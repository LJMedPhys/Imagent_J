"""detached.py — run a long script WITHOUT the supervisor waiting for it.

Normally `execute_script` blocks: it starts a subprocess and sits in `run.wait()`
until the script ends, so the whole agent graph is parked inside one tool call. For
a 20-minute Cellpose batch that is 20 minutes in which the supervisor cannot take a
model turn — which is why a note posted through `interject` cannot be read until the
batch finishes, and why the user cannot ask anything at all in the meantime.

Nothing about the script requires that wait. `run_control.SupervisedProcess` already
owns the process: its own process group, its own output buffer, its own terminator,
and the script watchdog supervising it. The supervisor is only holding the return
value. So a detached run is the same execution with the waiting moved off the graph:

    1. `execute_script` starts the run on a worker thread and returns immediately.
    2. The supervisor's turn ENDS. The user can chat; each message is a normal turn.
    3. When the script finishes, the result is submitted as a new turn.

Step 3 reuses what the GUI already does for undelivered notes (`AgentWorker.tasks`),
so turns stay SERIALISED — one graph run at a time. The script runs beside the graph,
never inside it, and two `supervisor.stream()` calls never overlap on one thread_id.

Detaching is MEASURED, not predicted
------------------------------------
Nothing can know a run will be long before running it: 20 images is seconds on a GPU
and ten minutes on a CPU, from the same template. So the gate is not an estimate in a
header — it is the clock. Every run starts normally and is waited on for
DETACH_AFTER_SECONDS; if it finishes inside that window the caller gets the output and
nothing about the run was different. Only a run that is STILL GOING at the deadline is
detached, and it is detached because it demonstrably needed to be.

The wait matters. Detaching a three-second script would make it slower and dearer, not
faster: one tool call becomes two model turns (a receipt, then the result). Waiting
first spends that only where it buys a conversation the user can actually use.

The cost at a short deadline is real and worth knowing: with a 10 s window most genuine
image-processing steps detach, so a multi-step pipeline pays roughly one extra model
turn per step. That is the trade — responsiveness against turns.

Scope, deliberately narrow
--------------------------
* A `imagentj-detach: <reason>` header (`#` or `//`, same 5-line window as
  `# imagentj-env:` in `tools/analyst_tools.py`) means "do not even wait the window —
  detach immediately", for a script already known to be long, like stage-3 training.
* **Subprocess runs only** — which is not the same as "Python only". Python always
  runs as a subprocess, and so does a self-contained batch Groovy script, which gets
  its own Fiji process (`_should_run_in_subprocess` in tools/script_tools.py). Both are
  safe to detach. What is not safe is an IN-PROCESS Groovy run: it executes on the
  app's own JVM beside the live Fiji windows, so the agent could act on ImageJ state a
  script is still mutating — and that path cannot be reliably killed either (see
  `_stopped_report`, which warns the script may still be running after an abort).
  Detachability and stoppability turn out to be the same property: owning the process.
* **Never an interactive script.** `WORKFLOW_FINETUNE_2_ANNOTATE.py` and the tile
  picker block on `napari.run()` ON PURPOSE — the script's return IS the "the human
  is finished" signal. Detaching those breaks the fine-tuning flow outright.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Callable, Dict, Optional

__all__ = [
    "wants_detach", "run_or_detach", "active", "set_completion_notifier",
    "DETACH_HEADER", "DETACH_AFTER_SECONDS", "disabled",
]

# How long to wait before handing the run back and freeing the conversation. Short
# enough that a human is never left staring at a blocked chat; long enough that the
# ordinary quick script never pays for a second model turn.
DETACH_AFTER_SECONDS = float(os.environ.get("IMAGENTJ_DETACH_AFTER", "10"))

# Benchmark mode waits instead of detaching (see `disabled`), and a wait needs two
# things detaching gave it for free: a VOICE and an END.
#
# The voice is the heartbeat. A waited run prints nothing between "starting" and
# "finished", so a 40-minute segmentation and a wedged subprocess produce byte-identical
# container logs, and the only way to tell them apart is to attach to the container and
# read /proc. That is how an arm came to sit for 20 minutes with nobody able to say
# whether it was working.
#
# The end is the cap. run_control's own backstop is 2 h, deliberately generous because
# it must not kill a legitimate overnight job in interactive use. An unattended ablation
# is the opposite case: nobody is watching, every arm blocks the next one, and a run
# that is genuinely going to need two hours has already invalidated the comparison. So
# benchmark runs get their own, much tighter cap, and blowing it FAILS THE SCRIPT rather
# than the whole arm — the agent is told what happened and can still finish and report.
#
# The cap must mean STUCK, not SLOW. A first version killed on wall clock alone and
# terminated a segmentation that was printing a line a second at the 30-minute mark —
# the arm then measured a truncated pipeline, which is worse than a long one. So the
# clock only decides when to START asking; what answers is `silent_for`, the same
# stuck-detector the script watchdog uses. A run still producing output is granted
# another window, up to an absolute ceiling.
BENCHMARK_SCRIPT_TIMEOUT = float(os.environ.get("IMAGENTJ_BENCHMARK_SCRIPT_TIMEOUT", "1800"))
BENCHMARK_SILENT_TIMEOUT = float(os.environ.get("IMAGENTJ_BENCHMARK_SILENT_TIMEOUT", "600"))
BENCHMARK_SCRIPT_MAX = float(os.environ.get("IMAGENTJ_BENCHMARK_SCRIPT_MAX", "5400"))
BENCHMARK_HEARTBEAT = float(os.environ.get("IMAGENTJ_BENCHMARK_HEARTBEAT", "60"))


def disabled() -> bool:
    """True when nothing may detach — a benchmark / auto-pilot run.

    Detaching exists so a human can keep talking to the agent while a long script
    runs. In BENCHMARK_MODE there is no human, so it buys nothing, and it actively
    breaks the run: handing the tool back ends the agent's TURN while the work
    continues in a subprocess, the benchmark's auto-finish fires on that early
    `finished` signal, and its one-shot `_bench_auto_finished` guard is spent
    before the real work is done. Observed as a run that completes its task and
    then sits for ever with a child process in waitpid.

    So: waiting is correct whenever the turn boundary is what something else is
    measuring.
    """
    return os.environ.get("BENCHMARK_MODE", "").lower() == "true"

DETACH_HEADER = "imagentj-detach:"

# Same shape and the same 5-line window as _ENV_HEADER_RE in tools/analyst_tools.py,
# but accepting `//` as well as `#` so a Groovy batch script can declare it the way it
# already declares `// imagentj-exec:`.
# The reason after the colon is required: it is what the user is shown while the run
# is in flight, and writing it forces the author to say why this one is long.
_DETACH_RE = re.compile(r"^(?:#|//)\s*imagentj-detach:\s*(.+?)\s*$")

_LOCK = threading.Lock()
_ACTIVE: Dict[int, dict] = {}
_ids = iter(range(1, 1 << 30))

# GUI hook: called with (label, output) when a detached run finishes, so the result
# can be submitted as a new turn. Unset outside the GUI (tests, benchmarks), where a
# detached run simply completes and is logged.
_completion_notifier: Optional[Callable[[str, str], None]] = None
# Called with (label,) the moment a run is handed back, so the transcript records WHEN
# it went to the background. The status line alone is not enough: it shows the present,
# and a user scrolling back later has no idea why the agent suddenly stopped reporting.
_detach_notifier: Optional[Callable[[str], None]] = None


def set_completion_notifier(fn: Optional[Callable[[str, str], None]]) -> None:
    global _completion_notifier
    _completion_notifier = fn


def set_detach_notifier(fn: Optional[Callable[[str], None]]) -> None:
    global _detach_notifier
    _detach_notifier = fn


def wants_detach(code: str) -> Optional[str]:
    """The reason from a `imagentj-detach: <reason>` header, or None."""
    for line in (code or "").splitlines()[:5]:
        m = _DETACH_RE.match(line.strip())
        if m and m.group(1).strip().lower() != "never":
            return m.group(1)
    return None


def never_detach(code: str) -> Optional[str]:
    """Why this script must be waited for however long it takes, or None.

    Only one thing genuinely qualifies: a script blocked on STDIN. Nobody can answer
    `input()` once the conversation has moved on — the subprocess would wait for ever
    with no way to reach it — so that one is waited for or not run at all.

    A window session is NOT this case, though an earlier version of this function
    treated it as one. See `interactive_reason`.
    """
    for line in (code or "").splitlines()[:5]:
        m = _DETACH_RE.match(line.strip())
        if m and m.group(1).strip().lower() == "never":
            return "declared `imagentj-detach: never`"
    if "input(" in (code or "").lower():
        return "blocked on stdin — nothing could answer it once detached"
    return None


def interactive_reason(code: str) -> Optional[str]:
    """Why this script is a person working in a window, or None.

    These detach IMMEDIATELY rather than after the usual wait: an annotation session
    runs for twenty minutes by design, and ten seconds of that is nothing but a
    blocked chat. The user is in a napari window; they are very likely to have
    questions WHILE they work, and until now the agent could not hear them.

    Detaching does not lose the "human is finished" signal — the script still exits
    when they close the window, and its report still arrives as a turn. What it
    changes is only who is waiting. The risk is the agent treating a receipt as a
    finished stage, which is a wording problem, handled in the receipt itself.
    """
    lowered = (code or "").lower()
    for marker in ("napari.run(", "run_picker(", "image_series_annotator(",
                   "annotator_2d(", "annotator_3d("):
        if marker in lowered:
            return f"a napari window is open and the user is working in it ({marker.rstrip('(')})"
    return None


def active() -> list:
    """Snapshot of the detached runs still going, newest last."""
    with _LOCK:
        return [dict(v) for v in sorted(_ACTIVE.values(), key=lambda d: d["started"])]


def _took(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}m {secs:02d}s" if mins else f"{secs}s"


def _spawn(label: str, work: Callable[[], str]) -> tuple[Dict[str, str], threading.Event]:
    """Start `work()` on a daemon thread; returns its result box and done flag.

    The thread carries the run's label because a thread dump is how a stuck
    container gets diagnosed, and "Thread-7" says nothing there.
    """
    box: Dict[str, str] = {}
    done = threading.Event()

    def _run():
        try:
            box["out"] = work()
        except Exception as exc:                # never let a worker thread die silently
            box["out"] = (f"SUMMARY: ERROR — the run raised before it could report: "
                          f"{type(exc).__name__}: {exc}\nSTATUS: ERROR")
        finally:
            done.set()

    threading.Thread(target=_run, name=f"run-{label[:24]}", daemon=True).start()
    return box, done


def _live_progress() -> str:
    """One line describing what the owned child processes are actually doing.

    Distinguishes "slow" from "wedged", which is the whole question a heartbeat is
    asked to answer: `silent_for` is the stuck-detector, and the tail is the evidence.
    """
    try:
        from .run_control import active_runs
        handles = active_runs()
    except Exception:
        return "no run registry"
    if not handles:
        return "no child process registered (work is in-process)"
    bits = []
    for h in handles:
        try:
            tail = (h.output_tail(200) or "").strip().replace("\n", " ⏎ ")
            # "script#N", never "run#N": N counts script EXECUTIONS inside this one
            # container, and an ablation reader seeing "run#2" reasonably concludes
            # the study repeated the arm. It did not — the agent re-ran a stage.
            bits.append(f"script#{h.run_id} {h.language} elapsed={_took(h.elapsed)} "
                        f"silent={_took(h.silent_for())} | …{tail[-160:]}")
        except Exception:
            bits.append(f"script#{getattr(h, 'run_id', '?')} (unreadable)")
    return " ;; ".join(bits)


def _quietest() -> Optional[float]:
    """Seconds since the busiest owned run last produced output, or None if unknown.

    The MINIMUM across runs on purpose: if anything is still talking, the work as a
    whole is progressing, and that is what decides whether a cap means "stuck".
    """
    try:
        from .run_control import active_runs
        handles = active_runs()
    except Exception:
        return None
    silences = []
    for h in handles:
        try:
            silences.append(float(h.silent_for()))
        except Exception:
            pass
    return min(silences) if silences else None


def _short(label: str, limit: int = 60) -> str:
    """A label short enough to read in a log line.

    `purpose` is written for the agent and routinely runs to 300 characters, which
    turns every heartbeat into a paragraph and buries the numbers that matter.
    """
    label = " ".join((label or "").split())
    return label if len(label) <= limit else label[:limit - 1].rstrip() + "…"


def _wait_bounded(label: str, work: Callable[[], str]) -> str:
    """Benchmark path: wait for `work()`, but talk while waiting and give up eventually."""
    started = time.time()
    short = _short(label)
    box, done = _spawn(label, work)
    print(f"[detach] benchmark mode — waiting for {short} instead of detaching "
          f"(cap {_took(BENCHMARK_SCRIPT_TIMEOUT)}, heartbeat every "
          f"{_took(BENCHMARK_HEARTBEAT)})", flush=True)

    last_reprieve = -1e9              # so the first reprieve always announces itself
    while not done.wait(BENCHMARK_HEARTBEAT):
        elapsed = time.time() - started
        print(f"[benchmark] still waiting on {short} — {_took(elapsed)} elapsed; "
              f"{_live_progress()}", flush=True)
        if elapsed < BENCHMARK_SCRIPT_TIMEOUT:
            continue

        # Past the cap — but is it stuck, or just long? A run that is still writing
        # output is doing the work it was asked to do, and killing it truncates the
        # very pipeline the arm is measuring. Only silence, or the absolute ceiling,
        # ends it.
        quiet = _quietest()
        if (quiet is not None and quiet < BENCHMARK_SILENT_TIMEOUT
                and elapsed < BENCHMARK_SCRIPT_MAX):
            # Said once, then every 10 min. The per-minute heartbeat above already
            # carries `silent=`, so repeating the reasoning every tick only buries it.
            if elapsed - last_reprieve >= 600:
                last_reprieve = elapsed
                print(f"[benchmark] {short} is past the "
                      f"{_took(BENCHMARK_SCRIPT_TIMEOUT)} cap but still producing "
                      f"output (last line {_took(quiet)} ago) — letting it run, "
                      f"ceiling {_took(BENCHMARK_SCRIPT_MAX)}", flush=True)
            continue

        why = (f"produced no output for {_took(quiet)}" if quiet is not None
               and quiet >= BENCHMARK_SILENT_TIMEOUT
               else f"hit the absolute {_took(BENCHMARK_SCRIPT_MAX)} ceiling")

        # Kill the child process group and let `work()` unwind normally — it returns
        # the run's own stopped-report, which is far more useful to the agent than
        # anything synthesised here.
        print(f"[benchmark] {short} {why} after {_took(elapsed)} — terminating it",
              flush=True)
        try:
            from .run_control import terminate_all
            terminate_all(reason=f"Benchmark watchdog: {why} after "
                                 f"{int(elapsed)}s", by="watchdog")
        except Exception as exc:
            print(f"[benchmark] terminate_all failed: {exc!r}", flush=True)

        if done.wait(60):
            return box.get("out", "")
        # The worker did not come back even after the kill. Returning is still
        # right: the agent gets a turn and the arm can finish and be measured,
        # which is the whole point of having a cap.
        print(f"[benchmark] {short} did not unwind after termination — "
              f"reporting it as failed and moving on", flush=True)
        return (
            f"SUMMARY: FAILED (stopped by the benchmark watchdog) — {label}\n"
            f"STATUS: ERROR\n"
            f"The script {why} and was terminated; it did not shut down cleanly, so "
            f"its output is unavailable and any files it wrote may be incomplete.\n"
            f"Do NOT re-run it unchanged — it will hit the same cap. Either fix "
            f"what made it hang, reduce its scope, or report what you have."
        )

    return box.get("out", "")


def run_or_detach(label: str, work: Callable[[], str],
                  wait: Optional[float] = None, reason: str = "",
                  interactive: str = "") -> str:
    """Run `work()`, waiting up to `wait` seconds; detach it if it outlasts that.

    Returns either the real output (finished in time — the caller cannot tell this
    module was involved) or a receipt, with the output delivered later through the
    completion notifier.

    `work` is the ordinary blocking execution the non-detached path would have made,
    so a detached run and a waited one do the same thing; only the waiting moves.
    """
    if disabled():
        # Wait it out — but audibly, and not for ever.
        return _wait_bounded(label, work)
    wait = DETACH_AFTER_SECONDS if wait is None else wait
    started = time.time()
    box, done = _spawn(label, work)

    if done.wait(wait):
        return box.get("out", "")               # finished in time: nothing changed

    # Still going. Hand the conversation back and let a waiter deliver the result.
    run_id = next(_ids)
    with _LOCK:
        _ACTIVE[run_id] = {"id": run_id, "label": label,
                           "reason": reason or f"still running after {_took(wait)}",
                           "started": started}

    def _deliver():
        done.wait()
        with _LOCK:
            _ACTIVE.pop(run_id, None)
        if _completion_notifier is None:
            return
        try:
            _completion_notifier(
                label,
                f"[DETACHED RUN FINISHED] {label} — took {_took(time.time() - started)}.\n"
                f"This is the result of the script you started earlier and did not "
                f"wait for. Carry on from here.\n\n{box.get('out', '')}"
            )
        except Exception:
            pass

    threading.Thread(target=_deliver, name=f"deliver-{run_id}", daemon=True).start()

    if _detach_notifier is not None:
        try:
            _detach_notifier(label)
        except Exception:
            pass

    if interactive:
        # A person is mid-task in a window. The failure to design against is the agent
        # reading this as a finished stage and moving on to the next one, so say what
        # has and has not happened in the plainest possible terms.
        return (
            f"SUMMARY: WAITING FOR THE USER (detached) — {label}\n"
            f"STATUS: RUNNING\n"
            f"{interactive}.\n\n"
            f"NOTHING HAS BEEN PRODUCED YET. The user is working right now; the script "
            f"saves their work itself and exits when they close the window, and only "
            f"then does its report arrive here as a new message.\n"
            f"Until that message arrives: do NOT start the next stage, do NOT re-run "
            f"this, do NOT read its output files, and do NOT state how much is done — "
            f"you cannot know.\n"
            f"You were detached so the user can TALK TO YOU while they work. Expect "
            f"questions about the task in front of them, and answer them."
        )

    why = reason or (f"it was still running after {_took(wait)}, so the conversation "
                     f"was handed back to you rather than left blocked")
    return (
        f"SUMMARY: STILL RUNNING (detached) — {label}\n"
        f"STATUS: RUNNING\n"
        f"Why you are seeing this instead of the result: {why}.\n\n"
        f"The script is running in its own process and you are NOT waiting for it. "
        f"Its full output will arrive as a new message when it finishes.\n"
        f"Do NOT re-run it, do not poll for it, and do not guess at its results. "
        f"Tell the user it is running and what it will produce, then either answer "
        f"whatever they ask next or end your turn."
    )

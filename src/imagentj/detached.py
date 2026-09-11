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
    "DETACH_HEADER", "DETACH_AFTER_SECONDS",
]

# How long to wait before handing the run back and freeing the conversation. Short
# enough that a human is never left staring at a blocked chat; long enough that the
# ordinary quick script never pays for a second model turn.
DETACH_AFTER_SECONDS = float(os.environ.get("IMAGENTJ_DETACH_AFTER", "10"))

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

    An INTERACTIVE script is the case the clock gets wrong. Stage 2 of fine-tuning
    blocks on `napari.run()` for as long as the human annotates — that block IS the
    result, because the script returning is the signal that they finished. Detach it
    at ten seconds and the agent is told "still running", carries on without the
    annotations, and the whole workflow silently proceeds on nothing.

    Two ways to be safe, because relying on either alone has failed before: an
    explicit `imagentj-detach: never` header, and a scan for the calls that mean "a
    window is open and a person is using it". The scan covers scripts nobody
    remembered to annotate — which, on the evidence of this project, is most of them.
    """
    for line in (code or "").splitlines()[:5]:
        m = _DETACH_RE.match(line.strip())
        if m and m.group(1).strip().lower() == "never":
            return "declared `imagentj-detach: never`"
    lowered = (code or "").lower()
    for marker in ("napari.run(", "run_picker(", "image_series_annotator(",
                   "annotator_2d(", "annotator_3d(", "input(", "plt.show("):
        if marker in lowered:
            return f"interactive: waits for the user ({marker.rstrip('(')})"
    return None


def active() -> list:
    """Snapshot of the detached runs still going, newest last."""
    with _LOCK:
        return [dict(v) for v in sorted(_ACTIVE.values(), key=lambda d: d["started"])]


def _took(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}m {secs:02d}s" if mins else f"{secs}s"


def run_or_detach(label: str, work: Callable[[], str],
                  wait: Optional[float] = None, reason: str = "") -> str:
    """Run `work()`, waiting up to `wait` seconds; detach it if it outlasts that.

    Returns either the real output (finished in time — the caller cannot tell this
    module was involved) or a receipt, with the output delivered later through the
    completion notifier.

    `work` is the ordinary blocking execution the non-detached path would have made,
    so a detached run and a waited one do the same thing; only the waiting moves.
    """
    wait = DETACH_AFTER_SECONDS if wait is None else wait
    started = time.time()
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

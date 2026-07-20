"""
Watchdog that supervises a running script and can terminate it mid-flight.

Why a separate thread rather than "let the supervisor check the output": while a
script runs, the supervisor is blocked inside the synchronous tool call that
started it. It gets the output only after the run returns, which is exactly the
situation we need to escape. Nothing on the agent's own control flow can observe
a run in progress, so supervision has to live outside it.

Two tiers, so the common case costs nothing:

  Tier 1 (free, always on) — output silence and total runtime, read from the
  RunHandle. No LLM involved.

  Tier 2 (LLM, only once a tripwire fires) — a small model sees the script, what
  it was for, how long it has been quiet, and the tail of its output, then rules
  CONTINUE or KILL.

Bias is heavily toward CONTINUE. Bioimage jobs are legitimately long and silent
(cellpose over a big stack, stitching, a slow plugin), and killing a 40-minute
segmentation on a false positive is far worse than waiting out a genuinely stuck
script. Every failure path here — LLM error, parse failure, missing key — resolves
to "leave it alone".
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

from . import run_control

log = logging.getLogger(__name__)

ENABLED = os.environ.get("IMAGENTJ_WATCHDOG", "1") not in ("0", "false", "False")
# Silence that trips the first LLM check. Long enough that a normal plugin step
# or model load does not trigger it.
SILENCE_SECONDS = float(os.environ.get("IMAGENTJ_WATCHDOG_SILENCE", "180"))
# Total runtime that trips a check regardless of how chatty the script is —
# catches a loop that prints forever without making progress.
MAX_RUNTIME_SECONDS = float(os.environ.get("IMAGENTJ_WATCHDOG_MAX_RUNTIME", "1500"))
POLL_SECONDS = 5.0
# After a CONTINUE verdict we back off multiplicatively, so a long legitimate job
# is not re-judged every few minutes at increasing cost.
BACKOFF_FACTOR = 2.0
# ...but the backoff is capped. Unbounded doubling means a run that goes stuck
# after the third check effectively stops being watched at all.
MAX_CHECK_GAP_SECONDS = float(os.environ.get("IMAGENTJ_WATCHDOG_MAX_GAP", "600"))

_MAX_CODE_CHARS = 3_000
_MAX_TAIL_CHARS = 2_500

# GUI hook — set by gui_runner so a watchdog kill can surface in the chat instead
# of only in the log.
_notifier: Optional[Callable[[str], None]] = None


def set_notifier(fn: Callable[[str], None]) -> None:
    global _notifier
    _notifier = fn


def _notify(message: str) -> None:
    if _notifier is None:
        return
    try:
        _notifier(message)
    except Exception:
        log.exception("watchdog notifier failed")


_VERDICT_PROMPT = """You are a watchdog supervising a running bioimage-analysis script.

Your ONLY job is to decide whether this run should be killed right now. You are not \
reviewing code quality and you cannot edit anything.

Default to CONTINUE. These scripts routinely run for many minutes with no output at \
all — loading models, segmenting large stacks, stitching tiles, writing big files. \
Silence alone is NOT evidence of a problem.

Answer KILL only on positive evidence the run is not going to finish usefully:
  - the same output repeats over and over (spinning loop)
  - it is blocked waiting for input that will never arrive (a prompt, a dialog, stdin)
  - it hit a fatal error and is now hanging instead of exiting
  - it is clearly doing the wrong thing (e.g. writing to the wrong location,
    reprocessing the same file endlessly, an obvious runaway)
  - it is in an UNBOUNDED WAIT: a loop polling for some external event (a file
    appearing, a lock clearing, a server responding) with no timeout and no exit
    condition it can reach on its own, and it has already waited far longer than
    that event should plausibly take

Distinguish those last two cases carefully, because they look identical from
outside:
  - COMPUTING silently (segmenting, filtering, training, writing a big file) has
    a definite end and will reach it. Silence here means CONTINUE, however long.
  - WAITING silently on something external that has not happened will never end
    by itself. Once that wait is clearly out of proportion, KILL — nothing is
    gained by waiting longer.
Read the code to tell them apart: a bounded `for` over known work is computing;
a `while (!condition)` poll with no timeout is waiting.

Otherwise answer CONTINUE.

--- SCRIPT PURPOSE ---
{purpose}

--- LANGUAGE ---
{language}

--- CODE ---
{code}

--- RUNTIME ---
Running for {elapsed_min}. No new output for {silent_min}.

--- RECENT OUTPUT (tail) ---
{tail}

Reply with exactly one line:
KILL: <short reason>
or
CONTINUE: <short reason>
"""


def _human_duration(seconds: float) -> str:
    """Minutes read better than raw seconds when judging 'is this too long?'."""
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    return f"{seconds / 60:.1f} minutes"


def _ask_llm(handle: "run_control.RunHandle") -> tuple[bool, str]:
    """
    Ask the model whether to kill. Returns (should_kill, reason).

    Imported lazily: agents.py builds the LLMs at import time and imports this
    module, so a top-level import here would cycle.
    """
    try:
        from .agents import llm_nano
    except Exception as exc:
        log.warning("watchdog: no LLM available (%s) — leaving run alone", exc)
        return False, ""

    prompt = _VERDICT_PROMPT.format(
        purpose=handle.purpose or "(not stated)",
        language=handle.language,
        code=handle.code[:_MAX_CODE_CHARS],
        elapsed_min=_human_duration(handle.elapsed),
        silent_min=_human_duration(handle.silent_for()),
        tail=handle.output_tail(_MAX_TAIL_CHARS) or "(no output yet)",
    )
    try:
        reply = llm_nano.invoke(prompt)
        text = (reply.content if hasattr(reply, "content") else str(reply)).strip()
    except Exception as exc:
        log.warning("watchdog: verdict call failed (%s) — leaving run alone", exc)
        return False, ""

    if isinstance(text, list):  # some providers return content blocks
        text = " ".join(str(part) for part in text)
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first.upper().startswith("KILL"):
        reason = first.split(":", 1)[1].strip() if ":" in first else "watchdog judged the run stuck"
        return True, reason
    return False, first


def _supervise(handle: "run_control.RunHandle") -> None:
    """Watch one run until it finishes or gets killed."""
    silence_threshold = SILENCE_SECONDS
    runtime_threshold = MAX_RUNTIME_SECONDS

    while True:
        time.sleep(POLL_SECONDS)

        if handle.terminated or handle.status == "finished":
            return
        if handle not in run_control.active_runs():
            return

        silent = handle.silent_for()
        elapsed = handle.elapsed
        if silent < silence_threshold and elapsed < runtime_threshold:
            continue

        trigger = (
            f"no output for {silent:.0f}s" if silent >= silence_threshold
            else f"running for {elapsed:.0f}s"
        )
        log.info("watchdog: checking run %s (%s)", handle.run_id, trigger)

        should_kill, reason = _ask_llm(handle)
        if should_kill:
            full_reason = f"{reason} (after {elapsed:.0f}s, {trigger})"
            log.warning("watchdog: killing run %s — %s", handle.run_id, full_reason)
            killed = handle.terminate(full_reason, by="watchdog")
            _notify(
                f"Watchdog stopped the running {handle.language} script: {full_reason}"
                if killed else
                f"Watchdog tried to stop the running {handle.language} script "
                f"({full_reason}) but it did not respond — it may still be running."
            )
            return

        # Cleared. Back off both tripwires so a long legitimate job is judged less
        # and less often — but cap the growth, otherwise a run that goes stuck
        # after a few clean verdicts would never be looked at again.
        silence_threshold = silent + min(silent * (BACKOFF_FACTOR - 1), MAX_CHECK_GAP_SECONDS)
        runtime_threshold = elapsed + min(elapsed * (BACKOFF_FACTOR - 1), MAX_CHECK_GAP_SECONDS)
        log.info(
            "watchdog: run %s cleared (%s); next check after %.0fs silence / %.0fs runtime",
            handle.run_id, reason or "continue", silence_threshold, runtime_threshold,
        )


def _on_run_registered(handle: "run_control.RunHandle") -> None:
    if not ENABLED:
        return
    threading.Thread(
        target=_supervise,
        args=(handle,),
        daemon=True,
        name=f"watchdog-{handle.run_id}",
    ).start()


def install() -> None:
    """Wire the watchdog into the run registry. Safe to call more than once."""
    run_control.set_register_hook(_on_run_registered)
    log.info(
        "watchdog %s (silence=%.0fs, max_runtime=%.0fs)",
        "enabled" if ENABLED else "disabled", SILENCE_SECONDS, MAX_RUNTIME_SECONDS,
    )

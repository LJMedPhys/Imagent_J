"""
Registry of in-flight script runs — makes a running script observable and killable.

Two things need this. The Stop button needs a handle it can terminate without
waiting for the script to finish, and the watchdog (see watchdog.py) needs to read
a script's output *while it runs* to judge whether it is stuck.

Both were impossible before: run_python_code() blocked in proc.communicate() and
only surfaced output at the end, and the Groovy path blocked the worker thread
inside the JVM with nothing watching it.

Each execution path registers a RunHandle carrying:
  - the code and why it was run (context for the watchdog's verdict)
  - a live output tail, either pushed (Python reader threads) or pulled
    (Groovy: the redirected System.out buffer is readable mid-run)
  - a terminator callable — the path knows how to kill itself; this module
    does not care whether that is a killpg or an ImageJ abort.

Termination is best-effort by design and the two paths differ sharply:
a Python subprocess dies on SIGKILL, whereas an in-JVM Groovy script can only be
asked to stop (see terminate_groovy_run in tools/script_tools.py for why).
"""

import itertools
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# How much output we retain per run. The watchdog only ever reads the tail, but a
# generous buffer keeps the final result intact for short/medium scripts.
_MAX_BUFFER_CHARS = 40_000
# What the watchdog actually gets shown.
_TAIL_CHARS = 4_000

_run_ids = itertools.count(1)


class RunHandle:
    """
    Live state of a single script execution.

    Thread-safety: every mutator takes _lock. The execution path writes output,
    the watchdog reads snapshots, and the GUI thread may call terminate() — all
    concurrently.
    """

    def __init__(
        self,
        language: str,
        code: str,
        purpose: str = "",
        terminator: Optional[Callable[[str], bool]] = None,
        output_provider: Optional[Callable[[], str]] = None,
    ):
        self.run_id = next(_run_ids)
        self.language = language
        self.code = code
        self.purpose = purpose
        self.started_at = time.monotonic()

        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._buffer_len = 0
        self._last_output_at = self.started_at
        # Pull-model runs (Groovy) expose their output through a callable instead
        # of pushing chunks; we diff its length to detect progress.
        self._output_provider = output_provider
        self._provider_len = 0

        self._terminator = terminator
        self.status = "running"          # running | finished | stopped | killed
        self.kill_reason = ""
        self.killed_by = ""              # user | watchdog
        # None until a stop is attempted; False means the run refused to die and
        # callers must say so instead of reporting a successful stop.
        self.terminate_succeeded: Optional[bool] = None
        self._terminate_lock = threading.Lock()
        # terminate() flips `status` immediately but the terminator itself can take
        # seconds to establish whether the run really stopped. Anyone reading
        # terminate_succeeded must wait for this, or they race the answer and see None.
        self._settled = threading.Event()

    # ── output ───────────────────────────────────────────────────────────

    def append_output(self, chunk: str) -> None:
        """Push model — called by the Python reader threads as bytes arrive."""
        if not chunk:
            return
        with self._lock:
            self._buffer.append(chunk)
            self._buffer_len += len(chunk)
            self._last_output_at = time.monotonic()
            while self._buffer_len > _MAX_BUFFER_CHARS and len(self._buffer) > 1:
                self._buffer_len -= len(self._buffer.pop(0))

    def _refresh_from_provider(self) -> None:
        """Pull model — poll the provider and treat growth as progress."""
        if self._output_provider is None:
            return
        try:
            current = self._output_provider()
        except Exception:
            return
        if len(current) != self._provider_len:
            self._provider_len = len(current)
            self._last_output_at = time.monotonic()
        self._buffer = [current[-_MAX_BUFFER_CHARS:]]
        self._buffer_len = len(self._buffer[0])

    def output_tail(self, chars: int = _TAIL_CHARS) -> str:
        with self._lock:
            self._refresh_from_provider()
            return "".join(self._buffer)[-chars:]

    # ── state ────────────────────────────────────────────────────────────

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def silent_for(self) -> float:
        """Seconds since the last byte of output. The primary stuck-detector."""
        with self._lock:
            self._refresh_from_provider()
            return time.monotonic() - self._last_output_at

    @property
    def terminated(self) -> bool:
        return self.status in ("stopped", "killed")

    # ── termination ──────────────────────────────────────────────────────

    def terminate(self, reason: str, by: str = "user") -> bool:
        """
        Ask the execution path to kill this run. Idempotent — the Stop button and
        the watchdog can race and only the first one takes effect.

        Returns True if the terminator reported success. False means the run
        could not be forced down (a CPU-bound Groovy script is the usual case)
        and the caller should surface that honestly rather than claim it stopped.
        """
        with self._terminate_lock:
            if self.terminated:
                return True
            self.status = "stopped" if by == "user" else "killed"
            self.kill_reason = reason
            self.killed_by = by

        if self._terminator is None:
            self.terminate_succeeded = False
            self._settled.set()
            return False
        try:
            self.terminate_succeeded = bool(self._terminator(reason))
        except Exception as exc:
            log.exception("terminator for run %s failed: %s", self.run_id, exc)
            self.terminate_succeeded = False
        finally:
            self._settled.set()
        return self.terminate_succeeded

    def wait_termination_settled(self, timeout: float) -> None:
        """Block until the termination attempt has a verdict (see _settled)."""
        self._settled.wait(timeout)

    def mark_finished(self) -> None:
        if self.status == "running":
            self.status = "finished"

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "language": self.language,
            "purpose": self.purpose,
            "elapsed": round(self.elapsed, 1),
            "silent_for": round(self.silent_for(), 1),
            "status": self.status,
            "output_tail": self.output_tail(),
        }


# ── registry ─────────────────────────────────────────────────────────────

_registry_lock = threading.Lock()
_active: list[RunHandle] = []
# Set by watchdog.py at import time so registering a run can start supervision
# without run_control importing the agent/LLM layer (which would cycle).
_on_register: Optional[Callable[[RunHandle], None]] = None


def set_register_hook(hook: Callable[[RunHandle], None]) -> None:
    global _on_register
    _on_register = hook


def register(handle: RunHandle) -> RunHandle:
    with _registry_lock:
        _active.append(handle)
    if _on_register is not None:
        try:
            _on_register(handle)
        except Exception:
            log.exception("run-register hook failed")
    return handle


def unregister(handle: RunHandle) -> None:
    with _registry_lock:
        try:
            _active.remove(handle)
        except ValueError:
            pass


def active_runs() -> list[RunHandle]:
    with _registry_lock:
        return list(_active)


def terminate_all(reason: str = "Stopped by user", by: str = "user") -> list[RunHandle]:
    """
    Terminate every in-flight run. Called by the Stop button.

    Returns the handles it acted on so the caller can report which ones actually
    went down — terminate() returning False is meaningful, not noise.
    """
    handles = active_runs()
    for handle in handles:
        handle.terminate(reason, by=by)
    return handles

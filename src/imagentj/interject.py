"""interject.py — user notes posted to the agent while a run is in flight.

The GUI blocks input for the whole of a run, so a user who spots a wrong turn
three minutes into a batch has no way to say so; the only control is Stop, which
throws the step away. This is the smaller, non-destructive alternative: park a
note here and let the agent pick it up at its OWN next model turn.

Delivery, and its limit
-----------------------
``InterjectMiddleware.before_model`` drains this queue and returns the notes as a
state update, so LangGraph merges AND checkpoints them — the note becomes part of
the thread's real message history, not a transient prompt decoration, and it
survives a reload like any other user message.

The note therefore lands at the next MODEL turn, not immediately. While the graph
is inside a long tool call (a 20-minute Cellpose batch in ``execute_script``)
there is no model turn to inject into, so the note waits for that tool to return.
That is inherent to steering an agent without cancelling its work: interrupting
mid-tool is a different feature built on ``run_control``/``stop_signal``, and it
can leave a half-written output.

Threading
---------
The GUI thread writes (``post``) and the agent worker thread reads (``drain``),
so every access takes the lock. ``bind_thread`` records which chat the worker is
currently running, because the middleware has no other way to know: ``Runtime``
carries no config, and reading langchain's ``var_child_runnable_config``
contextvar would be depending on private API.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Dict, List

__all__ = [
    "post", "drain", "pending", "peek",
    "bind_thread", "active_thread", "clear",
]

_LOCK = threading.Lock()
_PENDING: Dict[str, deque] = defaultdict(deque)
_ACTIVE: str = ""

# A note is a nudge, not a document. The cap stops a stuck agent (one that never
# reaches another model turn) from accumulating an unbounded backlog that would
# then all land at once and bury the actual task.
MAX_PENDING = 20


def bind_thread(thread_id: str) -> None:
    """Record the chat the worker is about to run, for the middleware to read."""
    global _ACTIVE
    with _LOCK:
        _ACTIVE = thread_id or ""


def active_thread() -> str:
    with _LOCK:
        return _ACTIVE


def post(thread_id: str, text: str) -> int:
    """Queue a note for `thread_id`. Returns the resulting queue depth.

    A depth of 0 means the note was rejected: blank, or the cap was already hit.
    """
    text = (text or "").strip()
    if not thread_id or not text:
        return 0
    with _LOCK:
        q = _PENDING[thread_id]
        if len(q) >= MAX_PENDING:
            return 0
        q.append(text)
        return len(q)


def drain(thread_id: str) -> List[str]:
    """Take every pending note for `thread_id`, in the order they were posted."""
    if not thread_id:
        return []
    with _LOCK:
        q = _PENDING.get(thread_id)
        if not q:
            return []
        notes = list(q)
        q.clear()
        return notes


def peek(thread_id: str) -> List[str]:
    """Pending notes without consuming them (for a flush after the run ends)."""
    if not thread_id:
        return []
    with _LOCK:
        return list(_PENDING.get(thread_id) or [])


def pending(thread_id: str) -> int:
    """How many notes are waiting — drives the queued-count in the status line."""
    if not thread_id:
        return 0
    with _LOCK:
        return len(_PENDING.get(thread_id) or [])


def clear(thread_id: str) -> None:
    with _LOCK:
        _PENDING.pop(thread_id, None)

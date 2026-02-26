"""
usage_tracker.py  –  Real-time token & tool-call metrics for ImagentJ.

Tracks:
  • input / output tokens  (aggregated across all LLM calls in a session)
  • total tool calls
  • failed tool calls       (on_tool_error fired)
  • soft-error tool calls   (execute_script / run_script_safe / run_python_code
                             returned OK but output contains error/warning signals)

Design notes:
  - UsageMetrics  : plain dataclass – thread-safe for reads; writes are
                    always on the LangGraph worker thread, reads on the Qt
                    main thread, so a single lock is enough.
  - UsageTrackerCallback : LangChain BaseCallbackHandler – plugged in via
                    config["callbacks"] so it works transparently alongside
                    LangSmith and requires zero changes to the agent graph.
  - MetricsSignalBridge   : QObject that lives on the Qt main thread and
                    receives signals from the callback (which runs on the
                    worker thread).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Patterns that flag a "soft error" in script output
# ---------------------------------------------------------------------------
_SOFT_ERROR_RE = re.compile(
    r"\b("
    r"error|exception|warning|failed|failure|"
    r"missingmethodexception|missingmethod|no such method|"
    r"groovyruntimeexception|scriptexception|"
    r"could not|unable to|traceback|illegalargument|"
    r"nullpointerexception|indexoutofbounds"
    r")\b",
    re.IGNORECASE,
)

# Only these tools are inspected for soft errors (the ones that execute code)
_EXECUTION_TOOLS = {"execute_script", "run_script_safe", "run_python_code"}


# ---------------------------------------------------------------------------
# Metrics container
# ---------------------------------------------------------------------------
@dataclass
class UsageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    soft_error_tool_calls: int = 0

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # Convenience ---------------------------------------------------------
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def snapshot(self) -> dict:
        """Thread-safe copy as a plain dict."""
        with self._lock:
            return {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "tool_calls": self.tool_calls,
                "failed_tool_calls": self.failed_tool_calls,
                "soft_error_tool_calls": self.soft_error_tool_calls,
            }

    def reset(self) -> None:
        with self._lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.tool_calls = 0
            self.failed_tool_calls = 0
            self.soft_error_tool_calls = 0


# ---------------------------------------------------------------------------
# Qt signal bridge  (must live on the main thread)
# ---------------------------------------------------------------------------
class MetricsSignalBridge(QObject):
    """Emits a signal whenever metrics change so the UI can update safely."""
    updated = Signal(dict)   # payload: UsageMetrics.snapshot()


# ---------------------------------------------------------------------------
# LangChain callback handler
# ---------------------------------------------------------------------------
class UsageTrackerCallback(BaseCallbackHandler):
    """
    Plugged into every supervisor.stream() call via config["callbacks"].
    Aggregates metrics into UsageMetrics and emits Qt signals via the bridge.
    """

    # Tell LangGraph to call us even inside sub-chains / tools
    raise_error = False

    def __init__(self, metrics: UsageMetrics, bridge: MetricsSignalBridge):
        super().__init__()
        self._m = metrics
        self._bridge = bridge

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token counts from whatever the provider puts in the response."""
        added_in = added_out = 0

        # Strategy 1: OpenAI-style llm_output dict
        usage = (response.llm_output or {}).get("token_usage") or \
                (response.llm_output or {}).get("usage")
        if isinstance(usage, dict):
            added_in  = usage.get("prompt_tokens",     0)
            added_out = usage.get("completion_tokens", 0)

        # Strategy 2: usage_metadata on the AIMessage (LangChain ≥ 0.2)
        if added_in == 0 and added_out == 0:
            for gen_list in response.generations:
                for gen in gen_list:
                    meta = getattr(getattr(gen, "message", None), "usage_metadata", None)
                    if meta:
                        added_in  += meta.get("input_tokens",  0)
                        added_out += meta.get("output_tokens", 0)

        # Strategy 3: response_metadata (some providers)
        if added_in == 0 and added_out == 0:
            for gen_list in response.generations:
                for gen in gen_list:
                    meta = getattr(getattr(gen, "message", None), "response_metadata", {}) or {}
                    tok = meta.get("token_usage") or meta.get("usage") or {}
                    added_in  += tok.get("prompt_tokens",     tok.get("input_tokens",  0))
                    added_out += tok.get("completion_tokens", tok.get("output_tokens", 0))

        if added_in or added_out:
            with self._m._lock:
                self._m.input_tokens  += added_in
                self._m.output_tokens += added_out
            self._emit()

    # ------------------------------------------------------------------
    # Tool tracking
    # ------------------------------------------------------------------
    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        with self._m._lock:
            self._m.tool_calls += 1
        self._emit()

    def on_tool_end(
        self,
        output: Any,
        *,
        name: str = "",
        **kwargs: Any,
    ) -> None:
        """Check execution-tool output for soft errors."""
        tool_name = name or (kwargs.get("serialized") or {}).get("name", "")
        if tool_name in _EXECUTION_TOOLS:
            if _SOFT_ERROR_RE.search(str(output)):
                with self._m._lock:
                    self._m.soft_error_tool_calls += 1
                self._emit()

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        **kwargs: Any,
    ) -> None:
        with self._m._lock:
            self._m.failed_tool_calls += 1
        self._emit()

    # ------------------------------------------------------------------
    def _emit(self) -> None:
        self._bridge.updated.emit(self._m.snapshot())
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest, AgentState
from langchain_core.messages import ToolMessage, SystemMessage, AIMessage
from langgraph.types import Command
from langchain.agents.middleware import TodoListMiddleware

try:  # py3.11+
    from typing import NotRequired
except ImportError:  # pragma: no cover
    from typing_extensions import NotRequired


# ── mode helpers ────────────────────────────────────────────────────────────
# The supervisor runs in one of several modes (advanced | quick | education),
# stored per-chat in graph state. "advanced" (or unset) is the full pipeline.

DEFAULT_MODE = "advanced"


def _state_mode(state) -> str:
    """Read the active mode from an agent state dict/object; default advanced."""
    if state is None:
        return DEFAULT_MODE
    if isinstance(state, dict):
        return state.get("mode") or DEFAULT_MODE
    return getattr(state, "mode", None) or DEFAULT_MODE


def _request_mode(request) -> str:
    return _state_mode(getattr(request, "state", None))


def _tool_name(t) -> str:
    """Best-effort name of a tool object / schema dict."""
    n = getattr(t, "name", None)
    if isinstance(n, str) and n:
        return n
    if isinstance(t, dict):
        return t.get("name") or (t.get("function") or {}).get("name") or ""
    return ""


class NarrationReminderMiddleware(AgentMiddleware):
    # Keeps the narration rule in the most-recent position on every turn so it
    # doesn't drift out of attention as tool history grows. Not persisted to state.
    # Only meaningful for the full pipeline, so it no-ops outside advanced mode.
    REMINDER = (
        """Reminder: before this turn's tool call(s), emit ONE short
        biologist-friendly sentence describing your intent. If a tool just
        returned, briefly acknowledge what came back in the same sentence
        (combine result + next intent — don't add a separate after-message)."""
    )

    def wrap_model_call(self, request, handler):
        if _request_mode(request) != "advanced":
            return handler(request)
        request.messages = list(request.messages) + [SystemMessage(content=self.REMINDER)]
        return handler(request)


# ── Multi-mode routing ──────────────────────────────────────────────────────

class AgentModeState(AgentState):
    """State fields for multi-mode operation, persisted per-chat (thread)."""
    mode: NotRequired[str]                 # "advanced" | "quick" | "education"
    course_plan: NotRequired[list]         # education: ordered chapter-id playlist
    course_progress: NotRequired[dict]     # education: {current, completed, notes}


@dataclass
class ModeSpec:
    """How one mode differs from the base graph. Any field left None is kept as-is.

    prompt: a system-prompt string, or a callable(state)->str (so the prompt can
            embed live state, e.g. the student's progress). None => keep the
            deep-agent-composed prompt (used by "advanced").
    tools:  the exact tool subset to expose this turn. None => keep the full
            registered tool set. Tools MUST be registered on the graph at build;
            this only narrows what the model is offered.
    model:  an alternate chat model for this mode. None => keep the default.
    """
    prompt: Optional[Callable[[dict], str] | str] = None
    tools: Optional[list] = None
    model: Any = None
    # Tool NAMES to drop from whatever is offered this turn, WITHOUT replacing the
    # whole set — so deepagents-injected tools (todos, filesystem, skills) and every
    # other tool are preserved. Used by "advanced" to hide the education tools while
    # keeping its own tools + builtins. Ignored when `tools` is also set.
    exclude_tools: Optional[list] = None


class ModeMiddleware(AgentMiddleware):
    """Routes each model call to a ModeSpec based on state['mode'].

    Sits in the user-middleware slot, which is *inner* to the deep-agent's
    prompt-composing base middleware — so overriding `system_message` here
    replaces the composed prompt for non-advanced modes, and overriding `tools`
    narrows the offered tools. "advanced" (the default) typically passes through
    untouched, preserving the current behaviour exactly.
    """

    state_schema = AgentModeState

    def __init__(self, modes: dict[str, ModeSpec], default: str = DEFAULT_MODE):
        super().__init__()
        self.modes = modes
        self.default = default

    def wrap_model_call(self, request, handler):
        mode = _request_mode(request)
        spec = self.modes.get(mode) or self.modes.get(self.default)
        if spec is None:
            return handler(request)

        overrides: dict = {}
        if spec.prompt is not None:
            state = getattr(request, "state", {}) or {}
            prompt = spec.prompt(state) if callable(spec.prompt) else spec.prompt
            if prompt:
                overrides["system_message"] = SystemMessage(content=prompt)
        if spec.tools is not None:
            overrides["tools"] = spec.tools
        if spec.model is not None:
            overrides["model"] = spec.model

        # Name-based exclusion: filter the CURRENTLY offered tools instead of
        # replacing them, so builtins and everything else survive. If the offered
        # list can't be read (empty), skip rather than blanking the toolset.
        if spec.exclude_tools and spec.tools is None:
            current = list(getattr(request, "tools", None) or [])
            drop = set(spec.exclude_tools)
            kept = [t for t in current if _tool_name(t) not in drop]
            if kept and len(kept) != len(current):
                overrides["tools"] = kept

        if overrides:
            request = request.override(**overrides)
        return handler(request)


class SafeToolLoggerMiddleware(AgentMiddleware):
     def wrap_tool_call(self, request: ToolCallRequest, handler):
        print(f"[TOOL LOG] Calling tool: {request.tool_call['name']}")
        try:
            result = handler(request)
        except Exception as e:
            print(f"[TOOL ERROR] {request.tool_call['name']} raised: {e}")
            return ToolMessage( content=f"Tool {request.tool_call['name']} failed with error: {str(e)}", tool_call_id=request.tool_call["id"] )
     # Handle LangGraph control commands
        if isinstance(result, Command):
            print(f"[TOOL LOG] Tool {request.tool_call['name']} returned a Command: {result}")
            return result # Handle standard ToolMessage
        if isinstance(result, ToolMessage):
             print(f"[TOOL LOG] Tool {request.tool_call['name']} returned ToolMessage")
             return result # Handle None or raw values print(f"[TOOL LOG] Tool {request.tool_call['name']} returned raw result: {repr(result)}")
        if result is None:
            result = "None (no output)"
            return ToolMessage( content=str(result), tool_call_id=request.tool_call["id"] )


class PhaseGuardState(AgentState):
    # Phases the guard has already handled on THIS thread — either it reminded
    # the supervisor to read the file, or it confirmed the file was in context.
    # Lives in graph state (not scanned from messages) so it survives
    # ContextEditingMiddleware, which wipes the very tool-call args / results the
    # guard would otherwise inspect. State is per-thread via the checkpointer, so
    # a fresh conversation starts with an empty set and re-prompts as needed.
    phase_reminders_sent: NotRequired[list[str]]


class PhaseGuardMiddleware(AgentMiddleware):
    """
    Guardrail that nudges the supervisor ONCE when it appears to be operating in
    a pipeline phase without having read the matching phase skill file.

    Design choices:
      - Does NOT inject phase content. The supervisor must read the file
        itself via smart_file_reader. The middleware only adds a one-line
        reminder when a gap is detected.
      - Fires AT MOST ONCE per phase per conversation. The set of handled
        phases is kept in durable graph state (`phase_reminders_sent`), not
        re-derived from message history every turn — so the reminder does not
        repeat (and the supervisor does not re-read the same phase file) just
        because the original read scrolled past the lookback window or was
        stripped by context editing.
      - Phase detection: scans recent messages for the most-recent signal —
        update_state_ledger(phase=...) tool call, or any ledger output
        containing a "CURRENT PHASE: <X>" line. If neither is found, the
        guard is silent (no false positives early in a session).
      - "File was read" detection: scans recent messages for a smart_file_reader
        call naming the matching phase file. When found, the phase is marked
        handled so a later context-edit can't resurrect the nag.
      - Lookback is bounded so the guard stays fast as conversation grows.
    """

    state_schema = PhaseGuardState

    PHASES_DIR = "/app/skills/workflow/supervisor_pipeline_phases"

    PHASE_FILES = {
        "1":  "phase_1_gathering.md",
        "2":  "phase_2_planning.md",
        "3":  "phase_3_setup.md",
        "4a": "phase_4a_io_check.md",
        "4b": "phase_4b_processing.md",
        "4c": "phase_4c_statistics.md",
        "4d": "phase_4d_plotting.md",
        "5":  "phase_5_summarization.md",
        "6":  "phase_6_documentation.md",
        "7":  "phase_7_qa.md",
    }

    LOOKBACK = 30

    _PHASE_RE = re.compile(r"CURRENT PHASE:\s*([0-9a-z]+)", re.IGNORECASE)

    _TRACK_RE = re.compile(r"TRACK:\s*([a-z]+)", re.IGNORECASE)

    def before_model(self, state, runtime=None):
        # Numbered pipeline phases only exist in the full analysis pipeline;
        # stay silent in quick/education modes.
        if _state_mode(state) != "advanced":
            return None
        msgs = list(state.get("messages", []))
        already = list(state.get("phase_reminders_sent") or [])

        # Fast track has no numbered phases, so the phase-file nag is pure
        # overhead there. Stay silent while the most recent track signal is
        # "fast"; the guard re-engages automatically if the request is later
        # escalated to "full" (which restores numbered phase signals).
        if self._on_fast_track(msgs):
            return None

        # Credit EVERY phase whose file was read in the recent window — including
        # a read-ahead for a phase not entered yet. Keying "handled" on the read
        # itself (not on the active phase at read time) is what stops a SECOND
        # read when the supervisor enters that phase later, after the original
        # read has scrolled out of the lookback window or been context-edited.
        handled = list(already)
        for pid, fname in self.PHASE_FILES.items():
            if pid not in handled and self._has_read_phase_file(msgs, fname):
                handled.append(pid)

        active_phase = self._detect_phase(msgs)
        phase_file = self.PHASE_FILES.get(active_phase) if active_phase else None

        if not phase_file or active_phase in handled:
            # Nothing to nudge about: no phase signal, an unknown phase id, or
            # the active phase's rules have already been seen. Persist any
            # newly-credited reads if the handled set actually grew.
            return {"phase_reminders_sent": handled} if handled != already else None

        reminder = SystemMessage(content=(
            f"[PHASE GUARD] You appear to be operating in Phase {active_phase} "
            f"without having read its rules in this conversation. Call "
            f"smart_file_reader('{self.PHASES_DIR}/{phase_file}') BEFORE "
            f"continuing with phase work. (This guard does not deliver the "
            f"rules itself; read the file yourself.)"
        ))
        # Mark handled in the SAME update so the reminder fires exactly once.
        return {"messages": [reminder], "phase_reminders_sent": handled + [active_phase]}

    def _on_fast_track(self, msgs):
        """True if the most recent track signal is 'fast'.

        Looks at the same bounded window as phase detection. A
        set_ledger_metadata(track=...) tool call or a "TRACK: <x>" line in any
        ledger output counts; the most recent wins so an escalation to "full"
        (which re-sets track) cleanly re-enables the guard.
        """
        for msg in reversed(msgs[-self.LOOKBACK:]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "set_ledger_metadata":
                        t = tc.get("args", {}).get("track")
                        if t:
                            return str(t).strip().lower() == "fast"
            if isinstance(msg, ToolMessage) and msg.content:
                m = self._TRACK_RE.search(str(msg.content))
                if m and not m.group(1).startswith("not"):
                    return m.group(1).strip().lower() == "fast"
        return False

    def _detect_phase(self, msgs):
        """Most recent ledger phase signal wins. Skips '[not set]' sentinels."""
        for msg in reversed(msgs[-self.LOOKBACK:]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "update_state_ledger":
                        p = tc.get("args", {}).get("phase")
                        if p:
                            return str(p).strip()
            if isinstance(msg, ToolMessage) and msg.content:
                m = self._PHASE_RE.search(str(msg.content))
                if m and not m.group(1).startswith("not"):
                    return m.group(1).strip()
        return None

    def _has_read_phase_file(self, msgs, phase_filename):
        """True if smart_file_reader was called/returned for the phase file."""
        for msg in reversed(msgs[-self.LOOKBACK:]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "smart_file_reader":
                        # smart_file_reader's parameter is `file_path` (not
                        # `path`); accept either so a renamed tool still works.
                        args = tc.get("args", {}) or {}
                        path = str(args.get("file_path") or args.get("path") or "")
                        if phase_filename in path:
                            return True
            if isinstance(msg, ToolMessage) and msg.content:
                if phase_filename in str(msg.content):
                    return True
        return False


class TodoDisplayMiddleware(TodoListMiddleware):
    def on_end(self, input, output, **kwargs):
        todos = getattr(self, "todos", [])
        if todos:
            formatted = "\n🧠 **Agent Plan / To-Do List:**\n" + "\n".join(
                [f"{i+1}. {t if isinstance(t, str) else t.get('task', str(t))}" for i, t in enumerate(todos)]
            )
            output["content"] += "\n\n" + formatted
        return output
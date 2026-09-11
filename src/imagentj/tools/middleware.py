import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest, AgentState
from langchain_core.messages import ToolMessage, SystemMessage, AIMessage
from langgraph.types import Command
from langchain.agents.middleware import TodoListMiddleware

from ..safety_filter import (
    filter_injected_blocks,
    find_sensitive_terms,
    is_bio_refusal,
    scrub_messages_report,
)


_log = logging.getLogger("imagentj")


def _truncate_tool_text(text: str, max_chars: int) -> str:
    """Bound one tool result while retaining both its summary and error tail."""
    if len(text) <= max_chars:
        return text

    marker_template = (
        "\n\n[TOOL OUTPUT TRUNCATED: original={original} characters, "
        "omitted={omitted}. Use a narrower query/path for more detail.]\n\n"
    )
    # Compute the marker twice because its own length depends on omitted digits.
    marker = marker_template.format(original=len(text), omitted=len(text) - max_chars)
    available = max(0, max_chars - len(marker))
    head_chars = (available * 3) // 4
    tail_chars = available - head_chars
    omitted = len(text) - head_chars - tail_chars
    marker = marker_template.format(original=len(text), omitted=omitted)
    available = max(0, max_chars - len(marker))
    head_chars = (available * 3) // 4
    tail_chars = available - head_chars
    return text[:head_chars] + marker + (text[-tail_chars:] if tail_chars else "")


def _bounded_tool_content(content, max_chars: int):
    """Return ToolMessage-compatible content no larger than ``max_chars``.

    Function-call outputs in this application are normally strings. For a list of
    content blocks, serialize the list only when it is too large; this preserves
    normal multimodal blocks while ensuring an oversized block cannot bypass the
    provider's per-output limit.
    """
    if isinstance(content, str):
        return _truncate_tool_text(content, max_chars)
    try:
        serialized = json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        serialized = str(content)
    if len(serialized) <= max_chars:
        return content
    return _truncate_tool_text(serialized, max_chars)


def _bounded_tool_message(message: ToolMessage, max_chars: int) -> ToolMessage:
    bounded = _bounded_tool_content(message.content, max_chars)
    if bounded is message.content or bounded == message.content:
        return message
    _log.warning(
        "tool output truncated before model call: tool=%s original_chars=%d limit=%d",
        getattr(message, "name", None) or "unknown",
        len(str(message.content)),
        max_chars,
    )
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": bounded})
    return message.copy(update={"content": bounded})


class BioRefusalRetryMiddleware(AgentMiddleware):
    """Catch provider-side biological-risk refusals at the model boundary.

    A refusal here would otherwise unwind the whole agent loop. Retry up to
    twice per call and only re-raise the *original* refusal if the provider
    also refuses every reformulation.

    Mount this LAST in an agent's ``middleware`` list. Composition makes the
    first entry outermost (``langchain.agents.factory._chain_model_call_handlers``),
    so last means innermost: the request seen here already carries the skill
    catalogue that ``SkillsMiddleware`` appended, and ``handler(retry_req)``
    goes straight to the model without re-injecting it. Mounted anywhere else,
    rung 1 below would be undone before the retry left the stack.

    The rungs, matching what the evidence implicates (see
    :mod:`imagentj.safety_filter`):

    1. drop the injected skill catalogue from the system message, and strip
       reasoning state from the outgoing messages;
    2. additionally neutralise pathogen proper nouns in the message prose.

    A rung that would change nothing is skipped rather than spending a call on
    a byte-identical replay. The caller's stored history is never modified;
    every rewrite acts on a copy of this attempt's outgoing payload.
    """

    def wrap_model_call(self, request, handler):
        try:
            return handler(request)
        except Exception as exc:
            if not is_bio_refusal(exc):
                raise
            last_exc = exc

        for neutralize in (False, True):
            retry_req = self._reformulate(request, neutralize=neutralize)
            if retry_req is None:
                continue
            try:
                return handler(retry_req)
            except Exception as exc:
                if not is_bio_refusal(exc):
                    raise
                last_exc = exc
        # Bare `raise` here would be a RuntimeError("No active exception to
        # reraise") — the except blocks above have already exited — which would
        # then fail is_bio_refusal() downstream and lose the diagnosis.
        raise last_exc

    def _reformulate(self, request, *, neutralize: bool):
        """Build the retry request for one rung, or None if it changes nothing."""
        overrides = {}
        changed = []

        system_message = getattr(request, "system_message", None)
        blocks = list(getattr(system_message, "content_blocks", None) or [])
        kept, dropped = filter_injected_blocks(blocks)
        if dropped:
            overrides["system_message"] = SystemMessage(content_blocks=kept)
            changed.append(f"dropped injected section(s) {', '.join(dropped)!r}")

        messages = list(getattr(request, "messages", []) or [])
        if messages:
            if neutralize:
                terms = find_sensitive_terms(messages)
                if terms:
                    changed.append(
                        "neutralised "
                        + ", ".join(f"{term}×{n}" for term, n in sorted(terms.items()))
                    )
            scrubbed, stats = scrub_messages_report(messages, neutralize=neutralize)
            if stats["reasoning_dropped"]:
                changed.append(f"stripped {stats['reasoning_dropped']} reasoning block(s)")
            if stats["reasoning_dropped"] or stats["terms_replaced"]:
                overrides["messages"] = scrubbed

        if not overrides:
            return None
        _log.warning(
            "model call refused by biological-risk filter — retrying: %s",
            "; ".join(changed),
        )
        return request.override(**overrides)


class ToolOutputLimitMiddleware(AgentMiddleware):
    """Enforce a per-ToolMessage limit at production and again before model I/O.

    The second check is deliberate: it also sanitizes messages restored from an
    older checkpoint or emitted inside a LangGraph Command. The provider limit is
    10 MiB for one function-call output; the much lower default here protects the
    useful context window and cost as well as avoiding the hard API rejection.
    """

    def __init__(self, max_chars: int | None = None):
        super().__init__()
        configured = max_chars if max_chars is not None else int(
            os.environ.get("IMAGENTJ_MAX_TOOL_OUTPUT_CHARS", "100000")
        )
        self.max_chars = max(2_000, min(int(configured), 1_000_000))

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        result = handler(request)
        if isinstance(result, ToolMessage):
            return _bounded_tool_message(result, self.max_chars)
        if isinstance(result, str):
            return _truncate_tool_text(result, self.max_chars)
        return result

    def wrap_model_call(self, request, handler):
        messages = list(request.messages)
        bounded = [
            _bounded_tool_message(message, self.max_chars)
            if isinstance(message, ToolMessage)
            else message
            for message in messages
        ]
        if any(new is not old for old, new in zip(messages, bounded)):
            request = request.override(messages=bounded)
        return handler(request)

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


# Read-only file access + search injected by the deep-agent backend and by
# FilesystemFileSearchMiddleware. A mode that narrows the toolset must still
# offer these: the skills catalogue points the model at /app/skills/** and
# these are how it gets there.
_BACKEND_FILE_TOOLS = frozenset({
    "ls", "read_file", "glob", "grep", "glob_search", "grep_search",
})


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
        request = request.override(messages=list(request.messages) + [SystemMessage(content=self.REMINDER)])
        return handler(request)

class VisionOptionState(AgentState):
    """Per-chat Vision Judge setting persisted by the graph checkpointer."""
    vision_enabled: NotRequired[bool]


class VisionOptionMiddleware(AgentMiddleware):
    """Condition the composed system prompt and tools on per-chat Vision state."""

    state_schema = VisionOptionState

    def __init__(self, enabled_prompt: str, disabled_prompt: str):
        super().__init__()
        self.enabled_prompt = enabled_prompt
        self.disabled_prompt = disabled_prompt

    def _disable_vision_in_prompt(self, system_message):
        """Substitute only the supervisor base inside the composed prompt.

        Deep-agent builds the system message before user middleware runs. Replacing
        the known Vision-on base with its Vision-off variant preserves every rule
        deep-agent composed around it (filesystem, skills, tool-use guidance, etc.).
        """
        if system_message is None:
            return SystemMessage(content=self.disabled_prompt)

        original_content = getattr(system_message, "content", system_message)
        if isinstance(original_content, list):
            replaced = False
            combined_content = []
            for block in original_content:
                if isinstance(block, str) and not replaced and self.enabled_prompt in block:
                    block = block.replace(self.enabled_prompt, self.disabled_prompt, 1)
                    replaced = True
                elif isinstance(block, dict) and not replaced:
                    text = block.get("text")
                    if isinstance(text, str) and self.enabled_prompt in text:
                        block = {
                            **block,
                            "text": text.replace(self.enabled_prompt, self.disabled_prompt, 1),
                        }
                        replaced = True
                combined_content.append(block)
        else:
            text = str(original_content or "")
            combined_content = text.replace(
                self.enabled_prompt,
                self.disabled_prompt,
                1,
            )

        if hasattr(system_message, "model_copy"):
            return system_message.model_copy(update={"content": combined_content})
        if hasattr(system_message, "copy"):
            return system_message.copy(update={"content": combined_content})
        return SystemMessage(content=combined_content)

    def wrap_model_call(self, request, handler):
        state = getattr(request, "state", {}) or {}
        if isinstance(state, dict):
            enabled = bool(state.get("vision_enabled", False))
        else:
            enabled = bool(getattr(state, "vision_enabled", False))

        if enabled:
            return handler(request)

        overrides = {
            "system_message": self._disable_vision_in_prompt(
                getattr(request, "system_message", None)
            )
        }

        current_tools = list(getattr(request, "tools", None) or [])
        overrides["tools"] = [
            tool for tool in current_tools if _tool_name(tool) != "vlm_judge"
        ]

        return handler(request.override(**overrides))


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
            # `tools` REPLACES the offered set, and the deep-agent builtins
            # (file access + search) are constructed by the backend, so no
            # mode's hand-written list can contain them. Replacing outright
            # therefore dropped them — while the skills instructions every
            # mode inherits still told the model to read /app/skills/** with
            # exactly those tools. It obliged, the name was not in the
            # offered list, and vLLM's parser left the call as raw markup in
            # the reply instead of a tool call. Keep whichever of them the
            # request already carries.
            keep = [
                t for t in (getattr(request, "tools", None) or [])
                if _tool_name(t) in _BACKEND_FILE_TOOLS
            ]
            have = {_tool_name(t) for t in spec.tools}
            overrides["tools"] = list(spec.tools) + [
                t for t in keep if _tool_name(t) not in have
            ]
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


_UNPARSED_TOOL_CALL_RE = re.compile(r"<tool_call>\s*([A-Za-z0-9_.\-]*)")


def _message_text(msg) -> str:
    """Flatten an AIMessage's content to plain text for markup scanning."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


class UnparsedToolCallRetryMiddleware(AgentMiddleware):
    """Recover when the server hands back a tool call as prose.

    A tool call only reaches the agent as a tool call if the *server* parses it
    out. vLLM's parser validates the emitted name against the tools the request
    offered (``parser_engine._is_valid_tool_name``); a name it cannot find is
    not an error — the markup is simply left in the assistant's text. The
    result is an AIMessage carrying a literal
    ``<tool_call>name<arg_key>...</arg_key></tool_call>`` with ``tool_calls``
    and ``invalid_tool_calls`` both empty. Nothing raises, nothing retries, and
    the agent ends its turn believing it has answered — the user sees raw
    markup and the run stalls. A cloud provider instead returns the bad call as
    an invalid tool call, which the agent can already see and correct, so this
    failure is specific to a local endpoint.

    Two causes are fixed at the source (the `rag_retrieve_docs` registration
    name and the builtins `ModeMiddleware` used to drop), but any future
    prompt/registration drift reintroduces it, so catch it here as well: tell
    the model the name is not available and what it may call instead, and let
    it choose again. If it still cannot, strip the markup and say so plainly
    rather than passing unparsed tags to the user.

    Mount inner to `ModeMiddleware` so `request.tools` is the narrowed list the
    model actually saw.
    """

    def __init__(self, max_retries: int = 2):
        super().__init__()
        self.max_retries = max_retries

    def wrap_model_call(self, request, handler):
        response = handler(request)

        for attempt in range(self.max_retries):
            bad = self._leaked_name(response)
            if bad is None:
                return response
            offered = sorted(
                n for n in (_tool_name(t) for t in (getattr(request, "tools", None) or [])) if n
            )
            _log.warning(
                "Model emitted an unparsed tool call for %r; not among the %d "
                "offered tools. Retrying (%d/%d).",
                bad, len(offered), attempt + 1, self.max_retries,
            )
            request = request.override(
                messages=list(getattr(request, "messages", []) or [])
                + [
                    SystemMessage(content=(
                        f"Your last reply tried to call a tool named '{bad}', which was "
                        "not accepted — it is not one of the tools available on this "
                        "turn, so the call was discarded and its markup was left in "
                        "your message as plain text. Do not repeat that name.\n\n"
                        f"Available tools this turn: {', '.join(offered) or '(none)'}\n\n"
                        "Either call one of those, using the normal tool-call mechanism "
                        "rather than writing the tags yourself, or answer directly if "
                        "no tool fits."
                    ))
                ]
            )
            response = handler(request)

        bad = self._leaked_name(response)
        if bad is not None:
            _log.error("Model kept emitting unparsed tool call %r; stripping markup.", bad)
            self._strip(response, bad)
        return response

    @staticmethod
    def _leaked_name(response) -> Optional[str]:
        """Name in leftover markup on a message that produced no tool call."""
        for msg in getattr(response, "result", None) or []:
            if not isinstance(msg, AIMessage):
                continue
            if getattr(msg, "tool_calls", None) or getattr(msg, "invalid_tool_calls", None):
                continue
            m = _UNPARSED_TOOL_CALL_RE.search(_message_text(msg))
            if m:
                return m.group(1) or "<unnamed>"
        return None

    @staticmethod
    def _strip(response, bad: str) -> None:
        """Last resort: replace the raw tags with a statement of what happened."""
        note = (
            f"\n\n[Agentic-J: a tool call to '{bad}' could not be dispatched — that tool "
            "is not available here. The step above did not run.]"
        )
        for msg in getattr(response, "result", None) or []:
            if not isinstance(msg, AIMessage):
                continue
            text = _message_text(msg)
            if "<tool_call>" not in text:
                continue
            cleaned = text.split("<tool_call>", 1)[0].rstrip()
            msg.content = cleaned + note


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

    def before_model(self, state, runtime=None):
        # Numbered pipeline phases only exist in the full analysis pipeline;
        # stay silent in quick/education modes. This single mode check replaces
        # the old fast/full "track" gate: a single self-contained operation is
        # quick mode now, so it never reaches this middleware at all.
        if _state_mode(state) != "advanced":
            return None
        msgs = list(state.get("messages", []))
        already = list(state.get("phase_reminders_sent") or [])

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

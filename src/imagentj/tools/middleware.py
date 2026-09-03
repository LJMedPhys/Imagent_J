import json
import logging
import os
import re

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest, AgentState
from langchain_core.messages import ToolMessage, SystemMessage, AIMessage, HumanMessage
from langgraph.types import Command
from langchain.agents.middleware import TodoListMiddleware

from .. import interject
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


class NarrationReminderMiddleware(AgentMiddleware):
    # Keeps the narration rule in the most-recent position on every turn so it
    # doesn't drift out of attention as tool history grows. Not persisted to state.
    REMINDER = (
        """Reminder: before this turn's tool call(s), emit ONE short 
        biologist-friendly sentence describing your intent. If a tool just 
        returned, briefly acknowledge what came back in the same sentence 
        (combine result + next intent — don't add a separate after-message)."""
    )

    def wrap_model_call(self, request, handler):
        request = request.override(messages=list(request.messages) + [SystemMessage(content=self.REMINDER)])
        return handler(request)


def _tool_name(tool) -> str:
    """Return a tool name from a LangChain tool object or tool-schema dict."""
    name = getattr(tool, "name", None)
    if isinstance(name, str) and name:
        return name
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name") or ""
    return ""


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


class InterjectMiddleware(AgentMiddleware):
    """Deliver notes the user typed WHILE the agent was running.

    The GUI parks them in :mod:`imagentj.interject`; this drains them at the next
    model turn and returns them as a state update, so LangGraph merges and
    checkpoints them. That matters: the note becomes a real message in the
    thread's history rather than a decoration on one model call, so it is visible
    to every later turn, to context editing, and to the transcript on reload.

    Returning ``{"messages": [...]}`` from ``before_model`` is the same mechanism
    PhaseGuardMiddleware already uses for its reminder.

    Notes are delivered as HumanMessage, not SystemMessage: they ARE the user
    speaking, and dressing them as system text would let the model treat them as
    infrastructure noise it can skip.
    """

    def before_model(self, state, runtime=None):
        notes = interject.drain(interject.active_thread())
        if not notes:
            return None
        _log.info("delivering %d queued user note(s) to the agent", len(notes))
        return {
            "messages": [
                HumanMessage(content=(
                    "[NOTE FROM THE USER, sent while you were working — read it "
                    "before your next action and adjust if it changes the plan]\n"
                    + note
                ))
                for note in notes
            ]
        }

"""Regression tests for per-chat Vision Judge middleware gating."""

import ast
from pathlib import Path


class _AgentMiddleware:
    pass


class _AgentState(dict):
    pass


class _SystemMessage:
    def __init__(self, content, marker=None):
        self.content = content
        self.marker = marker

    def model_copy(self, update):
        return _SystemMessage(
            content=update.get("content", self.content),
            marker=self.marker,
        )


class _Tool:
    def __init__(self, name):
        self.name = name


class _Request:
    def __init__(self, *, state=None, tools=None, messages=None, system_message=None):
        self.state = state or {}
        self.tools = list(tools or [])
        self.messages = list(messages or [])
        self.system_message = system_message

    def override(self, **values):
        return _Request(
            state=values.get("state", self.state),
            tools=values.get("tools", self.tools),
            messages=values.get("messages", self.messages),
            system_message=values.get("system_message", self.system_message),
        )


_VISION_PROMPT = (
    "supervisor base with VLM visual-checkpoint rules; "
    "after plotting call vlm_judge on each generated PNG figure"
)
_NO_VISION_PROMPT = "supervisor base without optional visual review"
_DEEP_AGENT_RULES = "deep-agent filesystem and skills rules"


def _load_middleware_namespace():
    source_path = Path(__file__).parents[1] / "src/imagentj/tools/middleware.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    selected = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "_tool_name",
            "VisionOptionState",
            "VisionOptionMiddleware",
        }:
            selected.append(node)

    namespace = {
        "AgentMiddleware": _AgentMiddleware,
        "AgentState": _AgentState,
        "NotRequired": lambda value: value,
        "SystemMessage": _SystemMessage,
    }
    future_annotations = ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )
    compiled = compile(
        ast.fix_missing_locations(
            ast.Module(body=[future_annotations, *selected], type_ignores=[])
        ),
        source_path,
        "exec",
    )
    exec(compiled, namespace)
    return namespace


def _run_middleware(state):
    namespace = _load_middleware_namespace()
    middleware = namespace["VisionOptionMiddleware"](
        enabled_prompt=_VISION_PROMPT,
        disabled_prompt=_NO_VISION_PROMPT,
    )
    request = _Request(
        state=state,
        tools=[_Tool("vlm_judge"), _Tool("execute_script")],
        messages=["conversation message"],
        system_message=_SystemMessage(
            f"{_VISION_PROMPT}\n\n{_DEEP_AGENT_RULES}",
            marker="deep-agent metadata",
        ),
    )
    return middleware.wrap_model_call(request, lambda updated: updated)


def test_vision_is_disabled_by_default_and_tool_is_hidden():
    result = _run_middleware({})

    assert [tool.name for tool in result.tools] == ["execute_script"]
    assert _VISION_PROMPT not in result.system_message.content
    assert "call vlm_judge on each generated PNG figure" not in result.system_message.content
    assert _NO_VISION_PROMPT in result.system_message.content
    assert _DEEP_AGENT_RULES in result.system_message.content
    assert result.system_message.marker == "deep-agent metadata"
    assert result.messages == ["conversation message"]


def test_enabled_chat_keeps_vision_tool_and_receives_checkpoint_rule():
    result = _run_middleware({"vision_enabled": True})

    assert [tool.name for tool in result.tools] == ["vlm_judge", "execute_script"]
    assert _VISION_PROMPT in result.system_message.content
    assert "call vlm_judge on each generated PNG figure" in result.system_message.content
    assert _NO_VISION_PROMPT not in result.system_message.content
    assert _DEEP_AGENT_RULES in result.system_message.content


def test_vision_setting_is_read_independently_from_each_chat_state():
    enabled_chat = _run_middleware({"vision_enabled": True})
    disabled_chat = _run_middleware({"vision_enabled": False})

    assert any(tool.name == "vlm_judge" for tool in enabled_chat.tools)
    assert all(tool.name != "vlm_judge" for tool in disabled_chat.tools)


def test_structured_system_content_preserves_deep_agent_rules_during_substitution():
    namespace = _load_middleware_namespace()
    middleware = namespace["VisionOptionMiddleware"](
        enabled_prompt=_VISION_PROMPT,
        disabled_prompt=_NO_VISION_PROMPT,
    )
    original_block = {
        "type": "text",
        "text": f"{_VISION_PROMPT}\n\ndeep-agent composed rules",
    }
    request = _Request(
        state={"vision_enabled": False},
        tools=[_Tool("vlm_judge")],
        system_message=_SystemMessage([original_block]),
    )

    result = middleware.wrap_model_call(request, lambda updated: updated)

    result_text = result.system_message.content[0]["text"]
    assert _VISION_PROMPT not in result_text
    assert _NO_VISION_PROMPT in result_text
    assert "deep-agent composed rules" in result_text

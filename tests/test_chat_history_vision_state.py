import ast
from pathlib import Path
from types import SimpleNamespace

class _Supervisor:
    def __init__(self):
        self.states = {
            "vision-on": {
                "vision_enabled": True,
                "messages": ["enabled chat message"],
            },
            "vision-off": {
                "vision_enabled": False,
                "messages": ["disabled chat message"],
            },
        }

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(values=self.states[thread_id])


def _load_chat_history_manager():
    source_path = Path(__file__).parents[1] / "src/imagentj/chat_history.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    original = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatHistoryManager"
    )
    methods = [
        node for node in original.body
        if isinstance(node, ast.FunctionDef) and node.name in {
            "get_messages_for_display",
            "get_state_values",
        }
    ]
    extracted = ast.ClassDef(
        name="ChatHistoryManager",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    future_annotations = ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )
    namespace = {}
    compiled = compile(
        ast.fix_missing_locations(
            ast.Module(body=[future_annotations, extracted], type_ignores=[])
        ),
        source_path,
        "exec",
    )
    exec(compiled, namespace)
    return namespace["ChatHistoryManager"]


def test_chat_history_reads_vision_setting_from_each_thread_state():
    manager = _load_chat_history_manager()()
    supervisor = _Supervisor()

    enabled = manager.get_state_values(supervisor, "vision-on")
    disabled = manager.get_state_values(supervisor, "vision-off")

    assert enabled["vision_enabled"] is True
    assert disabled["vision_enabled"] is False
    assert manager.get_messages_for_display(supervisor, "vision-on") == [
        "enabled chat message"
    ]

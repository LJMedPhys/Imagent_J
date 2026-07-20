"""Load isolated tool modules when the full container dependencies are absent."""

import importlib.util
import sys
import types
from functools import update_wrapper
from pathlib import Path


class _ToolWrapper:
    def __init__(self, func):
        self.func = func
        update_wrapper(self, func)

    def invoke(self, args):
        return self.func(**args)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


def _install_langchain_stubs():
    try:
        import langchain_core  # noqa: F401
        return
    except ImportError:
        pass

    core = types.ModuleType("langchain_core")
    tools = types.ModuleType("langchain_core.tools")
    messages = types.ModuleType("langchain_core.messages")
    tools.tool = lambda func: _ToolWrapper(func)
    messages.HumanMessage = type("HumanMessage", (), {"__init__": lambda self, **kwargs: None})
    sys.modules["langchain_core"] = core
    sys.modules["langchain_core.tools"] = tools
    sys.modules["langchain_core.messages"] = messages


def load_source_module(module_name: str, relative_path: str):
    _install_langchain_stubs()
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

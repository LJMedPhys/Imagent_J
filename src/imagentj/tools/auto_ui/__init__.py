"""auto_ui — window-scoped screenshot + template/VLM element location + xdotool clicking.

Internal helper used by auto_ui_tools.py LangChain tools.
Not imported directly by agents — import auto_ui_tools instead.
"""
from ._locator import locate_in_window

__all__ = ["locate_in_window"]

"""Shared element locator: template matching fast path, VLM fallback.

locate_in_window() is the single entry point used by all public tools.
It owns the screenshot lifecycle — the temp file is always deleted before returning.
"""
import logging

from . import _screenshot, _template, _vlm

log = logging.getLogger("imagentj.auto_ui")


def locate_in_window(
    window_id: str,
    description: str,
    template_name: str | None = None,
    use_active: bool = False,
) -> tuple[int, int]:
    """
    Find a UI element in a window and return its (x, y) in window-relative coords.

    Strategy:
      1. Capture the target window (scoped — never the full screen).
      2. If template_name is given, try template matching (< 100 ms).
      3. On miss, fall back to VLM (2–5 s).
      4. Delete the screenshot before returning, regardless of outcome.

    Args:
        window_id:     X11 window ID of the window to search.
        description:   Human-readable description sent to the VLM if needed.
        template_name: Filename in auto_ui/templates/ to try first (optional).
        use_active:    If True, capture the active (focused) window instead of
                       window_id. Useful for dialogs that grab focus on open.

    Returns:
        (x, y) pixel coordinates relative to the window's top-left corner.

    Raises:
        RuntimeError: if the element cannot be found by either method.
    """
    capture_fn = _screenshot.capture_active if use_active else (
        lambda: _screenshot.capture_window(window_id)
    )
    path = capture_fn()
    try:
        # --- fast path ---
        if template_name:
            match = _template.find_by_template(path, template_name)
            if match:
                log.debug(f"Template match '{template_name}' → {match}")
                return match

        # --- slow path ---
        log.debug(f"Template miss for '{template_name}', falling back to VLM")
        coords = _vlm.find_element_coords(path, description)
        if coords is None:
            raise RuntimeError(
                f"Element not visible in screenshot: '{description}'. "
                "The dialog may not be open yet, or the element may be off-screen."
            )
        return coords

    finally:
        import os
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

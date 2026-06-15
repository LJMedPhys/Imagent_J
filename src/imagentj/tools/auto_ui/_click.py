"""Low-level xdotool wrappers for mouse and keyboard actions."""
import subprocess
import time


def _xdotool(*args: str) -> None:
    result = subprocess.run(["xdotool", *args], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"xdotool {' '.join(args)} failed: {result.stderr.decode().strip()}"
        )


def move_and_click(abs_x: int, abs_y: int, button: int = 1) -> None:
    """Move to absolute screen coordinates and click the given mouse button."""
    _xdotool("mousemove", "--sync", str(abs_x), str(abs_y))
    time.sleep(0.05)
    _xdotool("click", str(button))


def click_in_window(window_id: str, rel_x: int, rel_y: int, button: int = 1) -> None:
    """Activate the window, then click at window-relative coordinates.

    Activating immediately before every click (not just at tool start) ensures
    that focus drifting to the chat box between clicks in a sequence does not
    cause clicks to land in the wrong window.
    """
    from ._window import activate_window, window_to_absolute
    activate_window(window_id)
    abs_x, abs_y = window_to_absolute(window_id, rel_x, rel_y)
    move_and_click(abs_x, abs_y, button)


def type_text(text: str, delay_ms: int = 20) -> None:
    """Type text into the currently focused widget."""
    _xdotool("type", f"--delay={delay_ms}", "--", text)


def key_press(key: str) -> None:
    """Send a key press (e.g. 'Return', 'Tab', 'Escape', 'ctrl+a')."""
    _xdotool("key", key)


def clear_and_type(text: str) -> None:
    """Select all existing text in the focused widget and replace it."""
    key_press("ctrl+a")
    time.sleep(0.05)
    type_text(text)


def hover(abs_x: int, abs_y: int, dwell_ms: int = 300) -> None:
    """Move to a position and dwell to trigger hover/submenu expansion."""
    _xdotool("mousemove", "--sync", str(abs_x), str(abs_y))
    time.sleep(dwell_ms / 1000)

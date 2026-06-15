"""X11 window lookup and geometry helpers for the Fiji process."""
import subprocess


def _xdotool(*args: str) -> str:
    result = subprocess.run(
        ["xdotool", *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"xdotool {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def get_active_window_id() -> str:
    return _xdotool("getactivewindow")


def get_fiji_window_ids() -> list[str]:
    """All window IDs belonging to the Fiji process, in creation order."""
    try:
        ids = _xdotool("search", "--class", "fiji").split()
        if ids:
            return ids
    except RuntimeError:
        pass
    try:
        ids = _xdotool("search", "--name", "Fiji").split()
        if ids:
            return ids
    except RuntimeError:
        pass
    raise RuntimeError("Fiji window not found on display. Is Fiji running?")


def get_main_fiji_window_id() -> str:
    """Return the main Fiji toolbar window (first created = index 0)."""
    return get_fiji_window_ids()[0]


def get_window_geometry(window_id: str) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) in absolute screen coordinates."""
    raw = _xdotool("getwindowgeometry", "--shell", window_id)
    vals: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, val = line.partition("=")
        vals[key.strip()] = int(val.strip())
    return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]


def window_to_absolute(window_id: str, rel_x: int, rel_y: int) -> tuple[int, int]:
    """Convert window-relative coordinates to absolute screen coordinates."""
    wx, wy, _, _ = get_window_geometry(window_id)
    return wx + rel_x, wy + rel_y


def activate_window(window_id: str) -> None:
    """Raise and focus a window so xdotool clicks land in the right place.

    Must be called before any click sequence when the chat GUI may have focus.
    """
    import time
    _xdotool("windowactivate", "--sync", window_id)
    _xdotool("windowfocus", "--sync", window_id)
    time.sleep(0.1)  # let the WM complete the focus switch


def activate_fiji_main() -> str:
    """Activate the main Fiji window and return its ID."""
    win_id = get_main_fiji_window_id()
    activate_window(win_id)
    return win_id

"""Window-scoped screenshot capture. All functions return a temp file path.
The caller MUST delete the file (use try/finally or the context manager below).
Screenshots are always scoped to a specific window — never the full screen.
"""
import contextlib
import os
import subprocess
import tempfile

from ._window import get_active_window_id, get_main_fiji_window_id


def capture_window(window_id: str) -> str:
    """Capture a single X11 window by ID. Returns path to a temporary PNG."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="fiji_cap_")
    os.close(fd)
    result = subprocess.run(
        ["import", "-window", window_id, path],
        capture_output=True,
    )
    if result.returncode != 0:
        os.unlink(path)
        raise RuntimeError(
            f"Screenshot of window {window_id} failed: {result.stderr.decode().strip()}"
        )
    return path


def capture_active() -> str:
    """Capture whichever window currently has focus (dialogs, dropdowns, etc.)."""
    return capture_window(get_active_window_id())


def capture_fiji_main() -> str:
    """Capture the main Fiji toolbar/main window."""
    return capture_window(get_main_fiji_window_id())


@contextlib.contextmanager
def scoped_active():
    """Context manager: yields path to screenshot of active window, deletes on exit."""
    path = capture_active()
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def scoped_fiji_main():
    """Context manager: yields path to screenshot of main Fiji window, deletes on exit."""
    path = capture_fiji_main()
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

"""OpenCV template matching — fast path for known Fiji UI elements.

Templates live in auto_ui/templates/ as PNG files.
Add new templates by cropping them from Fiji screenshots with any image editor.
Naming convention: <menu_or_context>_<element>.png
  e.g. menubar_analyze.png, dialog_ok_button.png, toolbar_run.png
"""
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_THRESHOLD = 0.85


def find_by_template(
    screenshot_path: str,
    template_name: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[int, int] | None:
    """
    Search for a template image inside a screenshot.

    Returns the (x, y) center of the best match in window-relative pixel
    coordinates, or None if no match exceeds the confidence threshold.
    """
    try:
        import cv2
    except ImportError:
        return None

    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        return None

    img = cv2.imread(screenshot_path, cv2.IMREAD_COLOR)
    tmpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if img is None or tmpl is None:
        return None

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return None

    th, tw = tmpl.shape[:2]
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2
    return cx, cy


def list_templates() -> list[str]:
    """Return filenames of all available templates."""
    return [p.name for p in sorted(TEMPLATES_DIR.glob("*.png"))]

"""LangChain tools for Auto-UI mode.

Design principle: each tool handles a complete logical interaction unit so that
long click-by-click workflows require as few tool calls as possible.

  click_menu_path       — full menu navigation (1+ levels) in one call
  perform_dialog_actions — all dialog field/button interactions in one call
  verify_fiji_state     — screenshot + VLM check without any clicking

Tools are always registered with the supervisor; the supervisor prompt controls
when they are used (only when operating_mode == "auto_ui").
"""
import logging
import time

from langchain_core.tools import tool

from .auto_ui._click import (
    click_in_window,
    clear_and_type,
    hover,
    key_press,
    move_and_click,
    type_text,
)
from .auto_ui._locator import locate_in_window
from .auto_ui._screenshot import capture_active, capture_fiji_main, scoped_active
from .auto_ui._vlm import find_element_coords
from .auto_ui._window import (
    activate_fiji_main,
    activate_window,
    get_active_window_id,
    get_fiji_window_ids,
    get_main_fiji_window_id,
    window_to_absolute,
)

log = logging.getLogger("imagentj.auto_ui")

# How long to wait for UI reactions (menus opening, dialogs appearing, etc.)
_MENU_SETTLE_S = 0.25
_DIALOG_SETTLE_S = 0.5
_CLICK_SETTLE_S = 0.1


# ─────────────────────────────────────────────────────────────────────────────
# click_menu_path
# ─────────────────────────────────────────────────────────────────────────────

@tool
def click_menu_path(menu_path: list[str]) -> str:
    """Navigate a Fiji menu hierarchy and click the final item, in one call.

    Handles the full sequence: click top-level menu bar item → wait for dropdown
    → click next item → repeat for submenus → click the final target.

    All screenshots are taken from the main Fiji window and are deleted
    immediately after use.

    Args:
        menu_path: Ordered list of menu labels from outermost to target.
                   Examples:
                     ["File", "Open..."]
                     ["Image", "Adjust", "Brightness/Contrast..."]
                     ["Plugins", "Analyze", "StarDist 2D"]

    Returns:
        A short summary of every step taken, or an error description.
    """
    if not menu_path:
        return "Error: menu_path must not be empty."

    steps: list[str] = []
    main_id = activate_fiji_main()  # ensure Fiji has focus before any clicking

    try:
        for i, label in enumerate(menu_path):
            is_first = i == 0

            # First item: look in the main Fiji window (menu bar).
            # Subsequent items: the active window is the open menu/submenu.
            window_id = main_id if is_first else get_active_window_id()

            rel_x, rel_y = locate_in_window(
                window_id=window_id,
                description=f'Menu item or menu bar entry labelled "{label}"',
                template_name=_menu_template(label),
                use_active=not is_first,
            )

            if i < len(menu_path) - 1:
                # Intermediate item: hover to expand submenu, then click.
                # activate_window is called inside click_in_window before each click.
                abs_x, abs_y = window_to_absolute(window_id, rel_x, rel_y)
                hover(abs_x, abs_y, dwell_ms=200)
                click_in_window(window_id, rel_x, rel_y)
                time.sleep(_MENU_SETTLE_S)
                steps.append(f"Opened '{label}'")
            else:
                # Final item: click to execute.
                click_in_window(window_id, rel_x, rel_y)
                time.sleep(_DIALOG_SETTLE_S)
                steps.append(f"Clicked '{label}'")

    except RuntimeError as exc:
        steps.append(f"Failed: {exc}")
        return " → ".join(steps)

    return " → ".join(steps)


def _menu_template(label: str) -> str | None:
    """Return a template filename for a menu label, if one exists."""
    from .auto_ui._template import list_templates, TEMPLATES_DIR
    candidate = f"menu_{label.lower().replace(' ', '_').replace('/', '_').replace('...', '')}.png"
    return candidate if (TEMPLATES_DIR / candidate).exists() else None


# ─────────────────────────────────────────────────────────────────────────────
# perform_dialog_actions
# ─────────────────────────────────────────────────────────────────────────────

@tool
def perform_dialog_actions(actions: list[dict]) -> str:
    """Perform a sequence of dialog interactions in the active Fiji dialog, in one call.

    Use this to fill fields, toggle checkboxes, select dropdown values, and
    click buttons — all in a single tool call. This is the preferred way to
    interact with Fiji plugin dialogs; one call per dialog, not one per field.

    Each action dict must have:
      "type"   : one of "fill" | "click" | "check" | "uncheck" | "select"
      "target" : plain-English description of the UI element to interact with
      "value"  : (required for "fill" and "select") the text/option to enter

    Action semantics:
      fill    — click the field, select-all, type the value
      click   — click a button or arbitrary element (e.g. "OK", "Run", "Cancel")
      check   — ensure a checkbox is checked (clicks it; no state verification)
      uncheck — ensure a checkbox is unchecked (clicks it; no state verification)
      select  — open a dropdown and choose an option by its visible label

    Example:
      [
        {"type": "fill",   "target": "Sigma (Radius)", "value": "2.0"},
        {"type": "select", "target": "Method dropdown", "value": "Otsu"},
        {"type": "check",  "target": "Preview checkbox"},
        {"type": "click",  "target": "OK button"}
      ]

    Returns:
        A step-by-step summary of what was done, or an error on first failure.
    """
    steps: list[str] = []

    # Resolve the target dialog window once. Dialogs are created after the main
    # Fiji window, so the last ID in the list is the most recently opened one.
    fiji_windows = get_fiji_window_ids()
    dialog_id = fiji_windows[-1]

    for i, action in enumerate(actions):
        action_type = action.get("type", "").lower()
        target = action.get("target", "")
        value = action.get("value", "")

        if not action_type or not target:
            steps.append(f"[{i}] Skipped — missing 'type' or 'target'")
            continue

        try:
            if action_type == "fill":
                rel_x, rel_y = locate_in_window(
                    dialog_id, f'Text or number input field for "{target}"',
                    use_active=True,
                )
                # click_in_window activates the window before every click
                click_in_window(dialog_id, rel_x, rel_y)
                time.sleep(_CLICK_SETTLE_S)
                clear_and_type(str(value))
                steps.append(f"[{i}] Filled '{target}' = '{value}'")

            elif action_type == "click":
                rel_x, rel_y = locate_in_window(
                    dialog_id, f'Button or clickable element: "{target}"',
                    use_active=True,
                )
                click_in_window(dialog_id, rel_x, rel_y)
                time.sleep(_DIALOG_SETTLE_S)
                steps.append(f"[{i}] Clicked '{target}'")

            elif action_type in ("check", "uncheck"):
                rel_x, rel_y = locate_in_window(
                    dialog_id, f'Checkbox labelled "{target}"',
                    use_active=True,
                )
                click_in_window(dialog_id, rel_x, rel_y)
                time.sleep(_CLICK_SETTLE_S)
                steps.append(f"[{i}] Toggled '{target}' ({action_type})")

            elif action_type == "select":
                # Open the dropdown — activate dialog before click
                rel_x, rel_y = locate_in_window(
                    dialog_id, f'Dropdown or combo box for "{target}"',
                    use_active=True,
                )
                click_in_window(dialog_id, rel_x, rel_y)
                time.sleep(_MENU_SETTLE_S)

                # Popup is now the active window; locate and click the option
                popup_id = get_active_window_id()
                opt_x, opt_y = locate_in_window(
                    popup_id, f'Dropdown option labelled "{value}"',
                    use_active=True,
                )
                click_in_window(popup_id, opt_x, opt_y)
                time.sleep(_CLICK_SETTLE_S)
                steps.append(f"[{i}] Selected '{value}' in '{target}'")

            else:
                steps.append(f"[{i}] Unknown action type '{action_type}' — skipped")

        except RuntimeError as exc:
            steps.append(f"[{i}] Failed on '{target}': {exc}")
            return "\n".join(steps) + "\n\nStopped at first failure."

    return "\n".join(steps)


# ─────────────────────────────────────────────────────────────────────────────
# verify_fiji_state
# ─────────────────────────────────────────────────────────────────────────────

@tool
def verify_fiji_state(expected_description: str) -> str:
    """Take a window-scoped screenshot of the active Fiji window and verify its state.

    Use this after clicks to confirm that the expected outcome occurred before
    proceeding to the next step. The screenshot is deleted immediately after
    the VLM analysis.

    Args:
        expected_description: Plain-English description of what should be visible.
                              Examples:
                                "the StarDist 2D dialog is open with a Sigma field"
                                "the Results table shows at least one row"
                                "the Brightness/Contrast dialog is closed"

    Returns:
        A short VLM observation of the current window state, including whether
        the expected condition appears to be met.
    """
    _VERIFY_SYSTEM = (
        "You are verifying the state of a Fiji/ImageJ window after a UI action.\n"
        "Describe what you see concisely (2-3 sentences). Then state whether the "
        "expected condition is met: start with CONFIRMED or NOT CONFIRMED.\n"
        "The image is already cropped to the specific window — do not reference "
        "elements outside the image."
    )

    import base64
    from langchain_core.messages import HumanMessage, SystemMessage
    from .imagej_tools import _get_vision_llm

    with scoped_active() as path:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        llm = _get_vision_llm()
        messages = [
            SystemMessage(content=_VERIFY_SYSTEM),
            HumanMessage(content=[
                {
                    "type": "text",
                    "text": f"Expected: {expected_description}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ]),
        ]
        response = llm.invoke(messages)
        return response.content.strip()

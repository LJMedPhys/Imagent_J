"""VLM-based element locator — slow path used when template matching fails.

Reuses the same vision LLM already configured in imagej_tools via
set_dialog_vision_llm(), so no separate initialisation is needed here.
"""
import base64
import json

_LOCATE_SYSTEM = """\
You are analyzing a screenshot of a Fiji/ImageJ window.
Find the center of the UI element described by the user.

Rules:
- Coordinates must be pixels relative to the TOP-LEFT corner of the provided image.
- The image is already cropped to the specific window — do not reference elements
  outside the image boundaries.
- Return ONLY a JSON object: {"x": <int>, "y": <int>}
- If the element is not visible, return: {"x": null, "y": null}
"""


def find_element_coords(screenshot_path: str, description: str) -> tuple[int, int] | None:
    """
    Ask the vision LLM to locate a UI element in a window-scoped screenshot.

    Returns (x, y) in window-relative pixel coordinates, or None if the element
    is not visible in the screenshot.
    """
    from imagentj.tools.imagej_tools import _get_vision_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    with open(screenshot_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    llm = _get_vision_llm()
    messages = [
        SystemMessage(content=_LOCATE_SYSTEM),
        HumanMessage(content=[
            {"type": "text", "text": f"Locate this element: {description}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]),
    ]

    response = llm.invoke(messages)
    text = response.content.strip()

    # Strip markdown code fences if the model wraps the JSON
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    coords = json.loads(text.strip())
    if coords.get("x") is None:
        return None
    return int(coords["x"]), int(coords["y"])

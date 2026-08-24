import base64
import io
import json
import os
import re
from pathlib import Path
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from imagentj.imagej_context import get_ij
from .metadata_tools import extract_file_metadata

_SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", "/app/skills"))


def _message_text(content) -> str:
    """Normalize a LangChain message's .content to plain text.

    Some providers (and multimodal responses in general) return content as a
    list of blocks (e.g. [{"type": "text", "text": "..."}]) instead of a bare
    string, so callers should not assume `.content` is always str.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _find_ui_docs_for_dialog(dialog_title: str) -> str:
    """
    Given a dialog title (e.g. 'CiliaQ on Linux - detection preferences'),
    look for a matching plugin skill folder under _SKILLS_DIR and return
    the concatenated contents of all UI_*.md files found there.
    Returns an empty string if nothing matches.
    """
    if not _SKILLS_DIR.exists():
        return ""

    # Extract a short plugin name: take the first meaningful token(s) before
    # separators like " - ", " on ", " (", numbers, or "preferences/settings/options"
    short = re.split(r'\s+[-–]\s+|\s+on\s+|\s+\(', dialog_title)[0]
    short = re.sub(r'\s+(preferences?|settings?|options?|parameters?|wizard).*', '',
                   short, flags=re.IGNORECASE).strip()
    slug = re.sub(r'[\s_\-]+', '', short).lower()  # "CiliaQ" → "ciliaq"

    # Score each skill folder by how much its name overlaps with the slug
    best_dir: Path | None = None
    best_score = 0
    for skill_dir in _SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        folder_slug = re.sub(r'[\s_\-]+(documentation|docs?|plugin)?$', '',
                              skill_dir.name, flags=re.IGNORECASE)
        folder_slug = re.sub(r'[\s_\-]+', '', folder_slug).lower()
        # Simple overlap score
        score = 0
        if slug == folder_slug:
            score = 100
        elif slug in folder_slug or folder_slug in slug:
            score = max(len(slug), len(folder_slug))
        if score > best_score:
            best_score = score
            best_dir = skill_dir

    if best_dir is None or best_score == 0:
        return ""

    # Read all UI_*.md files from the matched folder
    ui_files = sorted(best_dir.glob("UI_*.md"))
    if not ui_files:
        return ""

    parts = [f"[Skill documentation from: {best_dir.name}]"]
    for f in ui_files:
        try:
            parts.append(f"\n--- {f.name} ---\n{f.read_text(encoding='utf-8', errors='ignore')}")
        except Exception:
            pass
    return "\n".join(parts)

_DIALOG_VISION_SYSTEM = """You are an ImageJ/Fiji expert analysing a screenshot of a plugin dialog window.

Your task: extract every interactive element visible in the dialog so that an AI agent
can give the user precise, field-by-field parameter guidance.

Return a JSON object with these fields:

- dialog_title : string — the window title bar text
- fields : list of objects, one per visible interactive element:
    {
      "label":         string  — the exact text label shown next to the element,
      "type":          string  — "text_input" | "number_input" | "dropdown" | "checkbox" |
                                 "radio_button" | "slider" | "button" | "tab" | "label_only",
      "current_value": string  — the value currently shown (empty string if blank),
      "options":       list    — dropdown/radio options if visible, else [],
      "description":   string  — brief plain-English description of what this parameter controls
    }
- buttons : list of button labels visible at the bottom (e.g. ["OK", "Cancel", "Help"])
- warnings : list of any warning or info text visible in the dialog (empty list if none)

Be exhaustive — include every field, checkbox, and dropdown visible, in top-to-bottom order.
Do not guess values that are not visible in the screenshot."""

_dialog_llm = None

def set_dialog_vision_llm(llm) -> None:
    global _dialog_llm
    _dialog_llm = llm

def _get_vision_llm():
    if _dialog_llm is not None:
        return _dialog_llm
    # Fallback: construct directly (works only for direct OpenAI users)
    return ChatOpenAI(
        model="gpt-4o",
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY"),
    )


@tool
def ask_user(prompt: str) -> str:
    """
    Ask the user a question and return their input.
    Always ask in a way that a biologists without programming experience can understand.
    """
    return input(f"🖐 USER INPUT REQUIRED: {prompt}\n> ")


@tool
def load_image_ij(path: str)  -> object:
    """Load an image from a given path using ImageJ.

    Args:
        path (str): The file path to the image.

    Returns:
        [].
    """

    global image

    ij = get_ij()

    image = ij.io().open(path)
    return "Loaded image from " + path


@tool
def show_in_imagej_gui(path: str) -> str:
    """Open a file in the Fiji/ImageJ GUI so the user can see it.

    Behaves like the Fiji "File → Open..." menu — supports image formats
    (TIFF, PNG, JPG, BMP, CZI, LIF, ND2, etc.) as well as plain-text and
    table files (.txt, .csv, .tsv), which are shown in a text window or
    Results table.

    Use this ONLY to display something to the user. It does not return the
    file contents — for programmatic access use load_image_ij,
    smart_file_reader, or inspect_csv_header instead.

    Safe by design: empty, missing, non-file, or unreadable paths return a
    clear error string and never raise.

    Args:
        path: Absolute path to the file to display.

    Returns:
        A short status string: success message or human-readable error.
    """
    if not isinstance(path, str) or not path.strip():
        return "Could not open file: empty or invalid path."

    abs_path = os.path.abspath(path.strip())

    if not os.path.exists(abs_path):
        return f"Could not open file: path does not exist -> {abs_path}"
    if os.path.isdir(abs_path):
        return f"Could not open file: path is a directory, not a file -> {abs_path}"
    if not os.path.isfile(abs_path):
        return f"Could not open file: not a regular file -> {abs_path}"

    try:
        get_ij()  # ensure JVM/Fiji is up
        from scyjava import jimport
        IJ = jimport('ij.IJ')
        IJ.open(abs_path)
    except Exception as e:
        return f"Could not open file in ImageJ GUI ({abs_path}): {e!s}"

    return f"Opened in ImageJ GUI: {abs_path}"


@tool
def close_imagej_windows(
    titles: list[str] | None = None,
    close_all_images: bool = False,
    close_non_image: bool = False,
) -> str:
    """Close ImageJ/Fiji windows to clean up the GUI.

    Call this after a verification step or once the user has confirmed they
    no longer need a set of windows on screen — accumulating images, logs,
    and plot windows clutter Fiji and slow batch runs.

    The main ImageJ/Fiji control window is NEVER closed by this tool.

    Args:
        titles: Specific window titles to close (image windows or non-image
                windows like "Log", "Results", "ROI Manager", or plugin
                dialogs). Matches by exact title.
        close_all_images: If True, close every visible image window.
        close_non_image: If True, close visible non-image windows
                         (Log, Results, ROI Manager, exception popups, plugin
                         dialogs) — but never the main ImageJ control window.

    Returns:
        Human-readable summary of which windows were closed.
    """
    try:
        get_ij()
        from scyjava import jimport
        WindowManager = jimport('ij.WindowManager')
        Window = jimport('java.awt.Window')
    except Exception as e:
        return f"Could not access ImageJ window system: {e!s}"

    requested_titles = set(t for t in (titles or []) if isinstance(t, str) and t.strip())
    closed_images: list[str] = []
    closed_non_image: list[str] = []
    failed: list[str] = []

    # --- 1. Close image windows ---
    try:
        image_ids = WindowManager.getIDList() or []
    except Exception:
        image_ids = []
    for img_id in image_ids:
        try:
            imp = WindowManager.getImage(img_id)
            if imp is None:
                continue
            title = str(imp.getTitle())
            if close_all_images or title in requested_titles:
                imp.changes = False  # suppress "save changes?" dialog
                imp.close()
                closed_images.append(title)
                requested_titles.discard(title)
        except Exception as e:
            failed.append(f"{title if 'title' in dir() else '?'}: {e!s}")

    # --- 2. Close non-image windows (Log, Results, dialogs, etc.) ---
    if close_non_image or requested_titles:
        try:
            windows = list(Window.getWindows())
        except Exception:
            windows = []
        for win in windows:
            try:
                if not win.isVisible():
                    continue
                try:
                    title = str(win.getTitle())
                except Exception:
                    title = ""
                # Never close the main ImageJ/Fiji control window
                if _is_main_imagej_window(title):
                    continue
                want_close = (close_non_image and not _IMAGE_EXT_RE.search(title)) \
                              or (title in requested_titles)
                if not want_close:
                    continue
                # Dispose closes both Frame and Dialog without prompting
                try:
                    win.dispose()
                except Exception:
                    win.setVisible(False)
                closed_non_image.append(title or win.getClass().getSimpleName())
                requested_titles.discard(title)
            except Exception as e:
                failed.append(f"{title if 'title' in dir() else '?'}: {e!s}")

    parts = []
    if closed_images:
        parts.append(f"Closed {len(closed_images)} image window(s): {closed_images}")
    if closed_non_image:
        parts.append(f"Closed {len(closed_non_image)} non-image window(s): {closed_non_image}")
    if requested_titles:
        parts.append(f"Not found / already closed: {sorted(requested_titles)}")
    if failed:
        parts.append(f"Failed to close: {failed}")
    if not parts:
        parts.append("No windows matched the request — nothing to close.")
    return " | ".join(parts)


def _is_main_imagej_window(title: str) -> bool:
    if not title:
        return False
    tl = title.lower()
    return tl == "fiji" or "imagej" in tl


@tool
def inspect_all_ui_windows():
    """
    Inspect everything visible in the ImageJ UI:
    1. Image Windows (title, file path, dimensions, bit depth, min/max stats)
    2. Results Tables (row/column counts)
    3. ROI Manager (ROI count)
    4. Log Window (full text content)
    5. Console / Script Editor console tab (stdout/stderr from running scripts)
    6. Exception/Error Windows (full stack trace text)

    Call this whenever the user mentions an error in the console, script editor,
    or exception window, or to verify what is currently open in Fiji.
    """
    ij = get_ij()

    # Correct way to import Java classes in PyImageJ
    from scyjava import jimport
    WindowManager = jimport('ij.WindowManager')
    ResultsTable = jimport('ij.measure.ResultsTable')
    RoiManager = jimport('ij.plugin.frame.RoiManager')
    Frame = jimport('java.awt.Frame')

    all_inspections = {
        "images": [],
        "tables_and_text": []
    }

    # --- 1. Inspect Image Windows ---
    image_ids = WindowManager.getIDList()
    if image_ids:
        for img_id in image_ids:
            imp = WindowManager.getImage(img_id)
            try:
                # Resolve the on-disk path so the agent can pass it to other tools
                file_path = None
                file_path_note = None
                try:
                    fi = imp.getOriginalFileInfo()
                    if fi is not None and fi.directory and fi.fileName:
                        import os as _os
                        candidate = _os.path.join(str(fi.directory), str(fi.fileName))
                        if _os.path.exists(candidate):
                            file_path = candidate
                        else:
                            file_path_note = f"path from ImageJ ({candidate}) does not exist on disk — ask the user for the actual file location"
                except Exception:
                    pass

                # Convert ImagePlus to Dataset for stats
                dataset = ij.py.to_dataset(imp)

                min_val = ij.op().stats().min(dataset).getRealDouble()
                max_val = ij.op().stats().max(dataset).getRealDouble()

                entry = {
                    "title": imp.getTitle(),
                    "file_path": file_path,
                    "dimensions": f"{imp.getWidth()}x{imp.getHeight()}x{imp.getNSlices()}",
                    "stats": {"min": min_val, "max": max_val},
                    "bit_depth": imp.getBitDepth()
                }
                if file_path_note:
                    entry["file_path_note"] = file_path_note
                all_inspections["images"].append(entry)
            except Exception as e:
                all_inspections["images"].append({"title": imp.getTitle(), "file_path": None, "error": str(e)})

    # --- 2. Inspect Non-Image Windows ---
    # Use Window.getWindows() (not Frame.getFrames()) to also catch Dialogs,
    # which is what Fiji uses for many error/exception popups.
    IJ = jimport('ij.IJ')
    Window = jimport('java.awt.Window')

    def _collect_text_recursive(root):
        """Return all non-empty getText() values from root and every descendant."""
        parts = []
        try:
            t = str(root.getText())
            if t.strip():
                parts.append(t)
        except Exception:
            pass
        try:
            for child in root.getComponents():
                parts.extend(_collect_text_recursive(child))
        except Exception:
            pass
        return parts

    def _get_window_title(win):
        try:
            return str(win.getTitle())
        except Exception:
            try:
                return win.getClass().getSimpleName()
            except Exception:
                return ""

    for win in Window.getWindows():
        try:
            if not win.isVisible():
                continue
            title = _get_window_title(win)

            if title == "Results":
                rt = ResultsTable.getResultsTable()
                all_inspections["tables_and_text"].append({
                    "type": "Results Table",
                    "rows": rt.size(),
                    "columns": rt.getLastColumn() + 1
                })
            elif title == "ROI Manager":
                rm = RoiManager.getInstance()
                all_inspections["tables_and_text"].append({
                    "type": "ROI Manager",
                    "roi_count": rm.getCount() if rm else 0
                })
            elif title == "Log":
                log_text = ""
                try:
                    log_text = str(IJ.getLog()) or ""
                except Exception:
                    pass
                all_inspections["tables_and_text"].append({
                    "type": "Log Window",
                    "content": log_text[-4000:] if len(log_text) > 4000 else log_text
                })
            elif "console" in title.lower() or "script editor" in title.lower():
                # Script Editor has a JTabbedPane; find the "Console" tab first.
                # Fall back to collecting all text if no tab is found.
                console_text = ""
                try:
                    JTabbedPane = jimport('javax.swing.JTabbedPane')

                    def _find_console_tab(comp):
                        try:
                            if isinstance(comp, JTabbedPane):
                                for i in range(comp.getTabCount()):
                                    if "console" in str(comp.getTitleAt(i)).lower():
                                        tab_comp = comp.getComponentAt(i)
                                        parts = _collect_text_recursive(tab_comp)
                                        return "\n".join(parts)
                        except Exception:
                            pass
                        try:
                            for child in comp.getComponents():
                                result = _find_console_tab(child)
                                if result:
                                    return result
                        except Exception:
                            pass
                        return ""

                    console_text = _find_console_tab(win)
                    if not console_text.strip():
                        # No tabbed pane found — grab all text in the window
                        console_text = "\n".join(_collect_text_recursive(win))
                except Exception as e:
                    console_text = f"(could not read console: {e})"

                if console_text.strip():
                    all_inspections["tables_and_text"].append({
                        "type": "Console",
                        "title": title,
                        "content": console_text[-4000:] if len(console_text) > 4000 else console_text
                    })
            elif "exception" in title.lower() or "error" in title.lower():
                parts = _collect_text_recursive(win)
                text_content = "\n".join(parts)
                print(f"[inspect_ui] Exception window '{title}': found {len(parts)} text parts, {len(text_content)} chars")
                all_inspections["tables_and_text"].append({
                    "type": "Exception Window",
                    "title": title,
                    "content": text_content[-4000:] if len(text_content) > 4000 else text_content
                })
        except Exception as e:
            print(f"[inspect_ui] Skipped window: {e}")

    return str(all_inspections)


# Titles of known non-dialog Fiji windows to skip when looking for plugin dialogs
_SKIP_TITLES = {"ImageJ", "Fiji", "Log", "Results", "ROI Manager", "Recorder",
                "Brightness/Contrast", "Channels Tool", "Synchronize Windows",
                "Console"}

_IMAGE_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".gif",
                     ".fits", ".hdf5", ".h5", ".czi", ".lif", ".nd2", ".ims"}

_IMAGE_EXT_RE = re.compile(
    r'\.(' + '|'.join(e.lstrip('.') for e in _IMAGE_EXTENSIONS) + r')(\s|$|\[|\()',
    re.IGNORECASE,
)

def _is_non_dialog_window(title: str) -> bool:
    """Return True for windows that are definitely not plugin parameter dialogs."""
    if title in _SKIP_TITLES:
        return True
    # Main Fiji/ImageJ window variations  e.g. "(Fiji Is Just) ImageJ"
    tl = title.lower()
    if "imagej" in tl or tl == "fiji":
        return True
    # Image display windows — title contains a known image extension followed by
    # end-of-string, whitespace, or bracket (handles "img.tif (50%)", "stack.tif [1/10]")
    if _IMAGE_EXT_RE.search(title):
        return True
    return False


def _describe_screenshot(b64: str, system_prompt: str, text_prompt: str) -> dict:
    """Send one base64 PNG to the vision LLM and parse its JSON reply.

    Shared by the Fiji-dialog and napari paths: both ask a vision model for a
    structured description of what is on screen, and both have to cope with the
    model wrapping its JSON in a ``` fence. Returns the parsed object, or a dict
    with an "error" key if the call or the parse failed.
    """
    try:
        response = _get_vision_llm().invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": text_prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
            ]),
        ])
        raw = _message_text(response.content).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw).rstrip("` \n")
        parsed = json.loads(raw)
    except Exception as e:
        return {"error": f"Vision analysis failed: {e}"}
    # Callers index into the result, so never hand back a bare list/str even
    # when the model ignores the requested object shape.
    if not isinstance(parsed, dict):
        return {"error": "Vision model did not return a JSON object", "raw": parsed}
    return parsed


def _grab_fiji_dialogs() -> list[tuple[str, str]]:
    """Screenshot every visible Fiji plugin dialog. Returns [(title, base64_png)].

    Runs entirely in-process against the Fiji JVM's own AWT windows, so it is
    cheap and has no side effects — which is why the merged tool always tries
    this before reaching for napari.
    """
    from scyjava import jimport
    from PIL import Image as PILImage

    Window = jimport('java.awt.Window')
    Robot  = jimport('java.awt.Robot')
    Rectangle = jimport('java.awt.Rectangle')

    try:
        robot = Robot()
    except Exception as e:
        raise RuntimeError(f"Could not create AWT Robot: {e}") from e

    # Collect all visible windows that look like plugin dialogs
    dialog_images: list[tuple[str, str]] = []  # (title, base64_png)

    for win in Window.getWindows():
        try:
            if not win.isVisible():
                continue
            # getTitle() exists on Frame and Dialog but not all Window subtypes
            title = ""
            try:
                title = str(win.getTitle())
            except Exception:
                title = win.getClass().getSimpleName()

            # Skip known non-dialog Fiji windows and image display windows
            if not title or _is_non_dialog_window(title):
                continue

            bounds = win.getBounds()
            if bounds.width < 50 or bounds.height < 50:
                continue  # ignore tiny/invisible geometry

            # Capture the window region
            awt_rect = Rectangle(bounds.x, bounds.y, bounds.width, bounds.height)
            awt_img  = robot.createScreenCapture(awt_rect)

            # Convert java.awt.BufferedImage → PIL → base64 PNG
            width  = awt_img.getWidth()
            height = awt_img.getHeight()
            pixels = awt_img.getRGB(0, 0, width, height, None, 0, width)
            pil_img = PILImage.new("RGBA", (width, height))
            rgba_pixels = []
            for px in pixels:
                a = (px >> 24) & 0xFF
                r = (px >> 16) & 0xFF
                g = (px >>  8) & 0xFF
                b = (px      ) & 0xFF
                rgba_pixels.append((r, g, b, a if a else 255))
            pil_img.putdata(rgba_pixels)

            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            dialog_images.append((title, b64))
            print(f"[capture_ui_window] Captured Fiji dialog: '{title}' ({width}x{height})")

        except Exception as e:
            print(f"[capture_ui_window] Skipped window: {e}")
            continue

    return dialog_images


def _describe_fiji_dialogs(dialog_images: list[tuple[str, str]]) -> list[dict]:
    """Describe each captured Fiji dialog, enriched with that plugin's UI docs."""
    results = []
    for title, b64 in dialog_images:
        ui_docs = _find_ui_docs_for_dialog(title)
        text_prompt = f"Analyze this plugin dialog screenshot (window title: '{title}')."
        if ui_docs:
            text_prompt += (
                "\n\nThe following documentation describes the parameters of this plugin. "
                "Use it to enrich the 'description' field of each parameter with accurate, "
                "specific guidance (recommended values, valid ranges, what it controls):\n\n"
                + ui_docs
            )
            print(f"[capture_ui_window] Enriching '{title}' with UI docs ({len(ui_docs)} chars)")

        parsed = _describe_screenshot(b64, _DIALOG_VISION_SYSTEM, text_prompt)
        # Keep the window title even when the vision call failed, so the agent
        # can still tell the user *which* dialog it could not read.
        parsed.setdefault("dialog_title", title)
        results.append(parsed)
    return results


_NAPARI_VISION_SYSTEM = """You are a napari expert analysing a screenshot of the napari viewer window.

The window has up to four regions: layer controls (top-left, tools for the SELECTED layer),
layer list (bottom-left, one entry per open layer with an eye icon for visibility), the canvas
(the image itself), and — if a plugin is running (e.g. the "Segment Anything for Microscopy" /
micro_sam panel) — a docked widget panel, usually on the right, with its own fields and buttons.

Your task: extract every interactive element visible so an AI agent can give the user precise,
field-by-field guidance on what to click or set next.

Return a JSON object with these fields:

- window_title  : string — best guess at what's open (e.g. "napari — 2 layers, micro_sam panel
                  open"); empty string if you cannot tell.
- layers        : list of objects, one per row in the layer list:
    { "name": string, "type": string — "image"|"labels"|"points"|"shapes"|"unknown",
      "visible": boolean, "selected": boolean — true only if visually highlighted }
- dock_widget    : object or null — the docked plugin panel if one is visible:
    { "panel_title": string,
      "fields": list of { "label": string, "type": string — "text_input"|"number_input"|
                "dropdown"|"checkbox"|"radio_button"|"slider"|"button"|"progress"|"label_only",
                "current_value": string, "options": list, "description": string },
      "buttons": list of button labels visible in the panel }
- canvas_state   : string — brief plain-English note on what the canvas shows (an image, points/
                   masks overlaid, empty, a loading/progress indicator, ...)
- warnings       : list of any warning/error/info text visible anywhere in the window (empty
                   list if none)

Be exhaustive on the dock widget panel specifically — that is usually what the user needs help
with. Do not guess values that are not visible in the screenshot."""


_NAPARI_SKILL_DOC_PATHS = (
    _SKILLS_DIR / "napari" / "napari_general" / "SKILL.md",
    _SKILLS_DIR / "napari" / "micro_sam" / "UI_GUIDE.md",
)


def _napari_ui_docs() -> str:
    """Concatenate the napari layer-list/canvas primer and the micro_sam panel's UI guide,
    so the vision LLM has ground truth for layer names, button labels, and keyboard shortcuts
    instead of guessing them from pixels alone."""
    parts = []
    for path in _NAPARI_SKILL_DOC_PATHS:
        try:
            if path.exists():
                parts.append(f"\n--- {path.parent.name}/{path.name} ---\n"
                              + path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


def _extract_first_image_b64(mcp_content) -> str | None:
    if not isinstance(mcp_content, list):
        return None
    for block in mcp_content:
        if isinstance(block, dict) and block.get("type") == "image" and block.get("data"):
            return block["data"]
    return None


_NAPARI_SERVER = "napari-mcp"


def _napari_mcp_call(tool_name: str, arguments: dict, timeout: int) -> dict:
    """Call one napari-mcp tool. Returns the host payload, or {"error": ...}."""
    from .mcp_host_tools import load_mcp_server_configs, _call_server_tool, _run_async, _with_timeout

    configs = load_mcp_server_configs()
    if _NAPARI_SERVER not in configs:
        return {"error": f"MCP server '{_NAPARI_SERVER}' is not configured."}
    try:
        return _run_async(
            _with_timeout(
                _call_server_tool(_NAPARI_SERVER, configs[_NAPARI_SERVER], tool_name, arguments),
                timeout,
            )
        )
    except Exception as e:
        return {"error": f"Could not reach napari-mcp: {e}"}


def _napari_viewer_is_live() -> bool:
    """True only if a napari viewer ALREADY exists — without creating one.

    This probe is what makes target="auto" safe. napari-mcp's `screenshot` calls
    ensure_viewer(), so asking it for a picture COLD-STARTS napari plus software
    GL: a slow, very visible side effect for a user who was only ever asking
    about a Fiji dialog. `session_information` takes the other branch — it
    returns {"viewer": None, "message": "No viewer currently initialized..."}
    when nothing is open — so it answers the question for free.

    Any failure (server down, timeout, unexpected shape) is treated as "not
    live": the cost of a false negative is a missed screenshot the agent can
    retry with target="napari", while a false positive is a surprise cold start.
    """
    result = _napari_mcp_call("session_information", {}, 20)
    if "error" in result or result.get("status") != "ok":
        return False

    info = result.get("result", {}).get("parsed_content")
    if not isinstance(info, dict):
        return False
    # AUTO_DETECT mode reports an attached external viewer instead of `viewer`.
    if info.get("viewer_type") == "external":
        return True
    return info.get("viewer") is not None


def _describe_napari_window() -> dict:
    """Screenshot the live napari window and describe it. Assumes a viewer exists."""
    call_result = _napari_mcp_call("screenshot", {"canvas_only": False}, 90)
    if "error" in call_result:
        return call_result
    if call_result.get("status") != "ok":
        return {
            "error": call_result.get("message") or "napari screenshot failed",
            "detail": call_result,
        }

    b64 = _extract_first_image_b64(call_result.get("result", {}).get("content"))
    if not b64:
        return {"error": "napari-mcp did not return an image", "detail": call_result}

    ui_docs = _napari_ui_docs()
    text_prompt = "Analyze this napari window screenshot."
    if ui_docs:
        text_prompt += (
            "\n\nThe following documentation describes napari's layers, the micro_sam panel's "
            "fields, and keyboard shortcuts. Use it to enrich the 'description' field of each "
            "dock-widget field with accurate, specific guidance:\n\n" + ui_docs
        )

    return _describe_screenshot(b64, _NAPARI_VISION_SYSTEM, text_prompt)


@tool
def capture_ui_window(target: str = "auto") -> str:
    """
    Screenshot what is on screen and return a structured, field-by-field description
    of it — Fiji plugin dialogs, the napari window, or whichever of the two is open.

    Call this when the user is stuck, confused, or asks for help with something they
    can see: what a parameter means, which layer is selected, why a button is greyed
    out, what to click next. Never ask the user to take or send a screenshot instead.

    Args:
        target: "auto" (default) — look for Fiji plugin dialogs first, and fall back to
                  napari only if no dialog is open AND a napari viewer is already running.
                "fiji"   — only scan Fiji plugin dialogs.
                "napari" — only capture the napari window. Use this when you know napari
                  is the thing in question; unlike "auto" it will start the viewer if it
                  is not already open.

    Returns a JSON object:
      { "fiji_dialogs": [ {dialog_title, fields, buttons, warnings}, ... ],
        "napari_window": {window_title, layers, dock_widget, canvas_state, warnings} | null,
        "notes": [ ... ] }
    `fiji_dialogs` is an empty list and `napari_window` is null when nothing was found;
    `notes` explains why (e.g. napari was skipped because no viewer is running).
    """
    target = (target or "auto").strip().lower()
    if target not in {"auto", "fiji", "napari"}:
        return json.dumps({"error": f"Unknown target '{target}'. Use 'auto', 'fiji', or 'napari'."})

    out: dict = {"fiji_dialogs": [], "napari_window": None, "notes": []}

    if target in {"auto", "fiji"}:
        try:
            dialogs = _grab_fiji_dialogs()
        except Exception as e:
            dialogs = []
            out["notes"].append(f"Fiji dialog scan failed: {e}")
        if dialogs:
            out["fiji_dialogs"] = _describe_fiji_dialogs(dialogs)
        elif target == "fiji":
            out["notes"].append("No Fiji plugin dialogs are currently open.")

    if target == "napari":
        out["napari_window"] = _describe_napari_window()
    elif target == "auto" and not out["fiji_dialogs"]:
        # Nothing open in Fiji — try napari, but only if its viewer already exists,
        # so "auto" never cold-starts napari as a side effect.
        if _napari_viewer_is_live():
            out["napari_window"] = _describe_napari_window()
        else:
            out["notes"].append(
                "No Fiji plugin dialogs are open, and no napari viewer is running. "
                "Nothing to capture — ask the user what they have on screen, or call "
                "again with target='napari' to open the viewer."
            )

    return json.dumps(out, indent=2)


@tool
def extract_image_metadata(path: str) -> str:
    """Extract calibration, pixel intensity statistics, and suggested
    threshold/filter parameters from an image file.

    Returns a JSON string with pixel scale, intensity stats, recommended
    threshold values, filter sizes, and noise estimates.  Does NOT require
    an active ImageJ dataset — reads the file directly.

    If the file cannot be found or read, returns a JSON object with an
    `error` key and a human-readable `message` instead of raising — the
    supervisor can surface this to the user and continue.

    Args:
        path: Absolute file path to the image.
    """
    if not isinstance(path, str) or not path.strip():
        return json.dumps({
            "error": "invalid_path",
            "message": "extract_image_metadata called with an empty or non-string path.",
            "path": path,
        }, indent=2)

    abs_path = os.path.abspath(path.strip())

    try:
        result = extract_file_metadata(abs_path)
    except FileNotFoundError:
        return json.dumps({
            "error": "file_not_found",
            "message": f"No file at {abs_path}. Ask the user for the correct path "
                       f"or call inspect_folder_tree on the parent directory to list "
                       f"the available files.",
            "path": abs_path,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "error": "metadata_extraction_failed",
            "message": f"Could not read metadata from {abs_path}: {e!s}",
            "path": abs_path,
        }, indent=2)

    return json.dumps(result, indent=2, default=str)
# imagentj-env: napari-mcp
"""
micro_sam fine-tuning — STAGE 2 of 4: the human corrects the tiles.

Opens micro_sam's image-series annotator on the tiles built by stage 1, with the stock model's
guess already loaded into `committed_objects`, plus a small **Annotation Helper** panel that
reduces the whole job to three buttons: ADD an object (click, SAM outlines it), DRAW an
outline by hand (SAM tidies the trace), DELETE an object.

RUN THIS VIA python_data_analyst, NEVER via mcp__napari_mcp__execute_code. It opens its own
napari window and blocks on napari.run() until the human closes it — which is correct here
(the script's return IS the "human is finished" signal) but would kill an MCP call: that tool
runs on napari's Qt thread under a 90 s timeout, so the viewer, the VNC desktop and the agent
turn would all hang. python_data_analyst gives it a 7200 s supervised subprocess instead.

Work is saved tile by tile, when the human presses N. Re-running resumes at the first
unfinished tile (skip_segmented=True), so an interrupted session loses at most one tile.

When the window closes the script prints a per-tile status table. That table is what the agent
relays to the user and what decides whether stage 3 can start.

Next: WORKFLOW_FINETUNE_3_TRAIN.py

Run in the `napari-mcp` env. Edit TASK_DIR, execute.
"""
import os
import json
import glob
import time

import numpy as np
import tifffile

# ---- CONFIG -----------------------------------------------------------------
TASK_DIR = "/app/data/projects/demo/microsam_finetune"   # the folder stage 1 wrote
PRECOMPUTE_AMG_STATE = False   # True also caches the automatic-segmentation state so the
                               # annotator's "Automatic Segmentation" button is instant. Roughly
                               # doubles the startup wait; the pre-segmentation already covers it.
SHOW_HELPER = True             # the ADD / DELETE panel. Off = stock micro_sam annotator.
# -----------------------------------------------------------------------------

BANNER = r"""
================================================================================
  ANNOTATE {n} TILES        (full instructions: {instr})
================================================================================
  Fix the outlines so that INSIDE EACH SQUARE every object is outlined and
  nothing else is. Outlines only need to be roughly right.

  ADD an object     ->  click "ADD objects", click the object,  S ,  then  C
  DRAW an outline   ->  click "DRAW outline", trace the object, double-click to close,
                        then  S  (SAM tidies it)  and  C   -- C alone keeps it as drawn
  DELETE an object  ->  click "DELETE objects", click the object
  BAD OUTLINE       ->  delete it, then add it again (or DRAW it)
  TILE FINISHED     ->  press  N        <-- N is what SAVES the tile

  *** Press N on EVERY tile, INCLUDING THE LAST ONE. ***
  Closing the window without pressing N loses that tile (all earlier tiles are
  already saved, and restarting resumes at the first unfinished one).
================================================================================
"""


def ensure_model_cache(fallback_dir):
    """Point MICROSAM_CACHEDIR somewhere writable, and say so.

    micro_sam downloads its checkpoints with pooch into MICROSAM_CACHEDIR (default
    ~/.cache/micro_sam). In a container whose home is a named volume older than the image,
    that path can survive as a root-owned directory this process cannot write, and every
    model load then dies with `PermissionError: .../micro_sam/models` — a traceback that
    points at pooch and never mentions the volume. Probe it for real (mkdir + write, not a
    permission bit), fall back into the task folder, and carry over any weights already
    downloaded so the fallback costs no extra download."""
    import shutil

    current = os.environ.get("MICROSAM_CACHEDIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "micro_sam")
    models = os.path.join(current, "models")
    try:
        os.makedirs(models, exist_ok=True)
        probe = os.path.join(models, ".writable")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return current
    except OSError as exc:
        why = exc.strerror or str(exc)      # bind it: `exc` itself is gone after the block

    os.makedirs(os.path.join(fallback_dir, "models"), exist_ok=True)
    os.environ["MICROSAM_CACHEDIR"] = fallback_dir
    os.environ.setdefault("XDG_CACHE_HOME", os.path.dirname(fallback_dir))
    print(f"[annotate] model cache {current} is not writable ({why}) -> using {fallback_dir}")
    if os.path.isdir(models):
        for f in os.listdir(models):                       # reuse anything already downloaded
            src, dst = os.path.join(models, f), os.path.join(fallback_dir, "models", f)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy(src, dst)
                    print(f"[annotate]   carried over cached weight {f}")
                except OSError:
                    pass
    return fallback_dir


def _sam_mask_prompt(predictor, mask):
    """Refine a coarse binary mask with SAM, using the mask ITSELF as the prompt.

    SAM's prompt encoder takes three things: points, a box, and a coarse mask. The third is
    exactly what a hand-traced outline is, and it is the only one no annotator UI exposes —
    hence the universal advice to "use points", and the box as the usual fallback. A box
    cannot describe a concave nucleus. A mask can.

    Two details decide whether this works or silently returns nonsense. The mask goes in as
    LOW-RES LOGITS on the model's own 256x256 grid, and that grid covers the padded-to-square
    1024 input frame, not the image frame — resize straight to 256x256 and SAM refines a
    squashed, shifted copy of the outline, which looks like a model failure. And mask_input
    was trained as an ITERATIVE refinement signal, always accompanied by a point or box, so
    the outline's box and an interior point go in with it.

    Returns the refined boolean mask, or None when SAM's answer bears no resemblance to what
    the user drew — it likes to reply with the whole clump the object sits in.
    """
    from skimage.transform import resize
    from scipy.ndimage import distance_transform_edt

    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return None

    ys, xs = np.nonzero(mask)
    # SAM speaks XYXY and XY — (column, row), the opposite order to numpy indexing.
    kwargs = {
        "box": np.array([xs.min(), ys.min(), xs.max() + 1, ys.max() + 1], dtype=float),
        "multimask_output": False,
    }
    # The centroid of a concave shape can land outside it; the deepest interior pixel cannot.
    depth = distance_transform_edt(mask)
    py, px = np.unravel_index(int(np.argmax(depth)), depth.shape)
    kwargs["point_coords"] = np.array([[px, py]], dtype=float)
    kwargs["point_labels"] = np.array([1])

    tr = getattr(predictor, "transform", None)
    if tr is not None and hasattr(tr, "get_preprocess_shape"):
        side = int(getattr(tr, "target_length", 1024))
        nh, nw = tr.get_preprocess_shape(mask.shape[0], mask.shape[1], side)
        padded = np.zeros((side, side), np.float32)
        padded[:nh, :nw] = resize(mask.astype(np.float32), (nh, nw),
                                  order=0, preserve_range=True)
        low = resize(padded, (256, 256), order=0, preserve_range=True)
        kwargs["mask_input"] = (low * 20.0 - 10.0)[None].astype(np.float32)  # SAM cuts at 0
    else:
        print("[annotate] predictor has no .transform — box + point prompt only", flush=True)

    masks, scores, _ = predictor.predict(**kwargs)
    out = np.asarray(masks[0], dtype=bool)
    union = int(np.logical_or(out, mask).sum())
    iou = int(np.logical_and(out, mask).sum()) / union if union else 0.0
    print(f"[annotate] SAM refine: score={float(scores[0]):.3f} IoU-with-trace={iou:.2f}",
          flush=True)
    return None if (not out.any() or iou < 0.25) else out


def build_helper(viewer, manifest):
    """Dock a three-button panel: ADD (point prompts) / DRAW (polygon) / DELETE (fill with 0).

    Everything a beginner gets wrong here is a MODE problem — clicking the canvas does
    something different depending on which layer is selected and which tool it is in, and
    nothing on screen explains that. These buttons set layer + mode + label together, so a
    click always does what the button they last pressed says it does.

    ADD and DRAW are two ways of prompting the same model. ADD sends a click. DRAW sends the
    outline you trace, as a coarse-mask prompt — the only prompt type that can describe a
    concave nucleus, and the reason this does not simply reuse micro_sam's Shapes layer,
    which reduces everything drawn in it to a bounding box.

    The trace lands in `current_object` first, which makes both halves available from one
    button: C commits it exactly as drawn if S is never pressed, and if SAM's refinement
    wanders off into the neighbouring clump it is thrown away and the trace kept. Either way
    stage 3 trains on the LABEL IMAGE, so a hand trace is fully valid ground truth.
    """
    from qtpy import QtWidgets, QtCore

    ann_dir = manifest["dirs"]["annotations"]
    n_total = manifest["n_tiles"]

    panel = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(panel)
    lay.setSpacing(6)

    head = QtWidgets.QLabel()
    head.setStyleSheet("font-size:15px; font-weight:bold;")
    lay.addWidget(head)
    sub = QtWidgets.QLabel()
    sub.setWordWrap(True)
    lay.addWidget(sub)

    BTN_BASE = "font-size:14px; font-weight:bold;"
    btn_add = QtWidgets.QPushButton("➕  ADD objects")
    btn_draw = QtWidgets.QPushButton("✏  DRAW outline")
    btn_del = QtWidgets.QPushButton("✖  DELETE objects")
    for b in (btn_add, btn_draw, btn_del):
        b.setMinimumHeight(44)
        b.setStyleSheet(BTN_BASE)
        lay.addWidget(b)

    def highlight(active, colour):
        """Exactly one button is coloured, and it is the mode the canvas is actually in."""
        for b in (btn_add, btn_draw, btn_del):
            b.setStyleSheet(BTN_BASE + (f" background:{colour}; color:white;"
                                        if b is active else ""))

    hint = QtWidgets.QLabel()
    hint.setWordWrap(True)
    hint.setStyleSheet("padding:6px; font-size:12px;")
    lay.addWidget(hint)

    btn_next = QtWidgets.QPushButton("✓  TILE DONE → NEXT TILE")
    btn_next.setMinimumHeight(44)
    btn_next.setStyleSheet("font-size:14px; font-weight:bold; background:#1f5fa8; color:white;")
    lay.addWidget(btn_next)

    def press_next():
        """Fire micro_sam's own 'n' binding — the ONLY thing that saves the tile."""
        for kb, fn in viewer.keymap.items():
            text = kb.to_text() if hasattr(kb, "to_text") else str(kb)
            if text.lower() == "n":
                res = fn(viewer)
                if hasattr(res, "__next__"):     # press/release generator bindings
                    next(res, None)
                return
        hint.setText("<b>Could not find the Next action — press <big>N</big> on the keyboard.</b>")

    btn_next.clicked.connect(press_next)

    keys_label = QtWidgets.QLabel(
        "<hr><b>S</b> segment from your click<br>"
        "<b>T</b> switch click include ↔ exclude<br>"
        "<b>C</b> commit the object<br>"
        "<b>Shift+C</b> start this object over<br>"
        "<b>D</b> delete the object under the mouse<br>"
        "<b>Ctrl+Z</b> undo<br>"
        "<i>(in DRAW, S tidies the outline you traced and C commits it)</i><br><br>"
        "<b>N</b> — save this tile, go to the next<br>"
        "<span style='color:#d33;'><b>Press N on every tile,<br>including the last one.</b></span>"
        "<br><br><i>On a tile with nothing outlined, N asks \u201cNothing is segmented yet\u201d "
        "\u2014 click OK. Until you do, the window ignores everything else.</i>"
    )
    keys_label.setWordWrap(True)     # or the last sentence runs off the edge of the dock
    lay.addWidget(keys_label)
    lay.addStretch(1)

    def committed():
        return viewer.layers["committed_objects"] if "committed_objects" in viewer.layers else None

    def trace_layer():
        """Our own Shapes layer to trace on, created on first use.

        Deliberately NOT micro_sam's `prompts` layer. micro_sam owns that one: it attaches
        its own mouse callbacks to it, reads it for box prompts and clears it on commit, so
        a half-drawn polygon living there is being edited by two pieces of code at once. A
        layer nothing else touches cannot be cleared out from under the user mid-trace.
        """
        if "trace" in viewer.layers:
            return viewer.layers["trace"]
        return viewer.add_shapes(name="trace", edge_color="#7a4fa3",
                                 face_color="#ffffff00", edge_width=2)

    # micro_sam binds its prompt handling to the VIEWER's mouse callbacks, which fire on every
    # click whatever layer is active. napari's polygon tool keeps its in-progress vertices in
    # layer state that `_finish_drawing()` throws away as soon as something disturbs the active
    # layer or eats the press — so with both live, each click restarts the shape and no vertex
    # ever sticks. They cannot share the mouse: DRAW borrows it, and gives it back on exit.
    stashed = {"drag": None, "dbl": None}

    def grab_mouse():
        if stashed["drag"] is not None:
            return
        stashed["drag"] = list(viewer.mouse_drag_callbacks)
        stashed["dbl"] = list(viewer.mouse_double_click_callbacks)
        viewer.mouse_drag_callbacks.clear()
        viewer.mouse_double_click_callbacks.clear()
        names = ", ".join(getattr(f, "__name__", repr(f)) for f in stashed["drag"]) or "none"
        print(f"[annotate] DRAW: suspended {len(stashed['drag'])} viewer mouse callbacks "
              f"({names})", flush=True)

    def release_mouse():
        """Idempotent, and called by every other mode — ADD must never come back mute."""
        if stashed["drag"] is None:
            return
        viewer.mouse_drag_callbacks.extend(stashed["drag"])
        viewer.mouse_double_click_callbacks.extend(stashed["dbl"])
        stashed["drag"] = stashed["dbl"] = None

    # Which button is armed. S has to do something different in DRAW mode (refine the trace)
    # from ADD mode (micro_sam's own point-prompt segmentation), and once a shape has been
    # consumed there is nothing left on the layers themselves to tell the two apart.
    mode_state = {"draw": False}

    def set_add():
        pts = viewer.layers["point_prompts"]
        viewer.layers.selection.active = pts
        pts.mode = "add"
        # Clear the selection first: after a commit the points are deleted but napari keeps
        # their indices in `selected_data`, and writing current_properties then raises
        # KeyError deep in pandas (the same crash micro_sam's own T shortcut hits).
        try:
            pts.selected_data = set()
        except Exception:
            pass
        try:
            props = pts.current_properties      # force POSITIVE; T toggles it to negative
            props["label"] = np.array(["positive"])
            pts.current_properties = props
        except Exception:
            pass
        mode_state["draw"] = False
        release_mouse()
        highlight(btn_add, "#2d7d46")
        hint.setText(
            "Click the middle of an object → press <b>S</b> → press <b>C</b>.<br><br>"
            "<i>Pressed C and nothing happened?</i> That object is already outlined — "
            "micro_sam refuses to commit on top of an existing one. "
            "<b>DELETE the old outline first</b>, then add it again."
        )

    def set_draw():
        """Trace the object by hand; the trace becomes the pending object, S refines it."""
        if "current_object" not in viewer.layers:
            hint.setText("<b>This viewer has no current_object layer</b> — use ADD instead.")
            return
        shp = trace_layer()
        viewer.layers.selection.active = shp
        grab_mouse()
        active_mode = None
        for mode in ("add_polygon", "add_polygon_lasso"):
            try:
                shp.mode = mode
                active_mode = str(shp.mode)         # what it ACTUALLY took, not what we asked
                break
            except (ValueError, KeyError, AttributeError):
                continue
        mode_state["draw"] = active_mode is not None
        highlight(btn_draw, "#7a4fa3")
        print(f"[annotate] DRAW -> layer 'trace', mode {active_mode or 'NONE'}", flush=True)
        if active_mode and "lasso" in active_mode:
            # Lasso is drag-to-draw: clicking it produces a dot that vanishes on release,
            # which reads exactly like a broken button. Say which tool the user actually got.
            hint.setText("<b>Hold the mouse down and drag</b> right round the object "
                         "(this napari gave us the lasso tool, not click-by-click).<br><br>"
                         "Then <b>S</b> to let SAM tidy it, or <b>C</b> to keep it as drawn.")
        elif active_mode:
            hint.setText(
                "Click round the object, <b>double-click</b> to close.<br><br>"
                "Then <b>S</b> — SAM tidies your outline to the real edge — then <b>C</b>.<br><br>"
                "<i>Press C without S to keep the outline exactly as you drew it; press S "
                "again to refine further. Right-click removes the last point, <b>Esc</b> "
                "abandons the shape.</i>")
        else:
            hint.setText("<b>Could not switch to the polygon tool</b> — use ADD instead.")

    def set_delete():
        lyr = committed()
        if lyr is None:
            return
        viewer.layers.selection.active = lyr
        lyr.mode = "fill"
        lyr.preserve_labels = False             # else the fill refuses to write 0 over a label
        lyr.selected_label = 0                  # fill target 0 = erase the whole object
        lyr.n_edit_dimensions = 2
        mode_state["draw"] = False
        release_mouse()
        highlight(btn_del, "#a33")
        hint.setText("Click on a wrong object → it disappears.")

    btn_add.clicked.connect(set_add)
    btn_draw.clicked.connect(set_draw)
    btn_del.clicked.connect(set_delete)

    def take_polygon():
        """Move a finished trace out of `prompts` and into `current_object`.

        Left in the Shapes layer the trace is worth only its bounding box — that is all
        micro_sam ever does with a shape. Rasterised into current_object it is a real mask:
        C commits it as drawn, and S can hand it to SAM as a coarse-mask prompt.

        Called from the S and C handlers, and NOT from a timer. napari builds a polygon in
        `layer.data` as each vertex is clicked, so a shape exists from the first click and
        looks finished to anything watching the data. A timer that consumed it wiped the
        half-drawn outline on every click — the line appeared and vanished, and the polygon
        could never be closed.
        """
        from skimage.draw import polygon as _rasterise
        shp = trace_layer()
        cur = viewer.layers["current_object"]
        if getattr(shp, "_is_creating", False):     # vertices still being placed
            return False
        traces = [np.asarray(s) for s in shp.data]
        if not traces or cur.data.ndim != 2:
            return False
        buf = np.zeros(cur.data.shape, dtype=bool)
        for verts in traces:
            v = verts[:, -2:]                       # (row, col), trailing dims if 3D-ish
            rr, cc = _rasterise(v[:, 0], v[:, 1], shape=buf.shape)
            buf[rr, cc] = True
        shp.data = []                               # consumed, or it re-fires every tick
        if not buf.any():
            return False
        cur.data = buf.astype(cur.data.dtype)
        return True

    def refine():
        """S in DRAW mode: hand the pending trace to SAM as a coarse-mask prompt."""
        cur = viewer.layers["current_object"]
        mask = np.asarray(cur.data) > 0
        if not mask.any():
            return False                            # nothing traced — let micro_sam's S run
        out = None
        try:
            from micro_sam.sam_annotator._state import AnnotatorState
            out = _sam_mask_prompt(AnnotatorState().predictor, mask)
        except Exception as exc:                    # fail closed: the trace is never lost
            print(f"[annotate] SAM refine unavailable: {exc}", flush=True)
        if out is None:
            hint.setText("SAM had nothing better to offer, so <b>your outline is kept</b> — "
                         "press <b>C</b> to commit it.")
        else:
            cur.data = out.astype(cur.data.dtype)
            hint.setText("SAM tidied your outline. <b>S</b> again refines further, "
                         "<b>C</b> commits, <b>Shift+C</b> starts this object over.")
        return True

    # micro_sam owns "s" and "c". Keep both handlers and fall through to them whenever we are
    # not in DRAW mode with a finished trace, so ADD behaves exactly as it did before.
    def stock_key(key):
        for kb, fn in list(viewer.keymap.items()):
            text = kb.to_text() if hasattr(kb, "to_text") else str(kb)
            if text.lower() == key:
                return fn
        print(f"[annotate] WARNING: micro_sam's '{key}' binding is not on the viewer keymap; "
              f"ADD may not work as documented.", flush=True)
        return None

    _stock_s, _stock_c = stock_key("s"), stock_key("c")

    def fire(fn, v):
        if fn is None:
            return
        res = fn(v)
        if hasattr(res, "__next__"):                # press/release generator bindings
            next(res, None)

    @viewer.bind_key("s", overwrite=True)
    def _segment_or_refine(_v):
        if mode_state["draw"]:
            take_polygon()
            if refine():
                return
        fire(_stock_s, _v)

    @viewer.bind_key("c", overwrite=True)
    def _commit_trace_or_object(_v):
        # C on a trace the user never refined has to commit the trace itself. Nothing else
        # picks it up now that the timer does not, and micro_sam's own C would commit the
        # empty current_object and silently drop the outline.
        if mode_state["draw"]:
            take_polygon()
        fire(_stock_c, _v)

    # T (include <-> exclude) is broken in stock micro_sam 1.8.2 for the most common case:
    # committing with C deletes the point prompts but napari keeps their indices in
    # `selected_data`, so the next T raises
    #   KeyError: None of [RangeIndex(...)] are in the [index]
    # inside pandas. napari swallows it, so the user just sees T "not working" right after
    # every commit — i.e. exactly when they reach for it. Re-binding after micro_sam (last
    # binding wins) with the stale selection cleared first makes T behave as documented.
    from micro_sam.sam_annotator import util as _sam_util

    @viewer.bind_key("t", overwrite=True)
    def _toggle_prompt_label(_v):
        pts = viewer.layers["point_prompts"]
        try:
            pts.selected_data = set()
        except Exception:
            pass
        _sam_util.toggle_label(pts)
        lbl = pts.current_properties["label"][0]
        hint.setText(f"Next click = <b>{'INCLUDE' if lbl == 'positive' else 'EXCLUDE'}</b>"
                     f"{' (green)' if lbl == 'positive' else ' (red) — click the part that should NOT be in the object'}"
                     f"<br>then press <b>S</b> again. Press <b>T</b> to switch back.")

    @viewer.bind_key("d", overwrite=True)
    def _delete_under_cursor(_v):
        lyr = committed()
        if lyr is None:
            return
        try:
            idx = tuple(int(round(i)) for i in lyr.world_to_data(viewer.cursor.position))
            val = int(lyr.data[idx])
        except Exception:
            return
        if val:
            data = lyr.data
            data[data == val] = 0
            lyr.data = data                     # reassign so napari repaints

    # One timer drives everything that changes when the human presses N: the counter, and
    # resetting the mode. After N the selected layer is whatever it was, which for someone
    # who just deleted something is committed_objects in FILL mode — their next click would
    # silently erase instead of adding. Snapping back to ADD removes that trap.
    state = {"done": -1}

    def tick():
        try:
            done = len(glob.glob(os.path.join(ann_dir, "*.tif")))
            lyr = committed()
            n_obj = int(np.count_nonzero(np.unique(lyr.data))) if lyr is not None else 0
            head.setText(f"Tile {min(done + 1, n_total)} of {n_total}")
            sub.setText(f"<b>{n_obj}</b> objects outlined on this tile &nbsp;|&nbsp; "
                        f"{done} tile(s) saved")
            if done != state["done"]:
                state["done"] = done
                set_add()
        except Exception:
            pass

    # The run watchdog kills a script that prints nothing for 180 s, and an annotation
    # session is silent for as long as the person is working — a picker session was killed
    # at 52 minutes, losing everything. Say on stdout that the wait is intended.
    t0 = time.time()

    def heartbeat():
        n_done = len(glob.glob(os.path.join(manifest["dirs"]["annotations"], "*.tif")))
        print(f"[annotate] waiting for the user — {n_done} of {len(manifest['tiles'])} tiles "
              f"saved, window open {(time.time() - t0) / 60:.0f} min. This script is MEANT to "
              f"sit here until they close the annotator.", flush=True)

    beat = QtCore.QTimer(panel)
    beat.timeout.connect(heartbeat)
    beat.start(45_000)
    panel._imagentj_beat = beat                 # keep a reference or Qt garbage-collects it

    timer = QtCore.QTimer(panel)
    timer.timeout.connect(tick)
    timer.start(700)
    panel._imagentj_timer = timer               # keep a reference or Qt garbage-collects it

    panel.setMaximumWidth(340)
    dock = viewer.window.add_dock_widget(panel, name="ImagentJ — Annotation Helper", area="right")

    # micro_sam already docks two panels on the right (the annotator, and "Next Image [N]").
    # Stacked, the three of them eat most of the window and leave a sliver of canvas — which
    # is the thing the human actually has to look at. Tabbing them gives the canvas the width
    # back; raising ours means the helper is what they see first. The annotator panel stays
    # one click away for the "Automatic Segmentation" button.
    try:
        mw = viewer.window._qt_window
        others = [d for d in viewer.window._dock_widgets.values() if d is not dock]
        for d in others:                                  # give them real names, not "Dock widget 1"
            has_next = any(isinstance(w, QtWidgets.QPushButton) and "Next Image" in w.text()
                           for w in d.findChildren(QtWidgets.QPushButton))
            d.setWindowTitle("Next Image" if has_next else "micro_sam (advanced)")
        if others:
            base = others[0]
            for d in others[1:] + [dock]:                 # chain into ONE tab group
                mw.tabifyDockWidget(base, d)
        # raise() before the layout settles is ignored, so defer it by one event-loop turn
        QtCore.QTimer.singleShot(0, dock.raise_)
    except Exception:
        pass

    set_add()
    tick()
    return panel


def annotated_preview(entry, labels, out_dir):
    """Overlay of what the human actually produced, so the agent can LOOK at it afterwards.

    While the annotator is open the agent is blocked inside execute_script and can see nothing;
    these PNGs are how it inspects (or vlm_judge inspects) the finished work before spending
    GPU time on it.
    """
    from skimage.segmentation import find_boundaries
    import imageio.v3 as imageio
    img = tifffile.imread(entry["tile_path"])
    gray = img.mean(-1) if img.ndim == 3 else img
    rgb = np.repeat(gray.astype(np.uint8)[..., None], 3, -1)
    if labels.max() > 0:
        rgb[find_boundaries(labels, mode="outer")] = (60, 255, 60)
    path = os.path.join(out_dir, entry["name"] + "_annotated.png")
    imageio.imwrite(path, rgb)
    return path


def report(manifest):
    """Per-tile status after the window closes — the gate for stage 3."""
    prev_dir = os.path.join(manifest["task_dir"], "annotated_previews")
    os.makedirs(prev_dir, exist_ok=True)
    rows, ok = [], 0
    for e in manifest["tiles"]:
        p = e["annotation_path"]
        if not os.path.exists(p):
            rows.append((e["name"], "NOT ANNOTATED", 0, ""))
            continue
        lab = tifffile.imread(p)
        try:
            annotated_preview(e, lab, prev_dir)
        except Exception:
            pass
        ids = np.unique(lab)
        n = int(len(ids) - (1 if 0 in ids else 0))
        exp = (e["height"], e["width"])
        if lab.shape[:2] != exp:
            rows.append((e["name"], f"SHAPE MISMATCH {lab.shape[:2]} != {exp}", n, ""))
        elif n == 0:
            rows.append((e["name"], "EMPTY (skipped)", 0, ""))
        elif n < 2:
            rows.append((e["name"], "TOO FEW (<2 objects)", n, ""))
        else:
            ok += 1
            rows.append((e["name"], "ok", n, f"was {e['n_preseg_objects']}"))

    print("\n" + "=" * 72)
    print(f"{'tile':<14}{'status':<26}{'objects':>9}  {'first guess':<14}")
    print("-" * 72)
    for name, status, n, note in rows:
        print(f"{name:<14}{status:<26}{n:>9}  {note:<14}")
    print("-" * 72)
    total = sum(r[2] for r in rows if r[1] == "ok")
    print(f"{ok} of {len(rows)} tiles usable, {total} annotated objects in total.")
    print(f"overlays of what was annotated: {os.path.join(manifest['task_dir'], 'annotated_previews')}")
    if ok < 3:
        print("NOT ENOUGH YET: stage 3 needs at least 3 usable tiles (train + validation).\n"
              "Re-run this script — it resumes at the first unfinished tile.")
    else:
        print(f"READY for stage 3. Run WORKFLOW_FINETUNE_3_TRAIN.py with "
              f"TASK_DIR = {manifest['task_dir']}")
    print("=" * 72)
    return ok


def main():
    ensure_model_cache(os.path.join(TASK_DIR, ".micro_sam_cache"))
    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    tiles = [e["tile_path"] for e in manifest["tiles"]]
    presegs = [e["preseg_path"] for e in manifest["tiles"]]
    ann_dir = manifest["dirs"]["annotations"]
    os.makedirs(ann_dir, exist_ok=True)

    already = len(glob.glob(os.path.join(ann_dir, "*.tif")))
    if already >= len(tiles):
        print(f"All {len(tiles)} tiles are already annotated. Nothing to do.")
        report(manifest)
        return

    print(BANNER.format(n=len(tiles) - already,
                        instr=os.path.join(TASK_DIR, "ANNOTATION_INSTRUCTIONS.md")))
    if already:
        print(f"Resuming: {already} tile(s) already done, starting at tile {already + 1}.\n")

    import napari
    from micro_sam.sam_annotator import image_series_annotator

    print("Computing image embeddings (one-off, makes every click instant) ...")
    viewer = image_series_annotator(
        images=tiles,
        output_folder=ann_dir,
        model_type=manifest["model_type"],
        # Cached so the annotator LOADS embeddings instead of recomputing them per tile.
        embedding_path=manifest["dirs"]["embeddings"],
        initial_segmentations=presegs,       # the stock guess lands in committed_objects
        precompute_amg_state=PRECOMPUTE_AMG_STATE,
        skip_segmented=True,                 # resume at the first unfinished tile
        # We need the viewer BEFORE the event loop starts so the helper can be docked;
        # with return_viewer=False this call ends in its own napari.run() and never
        # gives us a chance to add anything.
        return_viewer=True,
    )
    if viewer is None:                       # everything was already segmented
        report(manifest)
        return

    if SHOW_HELPER:
        try:
            build_helper(viewer, manifest)
        except Exception as exc:             # the annotator must stay usable regardless
            print(f"[annotate] helper panel unavailable ({exc}); use the keyboard workflow "
                  f"in ANNOTATION_INSTRUCTIONS.md instead.")

    napari.run()                             # blocks until the human closes the window
    report(manifest)


if __name__ == "__main__":
    main()

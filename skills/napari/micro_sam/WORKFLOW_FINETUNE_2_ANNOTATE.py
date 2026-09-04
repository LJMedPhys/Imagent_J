# imagentj-env: napari-mcp
"""
micro_sam fine-tuning — STAGE 2 of 4: the human corrects the tiles.

Opens micro_sam's image-series annotator on the tiles built by stage 1, with the stock model's
guess already loaded into `committed_objects`, plus a small **Annotation Helper** panel that
reduces the whole job to three buttons: ADD an object (SAM does the outlining), DRAW an
outline by hand, DELETE an object.

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
  DRAW one by hand  ->  click "DRAW outline", click round the object, double-click to close
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

def build_helper(viewer, manifest):
    """Dock a three-button panel: ADD (point prompts) / DRAW (polygon) / DELETE (fill with 0).

    Everything a beginner gets wrong here is a MODE problem — clicking the canvas does
    something different depending on which layer is selected and which tool it is in, and
    nothing on screen explains that. These buttons set layer + mode + label together, so a
    click always does what the button they last pressed says it does.

    ADD goes through SAM: the click is a prompt, SAM returns the outline. DRAW does not —
    it writes the polygon straight into `committed_objects`. That matters because SAM's
    prompt encoder only accepts points, boxes and a coarse mask, so there is no way to hand
    it an outline; but the file stage 3 trains on is the LABEL IMAGE, not SAM's opinion of
    it. Anything that ends up in `committed_objects` is ground truth, however it got there.
    So DRAW is the escape hatch for the cases the docs otherwise tell the user to give up
    on — touching objects that SAM insists on merging, and outlines it keeps getting wrong.
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
        "<i>(S, T and C belong to ADD only — DRAW needs none of them)</i><br><br>"
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
        highlight(btn_add, "#2d7d46")
        hint.setText(
            "Click the middle of an object → press <b>S</b> → press <b>C</b>.<br><br>"
            "<i>Pressed C and nothing happened?</i> That object is already outlined — "
            "micro_sam refuses to commit on top of an existing one. "
            "<b>DELETE the old outline first</b>, then add it again."
        )

    def set_draw():
        """Draw one outline by hand, straight into committed_objects — no SAM in the loop."""
        lyr = committed()
        if lyr is None:
            return
        viewer.layers.selection.active = lyr
        lyr.n_edit_dimensions = 2
        # A fresh id per object, or two polygons drawn one after the other come out as a
        # single object. preserve_labels keeps the neighbours safe: the fill then writes
        # over background only, so a vertex that strays across a committed object cannot
        # eat it — which matters precisely in the touching-objects case this is here for.
        lyr.preserve_labels = True
        lyr.selected_label = int(lyr.data.max()) + 1
        # napari's polygon tool for Labels arrived in 0.4.19. Fall back to the brush on
        # anything older rather than leaving the button dead and the mode unchanged.
        active_mode = None
        for mode in ("polygon", "paint"):
            try:
                lyr.mode = mode
                active_mode = mode
                break
            except (ValueError, KeyError, AttributeError):
                continue
        highlight(btn_draw, "#7a4fa3")
        if active_mode == "polygon":
            hint.setText(
                "Click once at each corner around the object, then <b>double-click</b> to "
                "close it — the shape fills in as a new object.<br><br>"
                "Right-click removes the last point; <b>Esc</b> abandons the shape.<br><br>"
                "<i>Nothing here goes through SAM, so there is no S and no C — the outline "
                "you draw IS the answer. Use it for objects that are touching, and for any "
                "outline the ADD button keeps getting wrong.</i>")
        elif active_mode == "paint":
            lyr.brush_size = 6
            hint.setText("<b>This napari has no polygon tool</b> — using the brush instead. "
                         "Drag over the object to fill it in; <b>[</b> and <b>]</b> resize "
                         "the brush.")
        else:
            hint.setText("<b>Could not switch to a drawing tool</b> — use ADD instead.")

    def set_delete():
        lyr = committed()
        if lyr is None:
            return
        viewer.layers.selection.active = lyr
        lyr.mode = "fill"
        lyr.preserve_labels = False             # else the fill refuses to write 0 over a label
        lyr.selected_label = 0                  # fill target 0 = erase the whole object
        lyr.n_edit_dimensions = 2
        highlight(btn_del, "#a33")
        hint.setText("Click on a wrong object → it disappears.")

    btn_add.clicked.connect(set_add)
    btn_draw.clicked.connect(set_draw)
    btn_del.clicked.connect(set_delete)

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
            # Once a hand-drawn polygon has landed, the id it used is spent. Move to the
            # next one so the following polygon is a separate object; napari itself keeps
            # selected_label as-is, which would silently merge every shape into one.
            if lyr is not None and str(lyr.mode) == "polygon":
                cur = int(lyr.selected_label)
                if cur and int(lyr.data.max()) >= cur:
                    lyr.selected_label = cur + 1
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

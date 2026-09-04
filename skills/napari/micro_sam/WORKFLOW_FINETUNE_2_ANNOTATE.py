# imagentj-env: napari-mcp
"""
micro_sam fine-tuning — STAGE 2 of 4: the human corrects the tiles.

Opens micro_sam's image-series annotator on the tiles built by stage 1, with the stock model's
guess already loaded into `committed_objects`, plus a small **Annotation Helper** panel that
reduces the whole job to two buttons: ADD an object, DELETE an object.

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
  DELETE an object  ->  click "DELETE objects", click the object
  BAD OUTLINE       ->  delete it, then add it again
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

def series_nav(viewer):
    """Reach micro_sam's series-navigation state so we can move BACKWARDS through the tiles.

    `image_series_annotator` keeps the current tile index in a closure variable
    (`next_image_id`) of its own `next_image()` callback, and the only move it offers is
    "save, then advance". With `skip_segmented=True` that advance SKIPS every tile that is
    already annotated — which is exactly where Back needs to go — so Back cannot be built on
    top of it. We drive the same objects instead: micro_sam's own predictor, annotator and
    embedding paths, all of which are in that closure.

    Returns {name: cell} for `next_image()`'s free variables, or None if micro_sam's
    internals have moved. Callers must treat None as "hide the Back button" and carry on:
    losing Back must never cost the user their annotation session.
    """
    for kb, bound in getattr(viewer, "keymap", {}).items():
        text = kb.to_text() if hasattr(kb, "to_text") else str(kb)
        if text.lower() != "n":
            continue
        for cell in (getattr(bound, "__closure__", None) or ()):
            try:
                cand = cell.cell_contents
            except ValueError:               # empty cell
                continue
            inner = getattr(cand, "_function", cand)   # magicgui FunctionGui -> the function
            code = getattr(inner, "__code__", None)
            if code is not None and "next_image_id" in code.co_freevars:
                return dict(zip(code.co_freevars, inner.__closure__))
    return None


def goto_tile(viewer, nav, target):
    """Move to tile `target`, saving the current tile's work first. True if it moved.

    Replicates what micro_sam's `next_image()` does after it increments — new image into the
    image layer, embeddings re-initialised, `_update_image` with the segmentation to show —
    but for an ARBITRARY index, and it loads the tile's already-saved annotation rather than
    the stock pre-segmentation, so going back shows the user their own corrections.
    """
    import imageio.v3 as imageio

    cur = nav["next_image_id"].cell_contents
    images = nav["images"].cell_contents
    if not (0 <= target < len(images)) or target == cur:
        return False
    save_path = nav["_get_save_path"].cell_contents

    # 1. Never lose the tile being left. micro_sam only writes on N; Back must write too.
    seg = np.asarray(viewer.layers["committed_objects"].data)
    if seg.max() > 0:
        imageio.imwrite(save_path(images[cur], cur), seg, compression="zlib")

    # 2. Move the counter that micro_sam's own N reads, or N would save the wrong file.
    nav["next_image_id"].cell_contents = target

    # 3. What to show: the user's saved work for that tile, else the stock pre-segmentation.
    dst = save_path(images[target], target)
    if os.path.exists(dst):
        result = imageio.imread(dst)
    else:
        init = nav["initial_segmentations"].cell_contents
        result = None if init is None else (
            init[target] if isinstance(init[target], np.ndarray) else imageio.imread(init[target]))

    image = imageio.imread(images[target])
    viewer.layers["image"].data = image
    state = nav["state"].cell_contents
    if getattr(state, "amg", None) is not None:
        state.amg.clear_state()
    state.initialize_predictor(
        image, model_type=nav["model_type"].cell_contents, ndim=2,
        save_path=nav["embedding_paths"].cell_contents[target],
        tile_shape=nav["tile_shape"].cell_contents, halo=nav["halo"].cell_contents,
        predictor=nav["predictor"].cell_contents, decoder=nav["decoder"].cell_contents,
        precompute_amg_state=nav["precompute_amg_state"].cell_contents,
        device=nav["device"].cell_contents, skip_load=False,
    )
    state.image_shape = image.shape[:2] if (image.ndim == 3 and image.shape[-1] in (3, 4)) \
        else image.shape
    nav["annotator"].cell_contents._update_image(segmentation_result=result)
    return True


def build_helper(viewer, manifest):
    """Dock a two-button panel: ADD (point prompts) / DELETE (fill with 0).

    Everything a beginner gets wrong here is a MODE problem — clicking the canvas does
    something different depending on which layer is selected and which tool it is in, and
    nothing on screen explains that. These buttons set layer + mode + label together, so a
    click always does what the button they last pressed says it does.
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

    btn_add = QtWidgets.QPushButton("➕  ADD objects")
    btn_del = QtWidgets.QPushButton("✖  DELETE objects")
    for b in (btn_add, btn_del):
        b.setMinimumHeight(44)
        b.setStyleSheet("font-size:14px; font-weight:bold;")
        lay.addWidget(b)

    btn_undo = QtWidgets.QPushButton("↩  UNDO the outline I am building")
    btn_undo.setMinimumHeight(34)
    btn_undo.setStyleSheet("font-size:13px;")
    btn_undo.setToolTip("Throw away the outline S just produced, and the clicks that made it.")
    lay.addWidget(btn_undo)

    hint = QtWidgets.QLabel()
    hint.setWordWrap(True)
    hint.setStyleSheet("padding:6px; font-size:12px;")
    lay.addWidget(hint)

    nav = series_nav(viewer)          # None = micro_sam moved; Back is then simply absent

    btn_prev = QtWidgets.QPushButton("◀  BACK to previous tile")
    btn_prev.setMinimumHeight(34)
    btn_prev.setStyleSheet("font-size:13px;")
    btn_prev.setToolTip("Save this tile, then reopen the previous one with your corrections on it.")
    btn_prev.setVisible(nav is not None)
    lay.addWidget(btn_prev)

    btn_next = QtWidgets.QPushButton("✓  TILE DONE → NEXT TILE")
    btn_next.setMinimumHeight(44)
    btn_next.setStyleSheet("font-size:14px; font-weight:bold; background:#1f5fa8; color:white;")
    lay.addWidget(btn_next)

    def press_prev():
        """Go one tile back. Saves the current tile first, so nothing is ever lost.

        After correcting an old tile, N behaves as it always does: it saves and jumps to the
        first tile that still has no annotation — i.e. straight back to where the user was.
        """
        if nav is None:
            return
        cur = nav["next_image_id"].cell_contents
        if cur <= 0:
            hint.setText("<b>This is the first tile — there is nothing before it.</b>")
            return
        try:
            if goto_tile(viewer, nav, cur - 1):
                set_add()
                hint.setText(
                    f"Back on tile <b>{cur}</b> of {n_total}, with your saved corrections on it.<br>"
                    f"<i>Press N when done — it jumps forward to the first tile you have not "
                    f"annotated yet.</i>")
        except Exception as exc:
            hint.setText(f"<b>Could not go back:</b> {exc}")

    btn_prev.clicked.connect(press_prev)

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
        "<b>D</b> delete the object under the mouse<br>"
        "<b>U</b> or <b>Ctrl+Z</b> undo the outline you are building<br><br>"
        "<b>B</b> — back to the previous tile<br>"
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
        if "point_prompts" not in viewer.layers:   # same failure as Shift+C, same explanation
            prompt_layer_lost()
            return
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
        btn_add.setStyleSheet("font-size:14px; font-weight:bold; background:#2d7d46; color:white;")
        btn_del.setStyleSheet("font-size:14px; font-weight:bold;")
        hint.setText(
            "Click the middle of an object → press <b>S</b> → press <b>C</b>.<br><br>"
            "<i>Pressed C and nothing happened?</i> That object is already outlined — "
            "micro_sam refuses to commit on top of an existing one. "
            "<b>DELETE the old outline first</b>, then add it again."
        )

    def set_delete():
        lyr = committed()
        if lyr is None:
            return
        viewer.layers.selection.active = lyr
        lyr.mode = "fill"
        lyr.preserve_labels = False             # else the fill refuses to write 0 over a label
        lyr.selected_label = 0                  # fill target 0 = erase the whole object
        lyr.n_edit_dimensions = 2
        btn_del.setStyleSheet("font-size:14px; font-weight:bold; background:#a33; color:white;")
        btn_add.setStyleSheet("font-size:14px; font-weight:bold;")
        hint.setText("Click on a wrong object → it disappears.")

    btn_add.clicked.connect(set_add)
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

    def undo_last():
        """Throw away the in-progress outline, or put back the object just deleted.

        Ctrl+Z cannot do this. `S` writes its result into the `current_object` layer
        PROGRAMMATICALLY, and napari's undo history only records interactive edits, so there is
        nothing for it to revert — measured on micro_sam 1.8.2: after S the layer still holds
        every pixel it wrote, and Ctrl+Z is not even in the viewer keymap (napari handles it as
        an app-level Qt shortcut on the selected layer). So the honest fix is to implement the
        undo the user actually wants rather than to keep advertising a key that does nothing.
        """
        cur = viewer.layers["current_object"] if "current_object" in viewer.layers else None
        if cur is not None and int(np.count_nonzero(np.asarray(cur.data))):
            cur.data = np.zeros_like(np.asarray(cur.data))
            cur.refresh()
            if "point_prompts" in viewer.layers:
                pts = viewer.layers["point_prompts"]
                try:
                    pts.selected_data = set(range(len(pts.data)))
                    pts.remove_selected()
                except Exception:
                    pts.data = []
                pts.refresh()
            hint.setText("Dropped the outline you were building. Click the object again and "
                         "press <b>S</b>.")
            return
        # Nothing in progress: the last thing that changed was a DELETE on committed_objects.
        lyr = committed()
        try:
            if lyr is not None and hasattr(lyr, "undo"):
                lyr.undo()
                hint.setText("Put back the object you deleted.")
                return
        except Exception:
            pass
        hint.setText("Nothing to undo. (This undoes the outline you are building, or the last "
                     "object you deleted — not a whole tile.)")

    btn_undo.clicked.connect(undo_last)

    def prompts_alive():
        return "point_prompts" in viewer.layers

    def prompt_layer_lost():
        """Say what happened and how to recover, once, in language that fits the panel.

        Everything the annotator does with clicks goes through the `point_prompts` layer — S,
        C and the ADD button alike — so once it is gone the session cannot be repaired from
        here: micro_sam binds its segmentation callback to that layer OBJECT, and a replacement
        layer would restore the buttons while leaving S silently dead, which is worse than
        saying so. Recovery is cheap and lossless for finished tiles: close the window and
        re-run stage 2, which resumes at the first tile with no annotation saved.
        """
        hint.setText(
            "<b style='color:#d33;'>The prompt layer is gone.</b><br>"
            "Clicking, <b>S</b> and <b>C</b> cannot work without it. Nothing you already "
            "saved is lost — <b>close this window and run stage 2 again</b>; it picks up at "
            "the first tile you have not finished.<br><br>"
            "<i>(It disappears if 'point_prompts' gets deleted in the layer list on the left.)</i>")

    # micro_sam binds Shift+C to its Clear Annotations widget, which does
    #     viewer.layers["point_prompts"].data = []
    # with no guard. If that layer has been deleted, the binding raises
    #     KeyError: "'point_prompts' is not in list"
    # out of a Qt callback — reproduced in this container on micro_sam 1.8.2. Re-binding AFTER
    # micro_sam (last binding wins) keeps an accidental Shift+C from taking the session down.
    # It is deliberately NOT advertised in the key list: "start this object over" is served by
    # deleting the one bad outline and adding it again, which works in every state.
    @viewer.bind_key("Shift-C", overwrite=True)
    def _safe_clear(_v):
        if not prompts_alive():
            prompt_layer_lost()
            return
        try:
            from micro_sam.sam_annotator import util as _u
            _u.clear_annotations(viewer)
        except Exception as exc:
            hint.setText(f"<b>Clear did not work ({type(exc).__name__}).</b> Delete the one "
                         f"bad outline with <b>DELETE objects</b> (or <b>D</b>) and add it "
                         f"again — that works in every state.")

    # `U` is the one that is guaranteed to arrive: napari routes Ctrl+Z through its own Qt
    # action on the selected layer, so a viewer keybinding for it may never fire. Both are
    # bound so whichever the user reaches for does the same, working thing.
    @viewer.bind_key("u", overwrite=True)
    def _undo_u(_v):
        undo_last()

    @viewer.bind_key("Control-Z", overwrite=True)
    def _undo_ctrl_z(_v):
        undo_last()

    @viewer.bind_key("b", overwrite=True)
    def _back_one_tile(_v):
        press_prev()

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
            # The saved-file COUNT is not the position once Back exists — after stepping back
            # the count is unchanged while the tile on screen is an earlier one. Ask
            # micro_sam where it actually is; fall back to the count only if Back is absent.
            pos = (nav["next_image_id"].cell_contents + 1) if nav is not None \
                else min(done + 1, n_total)
            head.setText(f"Tile {pos} of {n_total}")
            btn_prev.setEnabled(nav is not None and nav["next_image_id"].cell_contents > 0)
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

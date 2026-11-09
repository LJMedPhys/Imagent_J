# imagentj-env: napari-mcp
"""
Cellpose fine-tuning — STAGE 2 of 4: the human corrects the tiles.

Opens a napari window on the tiles built by stage 1, with the stock model's guess already
loaded into `committed_objects`, plus a small **Annotation Helper** panel that reduces the
whole job to two modes: DRAW an object (trace its outline), DELETE an object.

Every object is drawn by hand: what the user traces IS the outline that gets saved — there is
no model in the loop here (the earlier micro_sam / Segment-Anything assisted annotator is gone
from this image). S turns the traced shapes into outlines (`current_object`), C keeps them
(`committed_objects`). The default gesture is napari's freehand lasso: press, drag round the
object, release. Pressing DRAW again switches to click-by-click polygon.

Every C also appends what was committed — the traced shapes' vertices and the label ids they
produced — to `<TASK_DIR>/prompt_log/<tile>.json`. The saved label tif is the annotation; the
log is the record of how each object got there.

RUN THIS VIA python_data_analyst, NEVER via mcp__napari_mcp__execute_code. It opens its own
napari window and blocks on napari.run() until the human closes it — which is correct here
(the script's return IS the "human is finished" signal) but would kill an MCP call: that tool
runs on napari's Qt thread under a 90 s timeout, so the viewer, the VNC desktop and the agent
turn would all hang. python_data_analyst gives it a 7200 s supervised subprocess instead.

Work is saved tile by tile, when the human presses N. Re-running resumes at the first
unfinished tile, so an interrupted session loses at most one tile.

When the window closes the script prints a per-tile status table. That table is what the agent
relays to the user and what decides whether stage 3 can start.

THIS PANEL IS A FIXED UI — EDIT `TASK_DIR` AND NOTHING ELSE. The user learns these buttons and
keys once, so a run where a button is renamed, restyled, added, removed or "improved" reads to
them as the tool breaking — a UI that changes between runs is a bug even when the code is
correct. If this panel cannot do what a task needs, say so and stop rather than improvising a
replacement.

Next: WORKFLOW_FINETUNE_CP_3_TRAIN.py

Run in the `napari-mcp` env. Edit TASK_DIR, execute.
"""
import os
import json
import time

import numpy as np
import tifffile

# ---- CONFIG -----------------------------------------------------------------
TASK_DIR = "/app/data/projects/demo/cellpose_finetune"   # the folder stage 1 wrote
# -----------------------------------------------------------------------------

BANNER = r"""
================================================================================
  ANNOTATE {n} TILES        (full instructions: {instr})
================================================================================
  Fix the outlines so that INSIDE EACH SQUARE every object is outlined and
  nothing else is. Outlines only need to be roughly right.

  DRAW an object    ->  click "DRAW objects", press + drag round the object,
                        release; draw as many as you like, then  S  and  C
                        (press DRAW again to click a polygon point by point)
  DELETE an object  ->  click "DELETE objects", click the object  (or hover + D)
  CLEAR drawings    ->  click "CLEAR my drawings" (outlines are not touched)
  BAD OUTLINE       ->  delete it, then draw it again
  TILE FINISHED     ->  press  N        <-- N is what SAVES the tile

  *** Press N on EVERY tile, INCLUDING THE LAST ONE. ***
  Closing the window without pressing N loses that tile (all earlier tiles are
  already saved, and restarting resumes at the first unfinished one).
================================================================================
"""

# Layer names. `committed_objects` / `current_object` keep the names users and docs already
# know; `drawings` is where the hand-traced shapes go.
L_IMAGE, L_COMMITTED, L_CURRENT, L_DRAW = "image", "committed_objects", "current_object", "drawings"

# The two drawing gestures, in the order DRAW cycles through them. The lasso is the default:
# one press-drag-release, so nothing can interrupt it half-way; the polygon is for objects
# with straight edges or for users who prefer clicking.
GESTURES = ("add_polygon_lasso", "add_polygon")


def shapes_to_labels(shapes_layer, shape):
    """Rasterise every closed shape (polygon, lasso, ellipse, rectangle) into one label image.

    One label per shape, 1..n in drawing order; where two shapes overlap the earlier one keeps
    the pixels, so a commit never produces an object hidden under another. Lines and paths
    enclose nothing and are skipped. Returns (labels, n_objects).
    """
    labels = np.zeros(shape, dtype=np.uint32)
    if len(shapes_layer.data) == 0:
        return labels, 0
    masks = np.asarray(shapes_layer.to_masks(mask_shape=shape), dtype=bool)
    n = 0
    for kind, m in zip(shapes_layer.shape_type, masks):
        if kind in ("line", "path") or not m.any():
            continue
        n += 1
        labels[m & (labels == 0)] = n
    return labels, n


def shapes_snapshot(shapes_layer):
    """The traced shapes as plain JSON (coordinates are y, x)."""
    return [{"type": str(kind), "vertices_yx": np.round(np.asarray(v)[:, -2:], 2).tolist()}
            for kind, v in zip(shapes_layer.shape_type, shapes_layer.data)]


def append_prompt_log(log_dir, tile_name, entry):
    """Add one commit to <log_dir>/<tile>.json. Written at once, so a crash loses nothing."""
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, tile_name + ".json")
    log = {"tile": tile_name, "commits": []}
    if os.path.exists(path):
        try:
            with open(path) as f:
                log = json.load(f)
        except (OSError, ValueError):
            pass
    log["commits"].append(entry)
    with open(path, "w") as f:
        json.dump(log, f, indent=1)
    return path


def read_labels(path, shape):
    """A label tif as uint32, or zeros if there is none / it has the wrong shape."""
    if path and os.path.exists(path):
        lab = np.asarray(tifffile.imread(path))
        if lab.shape[:2] == tuple(shape):
            return lab.astype(np.uint32)
        print(f"[annotate] ignoring {os.path.basename(path)}: shape {lab.shape} != {shape}",
              flush=True)
    return np.zeros(shape, dtype=np.uint32)


class Annotator:
    """Tile navigation, drawing, commit, delete and save — everything except the Qt panel.

    Kept separate from the panel so every action is one method the panel, the keyboard and a
    test can all call the same way.
    """

    def __init__(self, viewer, manifest):
        self.viewer = viewer
        self.m = manifest
        self.tiles = manifest["tiles"]
        self.log_dir = os.path.join(manifest["task_dir"], "prompt_log")
        self.idx = None
        self.empty_confirmed = False     # N on an empty tile needs a second press
        self.on_message = lambda html: None
        self.on_finished = lambda: None

    # -- layers ---------------------------------------------------------------------
    def layer(self, name):
        return self.viewer.layers[name] if name in self.viewer.layers else None

    def tile_shape(self, idx):
        e = self.tiles[idx]
        return (int(e["height"]), int(e["width"]))

    def first_unfinished(self, start=0):
        """Index of the first tile without a saved annotation, searching from `start` and
        wrapping round; None when every tile is saved."""
        n = len(self.tiles)
        for k in range(n):
            i = (start + k) % n
            if not os.path.exists(self.tiles[i]["annotation_path"]):
                return i
        return None

    def n_saved(self):
        return sum(os.path.exists(e["annotation_path"]) for e in self.tiles)

    def load(self, idx):
        """Show tile `idx`: the user's saved work if there is any, else the stock first guess."""
        e = self.tiles[idx]
        shape = self.tile_shape(idx)
        img = np.asarray(tifffile.imread(e["tile_path"]))
        rgb = img.ndim == 3 and img.shape[-1] in (3, 4)
        saved = e["annotation_path"] if os.path.exists(e["annotation_path"]) else None
        committed = read_labels(saved or e.get("preseg_path"), shape)

        v = self.viewer
        if self.layer(L_IMAGE) is None:
            v.add_image(img, name=L_IMAGE, rgb=rgb)
            v.add_labels(committed, name=L_COMMITTED)
            v.add_labels(np.zeros(shape, np.uint32), name=L_CURRENT, opacity=0.8)
            v.add_shapes(name=L_DRAW, edge_color="yellow", face_color="transparent",
                         edge_width=2)
        else:
            v.layers[L_IMAGE].data = img
            v.layers[L_COMMITTED].data = committed
            v.layers[L_CURRENT].data = np.zeros(shape, np.uint32)
            self.clear_drawings(quiet=True)
        self.idx = idx
        self.empty_confirmed = False
        self._as_loaded = committed.copy()      # to tell an untouched tile from an edited one
        v.reset_view()
        print(f"[annotate] tile {idx + 1}/{len(self.tiles)} {e['name']} "
              f"({'your saved work' if saved else 'first guess'}, "
              f"{self.n_objects()} objects)", flush=True)

    def changed(self):
        """True once the outlines on this tile differ from what was loaded."""
        lyr = self.layer(L_COMMITTED)
        return lyr is not None and not np.array_equal(np.asarray(lyr.data), self._as_loaded)

    def n_objects(self):
        lyr = self.layer(L_COMMITTED)
        return 0 if lyr is None else int(np.count_nonzero(np.unique(lyr.data)))

    # -- drawing --------------------------------------------------------------------
    def segment(self):
        """S: the traced shapes become outlines in `current_object` (not yet kept)."""
        cur, drw = self.layer(L_CURRENT), self.layer(L_DRAW)
        labels, n = shapes_to_labels(drw, cur.data.shape)
        cur.data = labels
        cur.refresh()
        self.on_message(f"<b>{n}</b> drawn outline(s) ready — press <b>C</b> to keep them."
                        if n else "Nothing to use — trace a closed shape first "
                                  "(lines are ignored).")
        return n

    def commit(self):
        """C: add the outlines to `committed_objects`, each as a NEW object.

        A new outline only takes pixels that are still background, so it can never eat into
        an object that is already there — to redraw an object, DELETE the old outline first.
        If S was not pressed, C does it first: the shapes on screen are what gets committed.
        """
        com, cur, drw = self.layer(L_COMMITTED), self.layer(L_CURRENT), self.layer(L_DRAW)
        if not np.any(cur.data) and len(drw.data):
            self.segment()
        new = np.asarray(cur.data)
        if not np.any(new):
            self.on_message("Nothing to keep — draw round an object, then <b>S</b> and "
                            "<b>C</b>.")
            return []
        data = np.asarray(com.data).astype(np.uint32, copy=True)
        nxt = int(data.max()) + 1
        new_ids, hidden = [], 0
        for i in [int(x) for x in np.unique(new) if x]:
            m = (new == i) & (data == 0)
            if not m.any():
                hidden += 1
                continue
            data[m] = nxt
            new_ids.append(nxt)
            nxt += 1
        com.data = data
        try:
            append_prompt_log(self.log_dir, self.tiles[self.idx]["name"], {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "drawn",
                "label_ids": new_ids, "shapes": shapes_snapshot(drw)})
        except Exception as exc:                  # never let logging break a commit
            print(f"[annotate] prompt log not written ({exc})", flush=True)
        cur.data = np.zeros_like(cur.data)
        self.clear_drawings(quiet=True)
        self.empty_confirmed = False
        msg = f"Kept <b>{len(new_ids)}</b> new object(s)."
        if hidden:
            msg += (f"<br><i>{hidden} outline(s) lay entirely on top of existing objects and "
                    f"were not added — DELETE the old outline first, then draw it again.</i>")
        self.on_message(msg)
        print(f"[annotate] C: +{len(new_ids)} object(s) on {self.tiles[self.idx]['name']}"
              + (f", {hidden} fully covered" if hidden else ""), flush=True)
        return new_ids

    def clear_drawings(self, quiet=False):
        """Remove the traced shapes. Committed outlines are not touched."""
        drw = self.layer(L_DRAW)
        n = 0 if drw is None else len(drw.data)
        if drw is not None and n:
            try:
                drw.selected_data = set(range(n))
                drw.remove_selected()
            except Exception:
                drw.data = []
        if not quiet:
            self.on_message(f"Cleared <b>{n}</b> drawing(s). Your kept outlines are untouched "
                            f"— <b>DELETE objects</b> removes those.")
        return n

    def delete_at(self, yx):
        """Erase the whole object under data coordinate `yx` (y, x)."""
        com = self.layer(L_COMMITTED)
        try:
            y, x = (int(round(c)) for c in yx[-2:])
            val = int(com.data[y, x])
        except Exception:
            return 0
        if val:
            data = np.asarray(com.data).copy()
            data[data == val] = 0
            com.data = data
        return val

    # -- tiles ----------------------------------------------------------------------
    def save(self):
        """Write the current tile's `committed_objects` to its annotation path."""
        e = self.tiles[self.idx]
        data = np.asarray(self.layer(L_COMMITTED).data).astype(np.uint32)
        os.makedirs(os.path.dirname(e["annotation_path"]), exist_ok=True)
        tifffile.imwrite(e["annotation_path"], data, compression="zlib")
        print(f"[annotate] saved {e['name']} ({self.n_objects()} objects)", flush=True)

    def next_tile(self):
        """N: save this tile, then go to the first tile that is still unfinished.

        An empty tile is saved only on a SECOND N, so a stray key press cannot file a tile
        that was simply forgotten — but a field that really holds no objects (debris only)
        can still be recorded as such, which is a useful negative example for training.
        """
        if self.n_objects() == 0 and not self.empty_confirmed:
            self.empty_confirmed = True
            self.on_message("<b>Nothing is outlined on this tile.</b><br>If the square really "
                            "has no objects in it, press <b>N</b> again to save it as EMPTY. "
                            "Otherwise draw the objects first.")
            return False
        self.save()
        nxt = self.first_unfinished(self.idx + 1)
        if nxt is None:
            self.on_message("<b>All tiles are saved.</b> You can close the window now "
                            "(press <b>B</b> first if you want to look at one again).")
            self.on_finished()
            return True
        self.load(nxt)
        self.on_message(f"Saved. Now on tile <b>{nxt + 1}</b> of {len(self.tiles)}.")
        return True

    def prev_tile(self):
        """B: save this tile if the user changed it, then reopen the previous one.

        Only a CHANGED tile is saved. Saving an untouched one would file the stock first guess
        as the user's answer and mark the tile done, so N would skip it and nobody would ever
        review it.
        """
        if self.idx is None or self.idx <= 0:
            self.on_message("<b>This is the first tile — there is nothing before it.</b>")
            return False
        if self.changed():
            self.save()
        self.load(self.idx - 1)
        self.on_message(f"Back on tile <b>{self.idx + 1}</b> of {len(self.tiles)}, with your "
                        f"saved corrections on it.<br><i>Press N when done — it jumps forward "
                        f"to the first tile you have not annotated yet.</i>")
        return True


def build_helper(viewer, ann):
    """Dock the Annotation Helper panel and bind the keys.

    Everything a beginner gets wrong in napari is a MODE problem — clicking the canvas does
    something different depending on which layer is selected and which tool it is in, and
    nothing on screen explains that. The two mode buttons set layer + tool together, so a
    click always does what the button they last pressed says it does.
    """
    from qtpy import QtWidgets, QtCore

    n_total = len(ann.tiles)
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
    btn_draw = QtWidgets.QPushButton("✏  DRAW objects")
    btn_del = QtWidgets.QPushButton("✖  DELETE objects")
    for b in (btn_draw, btn_del):
        b.setMinimumHeight(44)
        b.setStyleSheet(BTN_BASE)
        lay.addWidget(b)

    def highlight(active, colour):
        """Exactly one mode button is coloured, and it is the mode the canvas is in."""
        for b in (btn_draw, btn_del):
            b.setStyleSheet(BTN_BASE + (f" background:{colour}; color:white;"
                                        if b is active else ""))

    hint = QtWidgets.QLabel()
    hint.setWordWrap(True)
    hint.setStyleSheet("padding:6px; font-size:12px;")
    lay.addWidget(hint)
    ann.on_message = hint.setText

    btn_clear = QtWidgets.QPushButton("⌫  CLEAR my drawings")
    btn_clear.setMinimumHeight(34)
    btn_clear.setStyleSheet("font-size:13px;")
    btn_clear.setToolTip("Remove the yellow shapes you traced. Kept outlines are not touched.")
    lay.addWidget(btn_clear)

    btn_prev = QtWidgets.QPushButton("◀  BACK to previous tile")
    btn_prev.setMinimumHeight(34)
    btn_prev.setStyleSheet("font-size:13px;")
    btn_prev.setToolTip("Save this tile, then reopen the previous one with your corrections.")
    lay.addWidget(btn_prev)

    btn_next = QtWidgets.QPushButton("✓  TILE DONE → NEXT TILE")
    btn_next.setMinimumHeight(44)
    btn_next.setStyleSheet("font-size:14px; font-weight:bold; background:#1f5fa8; color:white;")
    lay.addWidget(btn_next)

    keys_label = QtWidgets.QLabel(
        "<hr><b>S</b> turn your drawings into outlines<br>"
        "<b>C</b> keep them (C alone also works)<br>"
        "<b>D</b> delete the object under the mouse<br><br>"
        "<b>B</b> — back to the previous tile<br>"
        "<b>N</b> — save this tile, go to the next<br>"
        "<span style='color:#d33;'><b>Press N on every tile,<br>including the last one.</b></span>"
        "<br><br><i>A new outline never paints over an existing object — to redraw one, "
        "DELETE it first.</i>")
    keys_label.setWordWrap(True)
    lay.addWidget(keys_label)
    lay.addStretch(1)

    state = {"gesture": 0, "mode": None}

    def set_draw(swap=True):
        """Trace round each object. Pressing DRAW while already drawing swaps lasso <-> polygon."""
        drw = ann.layer(L_DRAW)
        if state["mode"] == "draw" and swap:
            state["gesture"] = (state["gesture"] + 1) % len(GESTURES)
        viewer.layers.selection.active = drw
        active = None
        for g in GESTURES[state["gesture"]:] + GESTURES[:state["gesture"]]:
            try:
                drw.mode = g
                active = str(drw.mode)
                break
            except (ValueError, KeyError, AttributeError):
                continue
        state["mode"] = "draw"
        highlight(btn_draw, "#7a4fa3")
        if active and "lasso" in active:
            how = "<b>Press, drag round the object, release.</b>"
            other = "click-by-click polygon"
        elif active:
            how = "<b>Click round the object</b>, then <b>double-click</b> to close it."
            other = "freehand dragging"
        else:
            hint.setText("<b>Could not switch to a drawing tool.</b>")
            return
        hint.setText(f"{how} Draw as many as you like, then <b>S</b> to see them as outlines, "
                     f"then <b>C</b>.<br><br><i>What you draw is exactly what gets saved, so "
                     f"follow the edge — roughly is fine.</i><br><br>Press <b>DRAW</b> again "
                     f"for {other}.")
        print(f"[annotate] DRAW -> {active}", flush=True)

    def set_delete():
        com = ann.layer(L_COMMITTED)
        viewer.layers.selection.active = com
        com.mode = "fill"
        com.preserve_labels = False             # else the fill refuses to write 0 over a label
        com.selected_label = 0                  # fill target 0 = erase the whole object
        com.n_edit_dimensions = 2
        state["mode"] = "delete"
        highlight(btn_del, "#a33")
        hint.setText("Click on a wrong object → it disappears.")

    def after_tile_change(moved):
        if moved:                               # a fresh tile always starts in DRAW mode, so a
            state["mode"] = None                # click never silently erases on the new tile
            set_draw(swap=False)

    def press_next():
        after_tile_change(ann.next_tile())

    def press_prev():
        after_tile_change(ann.prev_tile())

    btn_draw.clicked.connect(lambda: set_draw())
    btn_del.clicked.connect(set_delete)
    btn_clear.clicked.connect(lambda: ann.clear_drawings())
    btn_prev.clicked.connect(press_prev)
    btn_next.clicked.connect(press_next)

    def delete_under_cursor(_layer=None):
        com = ann.layer(L_COMMITTED)
        try:
            yx = com.world_to_data(viewer.cursor.position)
        except Exception:
            return
        if ann.delete_at(yx):
            hint.setText("Deleted the object under the mouse.")

    # A layer's own key binding shadows the viewer's (napari#7302): the Shapes layer uses S
    # and D for its select tools, the Labels layers bind others. Bind every key on the viewer
    # AND on each of our layers so it does the same thing whichever layer is selected.
    actions = {
        "s": lambda _=None: ann.segment(),
        "c": lambda _=None: ann.commit(),
        "d": delete_under_cursor,
        "n": lambda _=None: press_next(),
        "b": lambda _=None: press_prev(),
    }
    owners = [viewer] + [ann.layer(n) for n in (L_IMAGE, L_COMMITTED, L_CURRENT, L_DRAW)]
    for owner in owners:
        for key, fn in actions.items():
            owner.bind_key(key, fn, overwrite=True)

    def tick():
        try:
            head.setText(f"Tile {ann.idx + 1} of {n_total}")
            btn_prev.setEnabled(ann.idx > 0)
            sub.setText(f"<b>{ann.n_objects()}</b> objects outlined on this tile &nbsp;|&nbsp; "
                        f"{ann.n_saved()} tile(s) saved")
        except Exception:
            pass

    # The run watchdog kills a script that prints nothing for 180 s, and an annotation
    # session is silent for as long as the person is working — a picker session was killed
    # at 52 minutes, losing everything. Say on stdout that the wait is intended.
    t0 = time.time()

    def heartbeat():
        print(f"[annotate] waiting for the user — {ann.n_saved()} of {n_total} tiles saved, "
              f"window open {(time.time() - t0) / 60:.0f} min. This script is MEANT to sit "
              f"here until they close the annotator.", flush=True)

    beat = QtCore.QTimer(panel)
    beat.timeout.connect(heartbeat)
    beat.start(45_000)
    panel._imagentj_beat = beat                 # keep a reference or Qt garbage-collects it
    timer = QtCore.QTimer(panel)
    timer.timeout.connect(tick)
    timer.start(700)
    panel._imagentj_timer = timer

    panel.setMaximumWidth(340)
    viewer.window.add_dock_widget(panel, name="ImagentJ — Annotation Helper", area="right")
    set_draw(swap=False)
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
    print(f"overlays of what was annotated: {prev_dir}")
    if ok < 3:
        print("NOT ENOUGH YET: stage 3 needs at least 3 usable tiles (train + validation).\n"
              "Re-run this script — it resumes at the first unfinished tile.")
    else:
        print(f"READY for stage 3. Run WORKFLOW_FINETUNE_CP_3_TRAIN.py with "
              f"TASK_DIR = {manifest['task_dir']}")
    print("=" * 72)
    return ok


def main():
    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    ann_dir = manifest["dirs"]["annotations"]
    os.makedirs(ann_dir, exist_ok=True)
    n_tiles = len(manifest["tiles"])
    already = len([e for e in manifest["tiles"] if os.path.exists(e["annotation_path"])])
    if already >= n_tiles:
        print(f"All {n_tiles} tiles are already annotated. Nothing to do.")
        report(manifest)
        return

    print(BANNER.format(n=n_tiles - already,
                        instr=os.path.join(TASK_DIR, "ANNOTATION_INSTRUCTIONS.md")))
    if already:
        print(f"Resuming: {already} tile(s) already done.\n")

    import napari

    viewer = napari.Viewer(title="ImagentJ — annotate tiles")
    ann = Annotator(viewer, manifest)
    ann.load(ann.first_unfinished(0))
    build_helper(viewer, ann)
    napari.run()                             # blocks until the human closes the window
    report(manifest)


if __name__ == "__main__":
    main()

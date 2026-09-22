"""Shared helpers for the three ground-truth evaluation scripts.

Why discovery rather than a fixed path
--------------------------------------
Every arm names its own project folder (`hela_rgb_instance_segmentation` in one,
`hela_cell_instance_segmentation` in the next), the deliverable may sit in the arm's
`output/`, in the project's `data/`, or beside the scripts that wrote it, and a run
that was corrected mid-flight often leaves an earlier attempt behind. So nothing here
hardcodes a layout: it looks for the set of TIFFs whose basenames best match the
ground truth, reports what it chose, and lets you override with --pred-glob when the
guess is wrong.

The alternative — assuming a path — fails silently by scoring zero files, which is
indistinguishable from a run that produced nothing.
"""

from __future__ import annotations

import os
import re
import sys
import glob as _glob
from collections import defaultdict

try:
    import numpy as np
except ImportError:                                     # pragma: no cover
    sys.exit("numpy is required:  pip install numpy tifffile")

try:
    import tifffile
except ImportError:                                     # pragma: no cover
    sys.exit("tifffile is required:  pip install tifffile")


IMG_EXT = (".tif", ".tiff")

# Suffixes a run may bolt onto an output name. Stripped when matching a prediction
# to its ground-truth image, so `img_007_mask.tif` still pairs with `img_007.tif`.
_SUFFIXES = ("_mask", "_masks", "_label", "_labels", "_seg", "_segmentation",
             "_cp_masks", "_instance", "_instances", "-mask", "-labels")


def stem_key(path: str) -> str:
    """A filename reduced to the part that should match between GT and prediction."""
    name = os.path.basename(path)
    for ext in IMG_EXT:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    low = name.lower()
    for suf in _SUFFIXES:
        if low.endswith(suf):
            name = name[: -len(suf)]
            break
    return name.lower().strip("_-. ")


def load_label(path: str) -> "np.ndarray":
    """Read a mask as a 2-D integer label image.

    Squeezes singleton axes and, for an RGB-looking array, takes the first channel:
    a run that wrote a colourised overlay instead of a label image is a real failure
    mode, and silently scoring its red channel would hide it — so that case is
    reported by the caller via `looks_like_rgb`.
    """
    arr = tifffile.imread(path)
    arr = np.squeeze(arr)
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):
        arr = arr[..., 0]
    elif arr.ndim == 3:
        arr = arr[0]
    return arr


def looks_like_rgb(path: str) -> bool:
    try:
        arr = np.squeeze(tifffile.imread(path))
    except Exception:
        return False
    return arr.ndim == 3 and arr.shape[-1] in (3, 4)


def find_masks(root: str, want_keys: set, pred_glob: str | None = None) -> dict:
    """Locate the prediction masks under `root`, keyed by stem.

    Picks the DIRECTORY that covers the most ground-truth stems, rather than every
    TIFF anywhere beneath the root — a project folder routinely holds staged copies
    of the inputs, per-channel intermediates and QC montages, all of which share the
    input filenames and would otherwise be scored as if they were the deliverable.
    """
    if pred_glob:
        paths = [p for p in _glob.glob(pred_glob, recursive=True) if os.path.isfile(p)]
        return {stem_key(p): p for p in paths if stem_key(p) in want_keys}

    by_dir: dict[str, dict] = defaultdict(dict)
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(IMG_EXT):
                continue
            key = stem_key(fn)
            if key in want_keys:
                by_dir[dirpath].setdefault(key, os.path.join(dirpath, fn))
    if not by_dir:
        return {}

    def rank(item):
        d, mapping = item
        # Coverage first. Ties go to the directory that looks like a deliverable
        # folder, then to the shallower path — an `output/` beside a stray
        # `processed_images/channels/` copy is the one that was asked for.
        name = os.path.basename(d).lower()
        looks_deliverable = name in ("output", "masks", "results", "res", "data")
        return (len(mapping), looks_deliverable, -d.count(os.sep))

    best_dir, best = max(by_dir.items(), key=rank)
    return {"__dir__": best_dir, **best}


def gt_index(gt_dir: str, pattern: str = "*") -> dict:
    """Ground-truth masks keyed by stem."""
    out = {}
    for dirpath, _d, filenames in os.walk(gt_dir):
        for fn in filenames:
            if fn.lower().endswith(IMG_EXT) and _glob.fnmatch.fnmatch(fn, pattern):
                out.setdefault(stem_key(fn), os.path.join(dirpath, fn))
    return out


def iou_matrix(gt: "np.ndarray", pred: "np.ndarray"):
    """(labels_gt, labels_pred, IoU[i, j]) for every non-zero label pair.

    Built from a joint histogram rather than per-pair boolean masks: an image with a
    few thousand objects makes the pairwise form quadratic in wall time, and these
    datasets reach that easily.
    """
    if gt.shape != pred.shape:
        raise ValueError(f"shape mismatch: gt {gt.shape} vs pred {pred.shape}")
    gt_labels = np.unique(gt); gt_labels = gt_labels[gt_labels != 0]
    pr_labels = np.unique(pred); pr_labels = pr_labels[pr_labels != 0]
    if gt_labels.size == 0 or pr_labels.size == 0:
        return gt_labels, pr_labels, np.zeros((gt_labels.size, pr_labels.size), float)

    gt_idx = {v: i for i, v in enumerate(gt_labels)}
    pr_idx = {v: i for i, v in enumerate(pr_labels)}
    g = np.array([gt_idx.get(v, -1) for v in gt.ravel()])
    p = np.array([pr_idx.get(v, -1) for v in pred.ravel()])
    both = (g >= 0) & (p >= 0)
    inter = np.zeros((gt_labels.size, pr_labels.size), np.int64)
    if both.any():
        np.add.at(inter, (g[both], p[both]), 1)

    gt_area = np.array([(gt == v).sum() for v in gt_labels], np.int64)
    pr_area = np.array([(pred == v).sum() for v in pr_labels], np.int64)
    union = gt_area[:, None] + pr_area[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        iou = np.where(union > 0, inter / union, 0.0)
    return gt_labels, pr_labels, iou


def match_one_to_one(iou: "np.ndarray", threshold: float):
    """Indices of matched (gt, pred) pairs with IoU >= threshold, one-to-one.

    Hungarian assignment when scipy is available, greedy by descending IoU otherwise.
    Above IoU 0.5 the two agree by construction (no object can exceed 0.5 IoU with
    two different objects), so the fallback only matters for the lower thresholds of
    an AP sweep.
    """
    if iou.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment
        rows, cols = linear_sum_assignment(-iou)
        return [(r, c) for r, c in zip(rows, cols) if iou[r, c] >= threshold]
    except ImportError:
        pairs, used_g, used_p = [], set(), set()
        order = np.dstack(np.unravel_index(np.argsort(-iou, axis=None), iou.shape))[0]
        for r, c in order:
            if iou[r, c] < threshold:
                break
            if r in used_g or c in used_p:
                continue
            used_g.add(r); used_p.add(c); pairs.append((int(r), int(c)))
        return pairs


def arm_dirs(results_root: str, only=None):
    """(arm_name, path) for every arm directory under a results root."""
    out = []
    for name in sorted(os.listdir(results_root)):
        path = os.path.join(results_root, name)
        if not os.path.isdir(path) or name in ("learned", "qdrant"):
            continue
        if only and name not in only:
            continue
        out.append((name, path))
    return out


def fmt(x, nd=4):
    return "n/a" if x is None else f"{x:.{nd}f}"

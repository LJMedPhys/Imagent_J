#!/usr/bin/env python3
"""Task 2 — counting error (MSE / RMSE) and segmentation overlap (Dice) vs ground truth.

WHAT IS MEASURED
----------------
Counting, from the required `counts.csv` (columns: filename, cell_count):
    MSE, RMSE, MAE, bias (mean signed error), MAPE, Pearson r and R^2 against the
    ground-truth count per image. Bias is reported separately from MAE on purpose —
    a method that is systematically 20 cells low and one that scatters +-20 have the
    same MAE and very different failure modes.

Segmentation, from the per-image masks:
    Dice on the BINARY foreground (mask > 0), which is what "Dice to compare the
    segmentation masks" conventionally means. It measures pixel overlap and is blind
    to instance identity: two merged cells score the same as two separated ones, as
    long as the pixels agree. That is exactly why task 1 also reports AP — use Dice
    for "did it find the right pixels", AP for "did it find the right objects".

    Both aggregates are given, and they answer different questions:
      * `dice_mean`  — mean of per-image Dice. Each IMAGE counts equally.
      * `dice_agg`   — one Dice over pooled intersection and totals. Each PIXEL counts
                       equally, so large cells and dense images dominate.

The count is ALSO recomputed from the predicted masks, independently of counts.csv.
A run whose CSV and masks disagree has a real bookkeeping bug, and reporting only the
CSV would hide it — `count_csv_vs_mask_mismatch` says how many images disagree.

Usage
-----
    scripts/eval_task2_counts.py --gt /data/task2_gt --results ./ablation_02 \
                                 --out task2_counts.csv
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from eval_common import (IMG_EXT, arm_dirs, find_masks, fmt, gt_index, load_label,
                         stem_key)


def find_counts_csv(root: str):
    """The run's counts.csv. Prefers an exact name, then any CSV with the right columns."""
    exact, candidates = [], []
    for dirpath, _d, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".csv"):
                continue
            path = os.path.join(dirpath, fn)
            (exact if fn.lower() == "counts.csv" else candidates).append(path)
    for path in exact + candidates:
        cols = read_counts(path)
        if cols:
            return path, cols
    return None, {}


def read_counts(path: str):
    """{stem: count} from a CSV with a filename-ish and a count-ish column."""
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return {}
    if not rows:
        return {}
    fields = [f for f in (rows[0].keys() or []) if f]
    name_col = next((f for f in fields if f.strip().lower()
                     in ("filename", "file", "image", "image_name", "name")), None)
    count_col = next((f for f in fields if f.strip().lower()
                      in ("cell_count", "count", "n_cells", "cells", "num_cells")), None)
    if not name_col or not count_col:
        return {}
    out = {}
    for r in rows:
        try:
            out[stem_key(str(r[name_col]))] = float(r[count_col])
        except (TypeError, ValueError):
            continue
    return out


def gt_counts_from_masks(gt_map):
    out = {}
    for key, path in gt_map.items():
        lab = load_label(path)
        vals = np.unique(lab)
        out[key] = int((vals != 0).sum())
    return out


def evaluate(gt_map, gt_counts, root, pred_glob, verbose=True):
    csv_path, pred_counts = find_counts_csv(root)
    found = find_masks(root, set(gt_map), pred_glob)
    mask_dir = found.pop("__dir__", None)

    inter_sum = gt_sum = pr_sum = 0
    dices, errs, mismatch = [], [], 0
    rows = []
    for key in sorted(gt_map):
        g_n = gt_counts[key]
        p_n_csv = pred_counts.get(key)
        p_n_mask = None
        dice = None
        if key in found:
            gt = load_label(gt_map[key]) > 0
            pr = load_label(found[key])
            if pr.shape != gt.shape and pr.shape == gt.shape[::-1]:
                pr = pr.T
            if pr.shape == gt.shape:
                p_n_mask = int((np.unique(pr) != 0).sum())
                prb = pr > 0
                inter = int(np.logical_and(gt, prb).sum())
                a, b = int(gt.sum()), int(prb.sum())
                inter_sum += inter; gt_sum += a; pr_sum += b
                dice = (2 * inter / (a + b)) if (a + b) else 1.0
                dices.append(dice)
        if p_n_csv is not None:
            errs.append(p_n_csv - g_n)
        if p_n_csv is not None and p_n_mask is not None and abs(p_n_csv - p_n_mask) > 0.5:
            mismatch += 1
        rows.append(dict(image=key, gt_count=g_n, pred_count_csv=p_n_csv,
                         pred_count_mask=p_n_mask, dice=dice))

    e = np.array(errs, float) if errs else np.array([])
    gtv = np.array([r["gt_count"] for r in rows if r["pred_count_csv"] is not None], float)
    prv = np.array([r["pred_count_csv"] for r in rows if r["pred_count_csv"] is not None], float)
    mse = float((e ** 2).mean()) if e.size else None
    ss_res = float(((gtv - prv) ** 2).sum()) if gtv.size else None
    ss_tot = float(((gtv - gtv.mean()) ** 2).sum()) if gtv.size else None
    summary = {
        "counts_csv": csv_path,
        "mask_dir": mask_dir,
        "images_gt": len(gt_map),
        "images_with_count": int(gtv.size),
        "images_with_mask": len(dices),
        "MSE": mse,
        "RMSE": float(np.sqrt(mse)) if mse is not None else None,
        "MAE": float(np.abs(e).mean()) if e.size else None,
        "bias": float(e.mean()) if e.size else None,
        "MAPE_pct": float(np.mean(np.abs(e) / np.maximum(gtv, 1)) * 100) if e.size else None,
        # Undefined, not zero, when either side is constant — numpy would return nan
        # after a divide warning, and a printed nan reads like a computed result.
        "pearson_r": (float(np.corrcoef(gtv, prv)[0, 1])
                      if gtv.size > 1 and gtv.std() > 0 and prv.std() > 0 else None),
        "R2": (1 - ss_res / ss_tot) if (ss_tot not in (None, 0.0)) else None,
        "dice_mean": float(np.mean(dices)) if dices else None,
        "dice_std": float(np.std(dices)) if dices else None,
        "dice_agg": (2 * inter_sum / (gt_sum + pr_sum)) if (gt_sum + pr_sum) else None,
        "count_csv_vs_mask_mismatch": mismatch,
        "gt_total_cells": int(sum(gt_counts.values())),
        "pred_total_cells_csv": int(prv.sum()) if prv.size else None,
    }
    if verbose:
        print(f"    counts.csv: {csv_path or 'NOT FOUND'}")
        print(f"    masks     : {mask_dir or 'NOT FOUND'}")
        if mismatch:
            print(f"    !! {mismatch} image(s) where counts.csv disagrees with its own mask")
    return rows, summary


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gt", required=True, help="directory of ground-truth label TIFFs")
    p.add_argument("--gt-pattern", default="*")
    p.add_argument("--gt-counts", help="optional CSV of true counts; else counted from masks")
    p.add_argument("--pred", help="a single directory to evaluate")
    p.add_argument("--results", help="an ablation results root; every arm is scored")
    p.add_argument("--only", nargs="+")
    p.add_argument("--pred-glob")
    p.add_argument("--out", help="write per-arm summary CSV here")
    p.add_argument("--per-image", help="write per-image rows CSV here (single --pred only)")
    args = p.parse_args()
    if not args.pred and not args.results:
        p.error("give --pred or --results")

    gt_map = gt_index(args.gt, args.gt_pattern)
    if not gt_map:
        sys.exit(f"no ground-truth TIFFs under {args.gt}")
    if args.gt_counts:
        gt_counts = read_counts(args.gt_counts)
        missing = set(gt_map) - set(gt_counts)
        if missing:
            print(f"!! {len(missing)} GT image(s) absent from {args.gt_counts}; "
                  f"counting those from their masks")
            gt_counts.update({k: v for k, v in gt_counts_from_masks(
                {k: gt_map[k] for k in missing}).items()})
    else:
        gt_counts = gt_counts_from_masks(gt_map)
    print(f"ground truth: {len(gt_map)} image(s), "
          f"{sum(gt_counts.values())} cells total\n")

    targets = ([(os.path.basename(args.pred.rstrip('/')), args.pred)] if args.pred
               else arm_dirs(args.results, args.only))
    summaries = []
    for name, path in targets:
        print(f"  --- {name} ---")
        rows, s = evaluate(gt_map, gt_counts, path, args.pred_glob)
        print(f"    counts : RMSE {fmt(s['RMSE'],2)}  MSE {fmt(s['MSE'],2)}  "
              f"MAE {fmt(s['MAE'],2)}  bias {fmt(s['bias'],2)}  R2 {fmt(s['R2'])}")
        print(f"    dice   : mean {fmt(s['dice_mean'])} +- {fmt(s['dice_std'])}   "
              f"aggregate {fmt(s['dice_agg'])}")
        print(f"    covered: {s['images_with_count']} counted / "
              f"{s['images_with_mask']} masked of {s['images_gt']}\n")
        summaries.append({"arm": name, **s})
        if args.per_image and args.pred:
            with open(args.per_image, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader()
                w.writerows(rows)
            print(f"    per-image rows -> {args.per_image}")

    if args.out and summaries:
        keys = ["arm"] + [k for k in summaries[0] if k != "arm"]
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader(); w.writerows(summaries)
        print(f"summary -> {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Task 1 — instance-segmentation accuracy against ground truth: AP@0.5 and AP@[0.5:0.95].

WHICH "AP" THIS IS, AND WHY
---------------------------
This is the average precision used by Cellpose, StarDist and the Data Science Bowl
segmentation literature:

    AP(tau) = TP / (TP + FP + FN)

at an IoU threshold `tau`, with one-to-one matching between ground-truth and predicted
objects. It is NOT COCO AP. COCO averages precision over a recall curve, which needs a
CONFIDENCE SCORE per predicted object to rank detections — a label mask carries no such
score, so that curve cannot be drawn from these deliverables at all. Reporting this
number as "COCO mAP" would be wrong, and the two are not comparable; say which you used.

AP@[0.5:0.95] is the mean of AP(tau) over tau = 0.50, 0.55, ..., 0.95 (ten thresholds),
matching the same convention.

Two aggregates are reported because the literature uses both and they differ whenever
images hold different numbers of cells:
  * `AP_micro`  — pool TP/FP/FN over every image, then divide. Weights each CELL equally.
  * `AP_macro`  — mean of the per-image AP values. Weights each IMAGE equally.
Quote whichever you prefer, but quote which.

Usage
-----
    # one prediction folder
    scripts/eval_task1_ap.py --gt /data/task1_gt --pred ablation_01/baseline

    # every arm of a study, into one CSV
    scripts/eval_task1_ap.py --gt /data/task1_gt --results ./ablation_01 \
                             --out task1_ap.csv
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from eval_common import (arm_dirs, find_masks, fmt, gt_index, iou_matrix,
                         load_label, looks_like_rgb, match_one_to_one)

THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]      # 0.50 … 0.95


def score_pair(gt_path, pred_path, thresholds):
    """{tau: (tp, fp, fn)} for one image pair, plus object counts."""
    gt = load_label(gt_path)
    pred = load_label(pred_path)
    if gt.shape != pred.shape:
        # Shapes must match or the IoU is meaningless. Transposed is a common and
        # recoverable case; anything else is reported rather than silently coerced.
        if gt.shape == pred.shape[::-1]:
            pred = pred.T
        else:
            raise ValueError(f"shape mismatch gt{gt.shape} vs pred{pred.shape}")
    gl, pl, iou = iou_matrix(gt, pred)
    per_tau = {}
    for tau in thresholds:
        matches = match_one_to_one(iou, tau)
        tp = len(matches)
        per_tau[tau] = (tp, len(pl) - tp, len(gl) - tp)
    return per_tau, len(gl), len(pl)


def evaluate(gt_map, pred_root, pred_glob, thresholds, verbose=True):
    found = find_masks(pred_root, set(gt_map), pred_glob)
    chosen_dir = found.pop("__dir__", pred_glob or pred_root)
    if not found:
        return None, {"error": "no prediction masks matched the ground-truth filenames",
                      "searched": pred_root}

    totals = {t: [0, 0, 0] for t in thresholds}
    per_image_ap = {t: [] for t in thresholds}
    rows, skipped, rgb_warn = [], [], 0
    for key in sorted(gt_map):
        if key not in found:
            skipped.append(key)
            continue
        if looks_like_rgb(found[key]):
            rgb_warn += 1
        try:
            per_tau, n_gt, n_pred = score_pair(gt_map[key], found[key], thresholds)
        except Exception as exc:
            skipped.append(f"{key} ({exc})")
            continue
        for t in thresholds:
            tp, fp, fn = per_tau[t]
            totals[t][0] += tp; totals[t][1] += fp; totals[t][2] += fn
            denom = tp + fp + fn
            per_image_ap[t].append(tp / denom if denom else 1.0)
        tp5, fp5, fn5 = per_tau[0.5]
        rows.append(dict(image=key, n_gt=n_gt, n_pred=n_pred,
                         tp50=tp5, fp50=fp5, fn50=fn5,
                         ap50=tp5 / (tp5 + fp5 + fn5) if (tp5 + fp5 + fn5) else 1.0))

    def micro(t):
        tp, fp, fn = totals[t]
        return tp / (tp + fp + fn) if (tp + fp + fn) else None

    summary = {
        "images_scored": len(rows),
        "images_missing_pred": len(skipped),
        "objects_gt": sum(r["n_gt"] for r in rows),
        "objects_pred": sum(r["n_pred"] for r in rows),
        "AP50_micro": micro(0.5),
        "AP50_macro": float(np.mean(per_image_ap[0.5])) if per_image_ap[0.5] else None,
        "AP50_95_micro": float(np.mean([micro(t) for t in thresholds
                                        if micro(t) is not None])) or None,
        "AP50_95_macro": float(np.mean([np.mean(per_image_ap[t]) for t in thresholds
                                        if per_image_ap[t]])) if rows else None,
        "pred_dir": chosen_dir,
        "rgb_predictions": rgb_warn,
    }
    for t in thresholds:
        summary[f"AP{int(t*100)}_micro"] = micro(t)
    if verbose:
        print(f"    masks from: {chosen_dir}")
        print(f"    scored {len(rows)} image(s); {len(skipped)} without a prediction")
        if rgb_warn:
            print(f"    !! {rgb_warn} prediction(s) look like RGB/overlay images, not "
                  f"label masks — their first channel was scored; check these")
        if skipped[:5]:
            print(f"    missing: {', '.join(map(str, skipped[:5]))}"
                  f"{' …' if len(skipped) > 5 else ''}")
    return rows, summary


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gt", required=True, help="directory of ground-truth label TIFFs")
    p.add_argument("--gt-pattern", default="*", help="filename filter inside --gt")
    p.add_argument("--pred", help="a single directory to search for predictions")
    p.add_argument("--results", help="an ablation results root; every arm is scored")
    p.add_argument("--only", nargs="+", help="with --results, only these arms")
    p.add_argument("--pred-glob", help="explicit glob for predictions, overriding discovery")
    p.add_argument("--out", help="write per-arm summary CSV here")
    p.add_argument("--per-image", help="write per-image rows CSV here (single --pred only)")
    args = p.parse_args()

    if not args.pred and not args.results:
        p.error("give --pred or --results")

    gt_map = gt_index(args.gt, args.gt_pattern)
    if not gt_map:
        sys.exit(f"no ground-truth TIFFs under {args.gt}")
    print(f"ground truth: {len(gt_map)} image(s) from {args.gt}\n")

    targets = ([(os.path.basename(args.pred.rstrip('/')), args.pred)] if args.pred
               else arm_dirs(args.results, args.only))
    summaries = []
    for name, path in targets:
        print(f"  --- {name} ---")
        rows, summary = evaluate(gt_map, path, args.pred_glob, THRESHOLDS)
        if rows is None:
            print(f"    !! {summary['error']}")
            summaries.append({"arm": name, **summary})
            continue
        print(f"    AP@0.50      micro {fmt(summary['AP50_micro'])}   "
              f"macro {fmt(summary['AP50_macro'])}")
        print(f"    AP@0.50:0.95 micro {fmt(summary['AP50_95_micro'])}   "
              f"macro {fmt(summary['AP50_95_macro'])}")
        print(f"    objects: {summary['objects_pred']} predicted vs "
              f"{summary['objects_gt']} ground truth\n")
        summaries.append({"arm": name, **summary})
        if args.per_image and args.pred:
            with open(args.per_image, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader()
                w.writerows(rows)
            print(f"    per-image rows -> {args.per_image}")

    if args.out and summaries:
        keys = sorted({k for s in summaries for k in s})
        keys = ["arm"] + [k for k in keys if k != "arm"]
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(summaries)
        print(f"summary -> {args.out}")


if __name__ == "__main__":
    main()

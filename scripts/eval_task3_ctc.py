#!/usr/bin/env python3
"""Task 3 — Cell Tracking Challenge DET and TRA against ground truth.

READ THIS BEFORE QUOTING A NUMBER
---------------------------------
DET and TRA are a published algorithm (AOGM — Matula et al., PLoS ONE 2015,
"Cell Tracking Accuracy Measurement Based on Comparison of Acyclic Oriented Graphs"),
and the challenge distributes reference binaries for it. The evaluation-methodology
page gives only the normalisation:

    DET = 1 - min(AOGM-D, AOGM-D0) / AOGM-D0
    TRA = 1 - min(AOGM,   AOGM0)   / AOGM0

It does NOT publish the operation weights, so this script does two things rather than
one, and the difference matters for a paper:

  1. If `py-ctcmetrics` is installed it uses that — a maintained, community-validated
     implementation of the official measure. This is the number to publish.
         pip install py-ctcmetrics

  2. Otherwise it falls back to the INDEPENDENT reimplementation below, whose weights
     are taken from the AOGM paper and stated explicitly in WEIGHTS. Treat its output
     as an internal comparison between arms, not as a challenge-comparable score, and
     say so if it reaches a manuscript. Arms are ranked consistently either way; the
     absolute value is what depends on getting every operation exactly right.

The script reports which path produced each number in the `implementation` column.

EXPECTED LAYOUT
---------------
Predictions (what the task asked the agent for) are already CTC RES format:
    <pred>/output/mask000.tif, mask001.tif, …     one label TIFF per frame
    <pred>/output/res_track.txt                   "ID start end parent" per line
Ground truth is CTC TRA format:
    <gt>/man_track000.tif, …                      one marker TIFF per frame
    <gt>/man_track.txt                            "ID start end parent" per line

Task 3 ran two experiments (01/ and 02/) and they are scored separately — pass --gt
once per experiment, or use --experiments to map them in one go.

Usage
-----
    # one experiment, one arm
    scripts/eval_task3_ctc.py --gt /data/task3/01_GT/TRA --pred ablation_03/baseline

    # both experiments, every arm, into one CSV
    scripts/eval_task3_ctc.py --experiments 01=/data/task3/01_GT/TRA \
                                            02=/data/task3/02_GT/TRA \
                              --results ./ablation_03 --out task3_ctc.csv
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from eval_common import arm_dirs, fmt, load_label

# AOGM operation costs, from Matula et al. 2015. Stated here rather than buried so a
# reader can check them against the paper without reading the code.
WEIGHTS = {
    "NS": 5.0,    # split a computed vertex that covers several reference markers
    "FN": 10.0,   # add a missing vertex
    "FP": 1.0,    # delete a spurious vertex
    "ED": 1.0,    # delete an edge
    "EA": 1.5,    # add an edge
    "EC": 1.0,    # correct an edge's semantics (parent link vs same-cell link)
}

_FRAME_RE = re.compile(r"(\d+)\D*$")


def frame_of(path: str):
    m = _FRAME_RE.search(os.path.splitext(os.path.basename(path))[0])
    return int(m.group(1)) if m else None


def read_track_file(path: str) -> dict:
    """{track_id: (start, end, parent)} from a CTC res_track.txt / man_track.txt."""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                tid, start, end, parent = (int(float(x)) for x in parts[:4])
            except ValueError:
                continue
            out[tid] = (start, end, parent)
    return out


def find_ctc_dir(root: str):
    """The directory under `root` holding mask TIFFs plus a track text file."""
    best = None
    for dirpath, _d, filenames in os.walk(root):
        masks = [f for f in filenames
                 if f.lower().endswith((".tif", ".tiff")) and frame_of(f) is not None]
        track = next((f for f in filenames
                      if f.lower() in ("res_track.txt", "man_track.txt")), None)
        if masks and track:
            cand = (len(masks), dirpath, track)
            if best is None or cand[0] > best[0]:
                best = cand
    if not best:
        return None, None, None
    n, dirpath, track = best
    return dirpath, os.path.join(dirpath, track), n


def build_graph(mask_dir: str, track_path: str):
    """Nodes {(track_id, frame)} and edges {((id,t),(id2,t2)): 'same'|'parent'}.

    Nodes come from the MASKS, not the track file: the track file is a claim, the
    pixels are the evidence, and a run whose text file lists cells its masks do not
    contain should be penalised for the missing detections rather than credited.
    """
    frames = {}
    for fn in sorted(os.listdir(mask_dir)):
        if not fn.lower().endswith((".tif", ".tiff")):
            continue
        t = frame_of(fn)
        if t is None:
            continue
        frames[t] = os.path.join(mask_dir, fn)

    labels_at = {}
    for t, path in frames.items():
        lab = load_label(path)
        vals = np.unique(lab)
        labels_at[t] = set(int(v) for v in vals if v != 0)

    nodes = {(l, t) for t, labs in labels_at.items() for l in labs}
    tracks = read_track_file(track_path) if os.path.exists(track_path) else {}

    edges = {}
    ordered = sorted(labels_at)
    for i, t in enumerate(ordered[:-1]):
        t2 = ordered[i + 1]
        for l in labels_at[t] & labels_at[t2]:
            edges[((l, t), (l, t2))] = "same"
    for tid, (start, _end, parent) in tracks.items():
        if parent and (tid, start) in nodes:
            prev = [t for t in ordered if t < start and parent in labels_at.get(t, ())]
            if prev:
                edges[((parent, prev[-1]), (tid, start))] = "parent"
    return frames, labels_at, nodes, edges


def match_nodes(gt_frames, gt_labels_at, res_frames, res_labels_at):
    """GT node -> RES node, by the CTC rule: overlap > 50% of the reference marker.

    That threshold is what makes the matching a function: no computed segment can
    cover more than half of two different reference markers, so each reference marker
    has at most one match, while one computed segment may be claimed by several
    reference markers — which is precisely the under-segmentation the NS operation
    charges for.
    """
    mapping, res_seen = {}, defaultdict(list)
    for t in sorted(set(gt_frames) & set(res_frames)):
        gt = load_label(gt_frames[t])
        res = load_label(res_frames[t])
        if gt.shape != res.shape:
            if gt.shape == res.shape[::-1]:
                res = res.T
            else:
                continue
        gt_flat, res_flat = gt.ravel(), res.ravel()
        for m in gt_labels_at.get(t, ()):
            sel = gt_flat == m
            area = int(sel.sum())
            if not area:
                continue
            overlaps = res_flat[sel]
            overlaps = overlaps[overlaps != 0]
            if overlaps.size == 0:
                continue
            vals, counts = np.unique(overlaps, return_counts=True)
            j = int(np.argmax(counts))
            if counts[j] > 0.5 * area:
                r = (int(vals[j]), t)
                mapping[(m, t)] = r
                res_seen[r].append((m, t))
    return mapping, res_seen


def aogm(gt_nodes, gt_edges, res_nodes, res_edges, mapping, res_seen):
    """AOGM / AOGM-D counts for one experiment."""
    tp = len(mapping)
    fn = len(gt_nodes) - tp
    matched_res = set(mapping.values())
    fp = len(res_nodes - matched_res)
    # One computed vertex claimed by k reference markers needs k-1 splits.
    ns = sum(len(v) - 1 for v in res_seen.values() if len(v) > 1)

    # Edges, evaluated on the subgraph induced by the matching.
    induced = {}
    for (u, v), sem in res_edges.items():
        induced[(u, v)] = sem
    ea = ec = 0
    used_res_edges = set()
    for (u, v), sem in gt_edges.items():
        ru, rv = mapping.get(u), mapping.get(v)
        if ru is None or rv is None:
            ea += 1                       # an endpoint is missing, so is the edge
            continue
        res_sem = induced.get((ru, rv))
        if res_sem is None:
            ea += 1
        else:
            used_res_edges.add((ru, rv))
            if res_sem != sem:
                ec += 1
    ed = len([e for e in res_edges if e not in used_res_edges])

    W = WEIGHTS
    aogm_d = W["NS"] * ns + W["FN"] * fn + W["FP"] * fp
    aogm_d0 = W["FN"] * len(gt_nodes)
    aogm_full = aogm_d + W["ED"] * ed + W["EA"] * ea + W["EC"] * ec
    aogm0 = W["FN"] * len(gt_nodes) + W["EA"] * len(gt_edges)
    det = 1 - min(aogm_d, aogm_d0) / aogm_d0 if aogm_d0 else None
    tra = 1 - min(aogm_full, aogm0) / aogm0 if aogm0 else None
    return dict(DET=det, TRA=tra, TP=tp, FN=fn, FP=fp, NS=ns, ED=ed, EA=ea, EC=ec,
                gt_nodes=len(gt_nodes), gt_edges=len(gt_edges),
                res_nodes=len(res_nodes), res_edges=len(res_edges),
                AOGM_D=aogm_d, AOGM_D0=aogm_d0, AOGM=aogm_full, AOGM0=aogm0)


def try_official(gt_dir, res_dir):
    """DET/TRA from py-ctcmetrics, or None if it is not installed / cannot run."""
    try:
        from ctc_metrics import evaluate_sequence            # type: ignore
    except ImportError:
        return None
    try:
        res = evaluate_sequence(res_dir, gt_dir, metrics=["DET", "TRA"])
        return {"DET": res.get("DET"), "TRA": res.get("TRA"),
                "implementation": "py-ctcmetrics"}
    except Exception as exc:
        print(f"    !! py-ctcmetrics failed ({type(exc).__name__}: {exc}); "
              f"falling back to the built-in implementation")
        return None


def evaluate(gt_dir, pred_root, verbose=True):
    gt_mask_dir, gt_track, n_gt = find_ctc_dir(gt_dir)
    if not gt_mask_dir:
        return {"error": f"no CTC ground truth (masks + man_track.txt) under {gt_dir}"}
    res_mask_dir, res_track, n_res = find_ctc_dir(pred_root)
    if not res_mask_dir:
        return {"error": f"no CTC result (masks + res_track.txt) under {pred_root}"}
    if verbose:
        print(f"    gt : {gt_mask_dir} ({n_gt} frames)")
        print(f"    res: {res_mask_dir} ({n_res} frames)")

    official = try_official(gt_mask_dir, res_mask_dir)

    gt_frames, gt_labels_at, gt_nodes, gt_edges = build_graph(gt_mask_dir, gt_track)
    res_frames, res_labels_at, res_nodes, res_edges = build_graph(res_mask_dir, res_track)
    missing = set(gt_frames) - set(res_frames)
    mapping, res_seen = match_nodes(gt_frames, gt_labels_at, res_frames, res_labels_at)
    out = aogm(gt_nodes, gt_edges, res_nodes, res_edges, mapping, res_seen)
    out["frames_gt"] = len(gt_frames)
    out["frames_res"] = len(res_frames)
    out["frames_missing"] = len(missing)
    out["implementation"] = "built-in (AOGM reimplementation)"
    if official:
        out["DET_builtin"], out["TRA_builtin"] = out["DET"], out["TRA"]
        out.update(official)
    if verbose and missing:
        print(f"    !! {len(missing)} ground-truth frame(s) have no result mask")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gt", help="CTC TRA ground-truth dir for a single experiment")
    p.add_argument("--experiments", nargs="+", metavar="NAME=GTDIR",
                   help="score several experiments, e.g. 01=/data/01_GT/TRA 02=…")
    p.add_argument("--pred", help="a single directory to evaluate")
    p.add_argument("--results", help="an ablation results root; every arm is scored")
    p.add_argument("--only", nargs="+")
    p.add_argument("--out", help="write summary CSV here")
    args = p.parse_args()
    if not args.gt and not args.experiments:
        p.error("give --gt or --experiments")
    if not args.pred and not args.results:
        p.error("give --pred or --results")

    exps = {}
    if args.gt:
        exps["-"] = args.gt
    for spec in (args.experiments or []):
        if "=" not in spec:
            p.error(f"--experiments wants NAME=GTDIR, got {spec!r}")
        name, path = spec.split("=", 1)
        exps[name] = path

    targets = ([(os.path.basename(args.pred.rstrip('/')), args.pred)] if args.pred
               else arm_dirs(args.results, args.only))
    rows = []
    for name, path in targets:
        for exp, gt_dir in exps.items():
            label = f"{name}" + (f" [exp {exp}]" if exp != "-" else "")
            print(f"  --- {label} ---")
            # An experiment lives in its own subfolder when the run kept them apart.
            root = path
            for cand in (os.path.join(path, exp), os.path.join(path, "output", exp)):
                if exp != "-" and os.path.isdir(cand):
                    root = cand
                    break
            res = evaluate(gt_dir, root)
            if "error" in res:
                print(f"    !! {res['error']}")
            else:
                print(f"    DET {fmt(res['DET'])}   TRA {fmt(res['TRA'])}   "
                      f"[{res['implementation']}]")
                print(f"    nodes TP {res['TP']} FN {res['FN']} FP {res['FP']} "
                      f"NS {res['NS']} | edges EA {res['EA']} ED {res['ED']} "
                      f"EC {res['EC']}\n")
            rows.append({"arm": name, "experiment": exp, **res})

    if args.out and rows:
        keys = sorted({k for r in rows for k in r})
        keys = ["arm", "experiment"] + [k for k in keys if k not in ("arm", "experiment")]
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
        print(f"summary -> {args.out}")


if __name__ == "__main__":
    main()

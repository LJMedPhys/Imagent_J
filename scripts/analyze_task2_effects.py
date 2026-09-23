#!/usr/bin/env python3
"""Component study, task 2 (cell counting, BBBC005) — noise floor, then effects.

WHAT IT MEASURES
----------------
Per run:  RMSE, MAE, bias on the counts; Dice on the subset with ground-truth masks;
          plus cost and wall time as secondary outcomes.

Ground truth for the counts comes from the filename — BBBC005 is synthetic and each
image carries its own answer:

    SIMCEPImages_A03_C10_F1_s01_w1.TIF
                     ^^^^ 10 cells      ^^ focus blur level

so counting is scored on every image. Dice needs a mask, and BBBC005 ships those only
for the in-focus subset, so Dice covers far fewer images and ALL OF THEM ARE SHARP.
It cannot speak for the blurred majority; `by_blur` in the per-run CSV is where that
lives.

THE THREE THINGS IT PRINTS
--------------------------
1. NOISE FLOOR — the spread across repeats of one arm. This is the unit every effect
   is measured in. An effect smaller than the noise is not an effect, however
   suggestive the means look.

2. TOTAL EFFECT — baseline vs all_off. This is the gate: it is the combined
   contribution of every component, and therefore an UPPER BOUND on any single one.
   If it is inside the noise, no leave-one-out or add-one-in arm can show anything
   and there is nothing to go looking for.

3. PER-COMPONENT EFFECTS, when those arms exist:
       LOO(X) = M(baseline)    - M(no_X)       what X adds given everything else
       AOI(X) = M(only_X)      - M(all_off)    what X does on its own
   with M oriented so HIGHER IS BETTER (error metrics are negated), a confidence
   interval from the repeats, and a standardised effect d = effect / pooled SD so
   metrics on different scales can be compared.

   Reading the pair:
       large / large -> genuinely useful      ~0 / large -> redundant
       large / ~0    -> only works with others  ~0 / ~0   -> does nothing

Usage
-----
    scripts/analyze_task2_effects.py --results ./study_task2 --gt-masks <dir> \
                                     --out effects.csv
"""

import argparse
import csv
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np
import tifffile

META = re.compile(r"_C(\d+)_F(\d+)_s(\d+)_w(\d+)", re.I)
RATES = {"gpt-5.6-sol": (4.00, 20.00, 0.10), "gpt-5.3-codex": (1.75, 14.00, 0.10),
         "gpt-5.6-luna": (0.10, 0.60, 0.10), "gpt-5.4-mini": (0.75, 4.50, 0.10),
         "gpt-4o-mini": (0.15, 0.60, 0.50)}
# metric -> +1 if higher is better, -1 if lower is better
DIRECTION = {"rmse": -1, "mae": -1, "dice_mean": +1, "cost_usd": -1, "minutes": -1}
REMOVABLE = ["rag", "concepts", "code_memory", "discovery", "vlm"]


def key_of(name):
    b = os.path.basename(str(name)).strip().strip('"')
    b = re.sub(r"\.(tif|tiff)$", "", b, flags=re.I)
    return re.sub(r"_(mask|masks|labels?|seg)$", "", b, flags=re.I).lower()


def base_arm(name):
    return re.sub(r"__r\d+$", "", name)


def money(st):
    total = 0.0
    for m, v in (st.get("by_model") or {}).items():
        pi, po, cf = RATES.get(m, (1.25, 10.0, 0.10))
        i, o, k = v["input_tokens"], v["output_tokens"], v.get("cached_input_tokens", 0)
        total += ((i - k) * pi + k * pi * cf + o * po) / 1e6
    return total


def find_one(root, *patterns):
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(root, pat), recursive=True))
        hits = [h for h in hits if "qdrant" not in h and "/learned/" not in h]
        if hits:
            return hits[0]
    return None


def read_counts(path):
    out = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            fn = r.get("filename") or r.get("file") or r.get("image")
            c = r.get("cell_count") or r.get("count") or r.get("n_cells")
            if fn is None or c is None:
                continue
            try:
                out[key_of(fn)] = float(c)
            except ValueError:
                pass
    return out


def binary(path):
    a = np.squeeze(tifffile.imread(path))
    if a.ndim == 3:
        a = a[..., 0] if a.shape[-1] in (3, 4) else a[0]
    return a > 0


def load_mapping(path):
    """{anonymised name -> (true_count, focus)} from anonymize_inputs.py's key."""
    out = {}
    with open(path, newline="") as fh:
        rows = [l for l in fh if not l.startswith("#")]
    for r in csv.DictReader(rows):
        try:
            out[key_of(r["new_name"])] = (float(r["true_count"]), int(r["focus"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def score_run(run_dir, gt_masks, mapping=None):
    """RMSE / MAE / bias / Dice / cost / minutes for one run directory."""
    csv_path = find_one(run_dir, "**/counts.csv", "**/*count*.csv")
    if not csv_path:
        return None
    pred = read_counts(csv_path)
    if not pred:
        return None

    errs, blur = [], defaultdict(list)
    for k, pc in pred.items():
        if mapping is not None:
            if k not in mapping:
                continue
            true_c, focus = mapping[k]
        else:
            # Fall back to the filename, which is where the answer sits in a
            # dataset that has not been anonymised — and is exactly why it should be.
            m = META.search(k)
            if not m:
                continue
            true_c, focus = int(m.group(1)), int(m.group(2))
        errs.append(pc - true_c)
        blur[focus].append(pc - true_c)
    e = np.asarray(errs, float)

    # Dice on whatever ground-truth masks exist, against the run's own mask folder.
    dices, masks = [], {}
    if gt_masks:
        for p in glob.glob(os.path.join(run_dir, "**", "*"), recursive=True):
            # Case-sensitive globbing is why this silently found nothing: BBBC005
            # ships .TIF and the runs write .tif, so "**/*.tif" matched the
            # predictions but a "*.TIF" ground truth (or the reverse) matched
            # neither. Match on the extension case-insensitively instead.
            if not p.lower().endswith((".tif", ".tiff")) or not os.path.isfile(p):
                continue
            if "qdrant" in p or "/learned/" in p:
                continue
            k = key_of(p)
            if k in gt_masks:
                masks.setdefault(k, p)
        for k, gp in gt_masks.items():
            if k not in masks:
                continue
            g, pr = binary(gp), binary(masks[k])
            if pr.shape != g.shape and pr.shape == g.shape[::-1]:
                pr = pr.T
            if pr.shape != g.shape:
                continue
            i = int(np.logical_and(g, pr).sum())
            a, b = int(g.sum()), int(pr.sum())
            dices.append((2 * i / (a + b)) if (a + b) else 1.0)

    cost = minutes = None
    rj = os.path.join(run_dir, "result.json")
    if os.path.exists(rj):
        try:
            md = (json.load(open(rj)).get("metadata") or {})
            cost = round(money(md.get("session_totals") or {}), 3)
        except Exception:
            pass
    # A perfect score over hundreds of images is not a result, it is a tell: the
    # counts were read rather than measured. Flagged, never silently averaged in.
    exact = int(np.sum(e == 0))
    leaked = bool(e.size >= 50 and exact == e.size)
    return dict(
        images=int(e.size),
        exact_matches=exact,
        leaked=leaked,
        rmse=float(np.sqrt((e ** 2).mean())) if e.size else None,
        mae=float(np.abs(e).mean()) if e.size else None,
        bias=float(e.mean()) if e.size else None,
        dice_mean=float(np.mean(dices)) if dices else None,
        dice_n=len(dices),
        # A silent n/a is indistinguishable from "scored zero", so record how many
        # of the run's files were even candidates.
        masks_found=len(masks) if gt_masks else 0,
        cost_usd=cost, minutes=minutes,
        rmse_sharp=_band(blur, 1, 10), rmse_mid=_band(blur, 14, 26),
        rmse_blurred=_band(blur, 29, 48),
    )


def _band(blur, lo, hi):
    vals = [v for f, arr in blur.items() if lo <= f <= hi for v in arr]
    return float(np.sqrt(np.mean(np.square(vals)))) if vals else None


def agg(values):
    v = [x for x in values if x is not None]
    if not v:
        return None, None, 0
    return float(np.mean(v)), (float(np.std(v, ddof=1)) if len(v) > 1 else 0.0), len(v)


def effect(a_vals, b_vals, metric):
    """M(a) - M(b) with M oriented higher-better, plus CI and standardised d."""
    sign = DIRECTION.get(metric, +1)
    a = [x * sign for x in a_vals if x is not None]
    b = [x * sign for x in b_vals if x is not None]
    if len(a) < 1 or len(b) < 1:
        return None
    ma, mb = np.mean(a), np.mean(b)
    sa = np.std(a, ddof=1) if len(a) > 1 else 0.0
    sb = np.std(b, ddof=1) if len(b) > 1 else 0.0
    d_raw = ma - mb
    se = math.sqrt(sa ** 2 / max(len(a), 1) + sb ** 2 / max(len(b), 1))
    pooled = math.sqrt(((len(a) - 1) * sa ** 2 + (len(b) - 1) * sb ** 2) /
                       max(len(a) + len(b) - 2, 1)) if (len(a) + len(b)) > 2 else 0.0
    t = 2.776 if min(len(a), len(b)) <= 5 else 1.96          # t(.975, df=4) ~ 2.776
    return dict(effect=d_raw, se=se, lo=d_raw - t * se, hi=d_raw + t * se,
                d=(d_raw / pooled) if pooled else None,
                n_a=len(a), n_b=len(b),
                significant=bool(se > 0 and (d_raw - t * se) * (d_raw + t * se) > 0))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", required=True, help="the study results root")
    p.add_argument("--gt-masks", help="directory of ground-truth masks, for Dice")
    p.add_argument("--mapping", help="anonymize_inputs.py key, so true counts come "
                                     "from the mapping instead of the filename")
    p.add_argument("--keep-leaked", action="store_true",
                   help="include runs whose counts exactly match ground truth on every "
                        "image (by default they are reported and excluded)")
    p.add_argument("--out", help="write the per-run metrics CSV here")
    args = p.parse_args()

    gt_masks = {}
    if args.gt_masks:
        gt_masks = {key_of(p_): p_ for p_ in glob.glob(os.path.join(args.gt_masks, "*"))
                    if os.path.isfile(p_)}
        print(f"ground-truth masks for Dice: {len(gt_masks)}")

    mapping = load_mapping(args.mapping) if args.mapping else None
    if mapping:
        print(f"scoring through the mapping: {len(mapping)} images")

    runs = {}
    for d in sorted(os.listdir(args.results)):
        full = os.path.join(args.results, d)
        if not os.path.isdir(full) or d in ("learned", "qdrant"):
            continue
        s = score_run(full, gt_masks, mapping)
        if s:
            runs[d] = s
    if not runs:
        sys.exit(f"no scorable runs under {args.results}")

    leaked = {n: s for n, s in runs.items() if s.get("leaked")}
    if leaked:
        print(f"\n{'!' * 78}\nGROUND-TRUTH LEAKAGE — {len(leaked)} of {len(runs)} run(s) "
              f"scored EXACTLY right on every image\n{'!' * 78}")
        for n, s in sorted(leaked.items()):
            print(f"  {n:18} {s['images']} images, {s['exact_matches']} exact, "
                  f"Dice {s['dice_mean'] if s['dice_mean'] is None else round(s['dice_mean'],3)}")
        print("  Counts that perfect did not come from segmentation. Anonymise the "
              "input filenames (scripts/anonymize_inputs.py) and re-run.")
        if not args.keep_leaked:
            print(f"  -> excluded from the statistics below (--keep-leaked to include)")
            runs = {n: s for n, s in runs.items() if not s.get("leaked")}

    by_arm = defaultdict(list)
    for name, s in runs.items():
        by_arm[base_arm(name)].append(s)

    METRICS = ["rmse", "mae", "dice_mean", "cost_usd"]
    print(f"\n{'=' * 78}\nPER-ARM SUMMARY   (mean +- SD over repeats)\n{'=' * 78}")
    print(f"{'arm':18}{'n':>3}" + "".join(f"{m:>18}" for m in METRICS))
    for arm in sorted(by_arm):
        row = f"{arm:18}{len(by_arm[arm]):>3}"
        for m in METRICS:
            mu, sd, n = agg([r[m] for r in by_arm[arm]])
            row += f"{('n/a' if mu is None else f'{mu:.3f} ± {sd:.3f}'):>18}"
        print(row)

    print(f"\n{'=' * 78}\n1. NOISE FLOOR — spread across repeats of a single arm\n{'=' * 78}")
    for arm in sorted(by_arm):
        if len(by_arm[arm]) < 2:
            continue
        print(f"  {arm}  (n={len(by_arm[arm])})")
        for m in METRICS:
            mu, sd, n = agg([r[m] for r in by_arm[arm]])
            if mu is None:
                continue
            mde = 2.8 * sd * math.sqrt(2 / n) if sd else 0.0
            print(f"     {m:12} mean {mu:8.3f}   SD {sd:7.3f}   "
                  f"smallest effect detectable at n={n}: {mde:.3f}")

    if "baseline" in by_arm and "all_off" in by_arm:
        print(f"\n{'=' * 78}\n2. TOTAL EFFECT — baseline vs all_off (the gate)\n{'=' * 78}")
        for m in METRICS:
            r = effect([x[m] for x in by_arm["baseline"]],
                       [x[m] for x in by_arm["all_off"]], m)
            if not r:
                continue
            verdict = "REAL (CI excludes 0)" if r["significant"] else "within noise"
            dtxt = "n/a" if r["d"] is None else f"{r['d']:.2f}"
            print(f"  {m:12} effect {r['effect']:+8.3f}   "
                  f"95% CI [{r['lo']:+.3f}, {r['hi']:+.3f}]   d {dtxt:>6}   {verdict}")

    # per-component effects, when those arms are present
    present = [c for c in REMOVABLE if by_arm.get(f"no_{c}") or by_arm.get(f"only_{c}")]
    if present:
        print(f"\n{'=' * 78}\n3. PER-COMPONENT EFFECTS\n{'=' * 78}")
        print(f"{'component':16}{'metric':10}{'LOO':>20}{'AOI':>20}   reading")
        for comp in present:
            for m in ("rmse", "dice_mean"):
                lo = effect([x[m] for x in by_arm.get("baseline", [])],
                            [x[m] for x in by_arm.get(f"no_{comp}", [])], m) \
                    if by_arm.get(f"no_{comp}") else None
                ai = effect([x[m] for x in by_arm.get(f"only_{comp}", [])],
                            [x[m] for x in by_arm.get("all_off", [])], m) \
                    if by_arm.get(f"only_{comp}") else None
                fmt = lambda r: "—" if not r else \
                    f"{r['effect']:+.3f}{'*' if r['significant'] else ' '}"
                read = ""
                if lo and ai:
                    L, A = lo["significant"], ai["significant"]
                    read = ("useful" if L and A else "redundant" if A and not L
                            else "needs others" if L and not A else "no effect")
                print(f"{comp:16}{m:10}{fmt(lo):>20}{fmt(ai):>20}   {read}")
        print("\n  * = 95% CI excludes zero")

    if args.out:
        fields = ["run", "base_arm"] + sorted({k for s in runs.values() for k in s})
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for name, s in sorted(runs.items()):
                w.writerow({"run": name, "base_arm": base_arm(name), **s})
        print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()

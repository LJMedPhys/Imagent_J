#!/usr/bin/env python3
"""Summarise a pooled component study as a LaTeX table (and plain text).

Every run is used, and n is reported per arm
--------------------------------------------
Unequal n across arms is handled by the statistics, not by discarding data.
Welch's t interval does not assume equal sample sizes or equal variances, and
this study has both problems: one arm's SD is four times another's.

Balancing was tried and was worse. Trimming every arm to three runs left the
`fast_mode` vs `baseline` contrast unresolved, while across all forty possible
three-run subsets the effect was positive in forty of forty (median +9.2 RMSE,
range +5.7 to +11.7) and cleared zero in twenty-four. The effect was never in
doubt; only the ability of three runs to resolve it was. Worse, sorting by run
name drew `baseline` entirely from a later batch and the other arms entirely
from the first, confounding batch with configuration — a problem the unbalanced
table does not have.

--per-arm N remains for a deliberate balanced table, but it is not the default
and the batch column is printed so that the confound above cannot recur
unnoticed.

Runs excluded before any of this:
  * leaked    — counts that matched ground truth on every image, i.e. read off
                the filename rather than measured (see anonymize_inputs.py)
  * truncated — fewer images than the run was given, so not a measurement of the
                same task

Effects are reported as differences of means with M oriented HIGHER IS BETTER,
so error metrics are negated and a positive number always means the first-named
arm won. A confidence interval containing zero means this design cannot
distinguish the arms — which is not the same as "no difference", and the caption
says so.

Usage
-----
    scripts/summary_table.py --csv study_task2_pooled.csv --per-arm 3
    scripts/summary_table.py --csv study_task2_pooled.csv --per-arm 3 --out table.tex
"""

import argparse
import csv
import math
import statistics as st
import sys

# metric -> (label, +1 if higher is better, decimal places)
METRICS = [
    ("rmse",      "RMSE (cells)",     -1, 2),
    ("mae",       "MAE (cells)",      -1, 2),
    ("dice_mean", "Dice",             +1, 3),
    ("cost_usd",  "Cost (USD)",       -1, 2),
]
ARM_LABEL = {"baseline": "baseline", "all\\_off": "all\\_off", "fast_mode": "fast\\_mode"}
# t(0.975, df) for the small dfs this design produces
TCRIT = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31,
         9: 2.26, 10: 2.23}


def fnum(row, key):
    v = row.get(key, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path, per_arm, min_images):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    kept, dropped = [], []
    for r in rows:
        n_img = fnum(r, "images") or 0
        if str(r.get("leaked", "")).strip().lower() == "true":
            dropped.append((r["run"], "leaked")); continue
        if min_images and n_img < min_images:
            dropped.append((r["run"], f"truncated ({int(n_img)} images)")); continue
        kept.append(r)

    by_arm = {}
    for r in kept:
        by_arm.setdefault(r["base_arm"], []).append(r)
    trimmed = {}
    for arm, rs in by_arm.items():
        rs = sorted(rs, key=lambda x: x["run"])
        if per_arm and len(rs) > per_arm:
            for extra in rs[per_arm:]:
                dropped.append((extra["run"], f"beyond --per-arm {per_arm}"))
            rs = rs[:per_arm]
        trimmed[arm] = rs
    return trimmed, dropped


def effect(a_vals, b_vals, sign):
    a = [v * sign for v in a_vals]
    b = [v * sign for v in b_vals]
    if len(a) < 2 or len(b) < 2:
        return None
    d = st.mean(a) - st.mean(b)
    va, vb = st.stdev(a) ** 2 / len(a), st.stdev(b) ** 2 / len(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return dict(d=d, lo=d, hi=d, sig=False, dz=0.0, df=0.0)
    df = (va + vb) ** 2 / ((va ** 2 / (len(a) - 1)) + (vb ** 2 / (len(b) - 1)))
    t = TCRIT.get(max(1, round(df)), 2.0)
    lo, hi = d - t * se, d + t * se
    pooled = math.sqrt((st.stdev(a) ** 2 + st.stdev(b) ** 2) / 2)
    return dict(d=d, lo=lo, hi=hi, sig=(lo * hi > 0),
                dz=(d / pooled if pooled else 0.0), df=df)


def latex(arms, order, contrasts, per_arm):
    esc = lambda s: s.replace("_", r"\_")
    L = []
    L.append(r"\begin{table}[htbp]")
    L.append(r"\centering")
    L.append(r"\caption{Cell-counting task: configurations compared over "
             r"independent repeat runs. Values are mean $\pm$ SD across runs; $n$ "
             r"differs by configuration and every available run is used rather than "
             r"trimming to a common $n$. Counting error (RMSE, MAE) is measured on "
             r"all 500 images; Dice is measured on the 33 images that carry "
             r"ground-truth masks, all of which are in focus.}")
    L.append(r"\label{tab:arm-summary}")
    L.append(r"\begin{tabular}{l c " + " ".join(["r"] * len(METRICS)) + "}")
    L.append(r"\toprule")
    L.append("Configuration & $n$ & " + " & ".join(lbl for _, lbl, _, _ in METRICS)
             + r" \\")
    L.append(r"\midrule")
    for arm in order:
        rs = arms.get(arm, [])
        cells = []
        for key, _lbl, _sgn, nd in METRICS:
            vals = [v for v in (fnum(r, key) for r in rs) if v is not None]
            cells.append(f"${st.mean(vals):.{nd}f} \\pm {st.stdev(vals):.{nd}f}$"
                         if len(vals) > 1 else
                         (f"${st.mean(vals):.{nd}f}$" if vals else "--"))
        L.append(f"{esc(arm)} & {len(rs)} & " + " & ".join(cells) + r" \\")
    L.append(r"\bottomrule")
    L.append(r"\end{tabular}")
    L.append(r"\end{table}")
    L.append("")

    L.append(r"\begin{table}[htbp]")
    L.append(r"\centering")
    L.append(r"\caption{Pairwise effects. Each value is a difference of means "
             r"oriented so that a positive number favours the first configuration; "
             r"error metrics are negated accordingly. Intervals are Welch's "
             r"$t$ intervals, which assume neither equal sample sizes nor equal "
             r"variances --- both of which are violated here, the largest "
             r"configuration SD being several times the smallest. Degrees of freedom "
             r"follow the Welch--Satterthwaite approximation and are given per row. "
             r"$d$ is the difference in pooled standard deviations. An interval "
             r"containing zero means the design cannot separate the two "
             r"configurations at this sample size, which is weaker than evidence of "
             r"no difference.}")
    L.append(r"\label{tab:effects}")
    L.append(r"\begin{tabular}{l l r r r r l}")
    L.append(r"\toprule")
    L.append(r"Contrast & Metric & Effect & \multicolumn{1}{c}{95\% CI} & $d$ & "
             r"df & Verdict \\")
    L.append(r"\midrule")
    for title, a, b in contrasts:
        first = True
        na, nb = len(arms.get(a, [])), len(arms.get(b, []))
        title = f"{title} ($n={na}$ vs ${nb}$)"
        for key, lbl, sgn, nd in METRICS:
            av = [v for v in (fnum(r, key) for r in arms.get(a, [])) if v is not None]
            bv = [v for v in (fnum(r, key) for r in arms.get(b, [])) if v is not None]
            e = effect(av, bv, sgn)
            if not e:
                continue
            name = esc(title) if first else ""
            first = False
            L.append(f"{name} & {lbl} & ${e['d']:+.{nd}f}$ & "
                     f"$[{e['lo']:+.{nd}f},\\ {e['hi']:+.{nd}f}]$ & "
                     f"${e['dz']:+.2f}$ & ${e['df']:.1f}$ & "
                     + (r"\textbf{resolved}" if e["sig"] else "within noise")
                     + r" \\")
        L.append(r"\addlinespace")
    if L[-1] == r"\addlinespace":
        L.pop()
    L.append(r"\bottomrule")
    L.append(r"\end{tabular}")
    L.append(r"\end{table}")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True, help="the pooled per-run metrics CSV")
    p.add_argument("--per-arm", type=int, default=0,
                   help="keep only the first N runs of each arm. NOT recommended: "
                        "Welch's correction already handles unequal n, and trimming "
                        "discards real measurements — see the module docstring.")
    p.add_argument("--min-images", type=int, default=500,
                   help="drop runs that scored fewer images than this (0 to keep all)")
    p.add_argument("--arms", nargs="+",
                   default=["baseline", "all_off", "fast_mode"],
                   help="arms to include, in table order")
    p.add_argument("--out", help="write the LaTeX here as well as printing it")
    args = p.parse_args()

    arms, dropped = load(args.csv, args.per_arm, args.min_images)
    order = [a for a in args.arms if a in arms]
    missing = [a for a in args.arms if a not in arms]

    print("excluded runs:", file=sys.stderr)
    for run, why in dropped:
        print(f"   {run:34} {why}", file=sys.stderr)
    for arm in order:
        print(f"   {arm:12} n={len(arms[arm])}: "
              f"{', '.join(r['run'] for r in arms[arm])}", file=sys.stderr)
    if missing:
        print(f"   !! not present in the CSV: {', '.join(missing)}", file=sys.stderr)
    print(file=sys.stderr)

    contrasts = []
    if "baseline" in arms and "all_off" in arms:
        contrasts.append(("baseline vs all_off", "baseline", "all_off"))
    if "fast_mode" in arms and "baseline" in arms:
        contrasts.append(("fast_mode vs baseline", "fast_mode", "baseline"))

    tex = latex(arms, order, contrasts, args.per_arm or "all")
    print(tex)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(tex + "\n")
        print(f"\n-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare WHAT each configuration actually did, not just how well it scored.

Every run's result.json carries an ordered log of its tool calls at

    metadata.usage_report.conversation.queries[0].tool_call_log

one entry per call: {tool, status, detail, code_preview}. That is the run's
method — which tools it reached for, in what order, how often it had to retry,
and what it never touched at all. Two configurations can land on the same RMSE
by completely different routes, and the score alone cannot tell you that.

What it reports
---------------
1. SHAPE          calls, distinct tools, failures and soft errors per arm.
2. OPENING        the first N calls of each arm side by side. Runs diverge
                  early: how a run orients itself before writing any code is
                  usually the clearest difference between configurations.
3. TOOL USE       a per-tool matrix across arms, so a tool one arm leans on and
                  another never calls is visible at a glance.
4. EXCLUSIVE      tools used by exactly one arm — the sharpest summary of what
                  a capability actually changed in behaviour.

Repeats of the same arm are pooled, and per-arm figures are averaged over them,
because a single run's trace is as noisy as its score.

Usage
-----
    scripts/compare_traces.py --results ./study_task2 ./study_results_ext2
    scripts/compare_traces.py --results ./ablation_01 --opening 20
"""

import argparse
import collections
import json
import os
import re
import statistics as st
import sys


def base_arm(name):
    return re.sub(r"__r\d+$", "", name.split("/")[-1])


def load_trace(path):
    """(ordered tool-call entries, arm label) from one result.json."""
    try:
        d = json.load(open(path))
    except Exception:
        return None
    md = d.get("metadata") or {}
    conv = ((md.get("usage_report") or {}).get("conversation") or {})
    queries = conv.get("queries") or []
    log = []
    for q in queries:
        log.extend(q.get("tool_call_log") or [])
    if not log:
        # Older runs recorded only a count. Say so rather than showing an arm
        # with zero calls, which reads as "did nothing".
        return {"entries": [], "count_only": md.get("tool_calls")}
    return {"entries": log, "count_only": None}


def collect(roots):
    runs = {}
    for root in roots:
        if os.path.isfile(root) and root.endswith(".json"):
            runs[root] = load_trace(root)
            continue
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d, "result.json")
            if os.path.isfile(p):
                tag = f"{os.path.basename(os.path.normpath(root))}/{d}" \
                      if len(roots) > 1 else d
                runs[tag] = load_trace(p)
    return {k: v for k, v in runs.items() if v}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", required=True, nargs="+",
                   help="result roots, or individual result.json files")
    p.add_argument("--opening", type=int, default=12,
                   help="how many of the first calls to show per arm (default 12)")
    p.add_argument("--arms", nargs="+", help="restrict to these arms, in this order")
    p.add_argument("--out", help="write the per-tool matrix as CSV here")
    args = p.parse_args()

    runs = collect(args.results)
    if not runs:
        sys.exit("no result.json with a usable trace under: " + ", ".join(args.results))

    by_arm = collections.defaultdict(list)
    for name, tr in runs.items():
        by_arm[base_arm(name)].append((name, tr))
    arms = args.arms or sorted(by_arm)
    arms = [a for a in arms if a in by_arm]

    no_trace = [n for n, t in runs.items() if t["count_only"] is not None]
    if no_trace:
        print(f"{len(no_trace)} run(s) predate the tool_call_log and report only a "
              f"count; excluded from the trace comparison:")
        for n in no_trace[:5]:
            print(f"   {n}")
        print()

    print("=" * 78)
    print("1. SHAPE OF THE RUN   (mean over repeats)")
    print("=" * 78)
    print(f"{'arm':18}{'runs':>5}{'calls':>9}{'distinct':>10}{'errors':>8}{'soft':>7}")
    for a in arms:
        traces = [t for _n, t in by_arm[a] if t["entries"]]
        if not traces:
            continue
        calls = [len(t["entries"]) for t in traces]
        distinct = [len({e.get("tool") for e in t["entries"]}) for t in traces]
        errs = [sum(1 for e in t["entries"]
                    if str(e.get("status", "")).lower() not in ("ok", "", "none"))
                for t in traces]
        soft = [sum(1 for e in t["entries"] if e.get("detail")) for t in traces]
        print(f"{a:18}{len(traces):>5}{st.mean(calls):>9.1f}{st.mean(distinct):>10.1f}"
              f"{st.mean(errs):>8.1f}{st.mean(soft):>7.1f}")

    print()
    print("=" * 78)
    print(f"2. HOW EACH RUN OPENS   (first {args.opening} calls of one representative run)")
    print("=" * 78)
    for a in arms:
        traces = [(n, t) for n, t in by_arm[a] if t["entries"]]
        if not traces:
            continue
        name, tr = traces[0]
        print(f"\n  {a}   [{name}]")
        for i, e in enumerate(tr["entries"][:args.opening], start=1):
            bad = "" if str(e.get("status", "ok")).lower() == "ok" else \
                  f"  <-- {e.get('status')}"
            print(f"     {i:3d}. {e.get('tool')}{bad}")

    print()
    print("=" * 78)
    print("3. TOOL USE   (mean calls per run)")
    print("=" * 78)
    tools = sorted({e.get("tool") for _a in arms for _n, t in by_arm[_a]
                    for e in t["entries"]}, key=lambda x: (x or ""))
    matrix = {}
    for a in arms:
        traces = [t for _n, t in by_arm[a] if t["entries"]]
        if not traces:
            continue
        per = []
        for t in traces:
            c = collections.Counter(e.get("tool") for e in t["entries"])
            per.append(c)
        matrix[a] = {tool: st.mean([c.get(tool, 0) for c in per]) for tool in tools}
    cols = [a for a in arms if a in matrix]
    print(f"{'tool':34}" + "".join(f"{a[:13]:>14}" for a in cols))
    for tool in sorted(tools, key=lambda x: -max(matrix[a].get(x, 0) for a in cols)):
        row = "".join(f"{matrix[a].get(tool, 0):>14.1f}" for a in cols)
        print(f"{(tool or '?'):34}{row}")

    print()
    print("=" * 78)
    print("4. USED BY ONLY ONE CONFIGURATION")
    print("=" * 78)
    for tool in tools:
        users = [a for a in cols if matrix[a].get(tool, 0) > 0]
        if len(users) == 1:
            print(f"   {tool:34} only {users[0]}  ({matrix[users[0]][tool]:.1f}/run)")

    if args.out:
        import csv
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["tool"] + cols)
            for tool in tools:
                w.writerow([tool] + [f"{matrix[a].get(tool, 0):.3f}" for a in cols])
        print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()

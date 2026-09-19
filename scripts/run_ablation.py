#!/usr/bin/env python3
"""Leave-one-out ablation runner: one `docker compose run` per arm, no human.

Each arm is the full system with exactly ONE capability removed, plus an all-on
baseline. Six switches therefore give seven arms, not the 64 a full factorial
would need — the difference between roughly seven hours and three days.

An arm is described entirely by a generated `imagentj_config.yaml`; nothing is
ever commented in or out of the source. `config.py` resolves `$IMAGENTJ_CONFIG`
before anything else, so pointing that at the generated file is all it takes.

The prompt comes from `instruction.txt` in the arm's output directory, which is
what the existing benchmark auto-pilot already reads (`benchmark_gui_hooks`).
Nothing here needs a person: the container starts, works, writes `result.json`
and exits.

LEARNED MEMORY IS SHARED AND CARRIED FORWARD ON PURPOSE
------------------------------------------------------
`--learned-root` is one directory reused by every arm, so what one run learns is
available to the next — the way the system actually behaves in use. Start it
empty for the first study and it accumulates from there. Pass a fresh path (or
`--fresh-learned`) when an arm must start from nothing.

That makes arms ORDER-DEPENDENT, which is a real limitation and the reason the
order actually run is recorded in `summary.json`. If you later want arms to be
independent, give each one its own `--learned-root`.

Usage
-----
    scripts/run_ablation.py --instruction task.txt --input-dir ./images \\
                            --results ./ablation_results

    # just one arm, e.g. re-run the baseline
    scripts/run_ablation.py ... --only baseline
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Every switch, and the arm that removes it. "baseline" removes nothing.
# Capabilities the baseline HAS and each arm removes -> "no_<x>".
REMOVABLE = ["rag", "concepts", "code_memory", "discovery", "vlm"]

# Settings the baseline does NOT have and an arm turns ON. Named for what the arm
# DOES, not for a removal: the baseline runs in advanced mode, so the fast-mode arm
# switches fast mode on. Calling it "no_fast_mode" read exactly backwards — the arm
# with that name was the one running in quick mode.
ADDITIVE = {"fast_mode": {"fast_mode": True}}

SWITCHES = REMOVABLE + list(ADDITIVE)


def arms(only=None, baseline="last"):
    """The seven arms, in run order.

    Order is not cosmetic while the learned store is SHARED: every arm writes to
    it, so a later arm starts with more memory than an earlier one. Putting the
    baseline last therefore gives it the richest store of all, and any advantage
    it shows is then partly ablation and partly running-order. Use
    --isolate-learned to remove the confound entirely.
    """
    out = [(f"no_{s}", {s: False}) for s in REMOVABLE]
    out += [(name, dict(ov)) for name, ov in ADDITIVE.items()]
    out = ([("baseline", {})] + out) if baseline == "first" else (out + [("baseline", {})])
    if only:
        wanted = set(only)
        out = [a for a in out if a[0] in wanted]
        missing = wanted - {a[0] for a in out}
        if missing:
            sys.exit(f"unknown arm(s): {', '.join(sorted(missing))}")
    return out


def render_config(base_path: Path, overrides: dict) -> str:
    """The shipped config with this arm's switches applied.

    Edited as TEXT rather than rewritten from a parsed dict, so the file keeps
    its comments — the generated config is the record of what an arm was, and a
    bare dump of keys is much harder to read six weeks later.
    """
    # (key, section) — the SECTION matters. "vlm" appears three times in this file:
    # the model name under `models:`, its thinking budget under `reasoning_effort:`,
    # and the on/off flag under `agents:`. Matching on the key alone rewrote all
    # three, so the no_vlm arm would have run with a corrupted models block.
    TARGET = {
        "rag":         ("rag",         "features"),
        "concepts":    ("concepts",    "features"),
        "code_memory": ("code_memory", "features"),
        "discovery":   ("discovery",   "features"),
        "vlm":         ("vlm",         "agents"),
    }
    lines = base_path.read_text(encoding="utf-8").split("\n")

    def section_of(index: int) -> str:
        """The nearest top-level `key:` above this line."""
        for j in range(index, -1, -1):
            l = lines[j]
            if l and not l.startswith((" ", "\t", "#")) and l.rstrip().endswith(":"):
                return l.split(":", 1)[0].strip()
        return ""

    for key, value in overrides.items():
        if key == "fast_mode":
            # fast_mode=True  -> quick mode (the arm)
            # fast_mode=False -> advanced (the baseline; also what the file ships as)
            target = "quick" if value else "advanced"
            for i, l in enumerate(lines):
                if l.startswith("  mode:") and section_of(i) == "features":
                    lines[i] = f"  mode:        {target}".ljust(30) + \
                               f"# ablation arm: fast mode {'ON' if value else 'off'}"
            continue
        want_key, want_section = TARGET[key]
        hits = 0
        for i, l in enumerate(lines):
            stripped = l.strip()
            if not stripped.startswith(f"{want_key}:"):
                continue
            if section_of(i) != want_section:
                continue
            comment = l.split("#", 1)[1].strip() if "#" in l else ""
            indent = l[:len(l) - len(l.lstrip())]
            body = f"{indent}{want_key}:".ljust(len(indent) + 14) + \
                   ("true" if value else "false")
            lines[i] = f"{body.ljust(30)}# {comment}" if comment else body
            hits += 1
        if hits != 1:
            # Never guess here: a miss means the arm silently ran unablated, and a
            # double hit means something else was overwritten. Both invalidate it.
            raise SystemExit(
                f"config edit for {key!r} matched {hits} line(s) under "
                f"{want_section!r} — expected exactly 1. Refusing to generate a "
                f"config that may not mean what the arm name says."
            )
    return "\n".join(lines)


def run_arm(name, overrides, args, learned_root: Path) -> dict:
    out_dir = args.results / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # The auto-pilot reads the prompt from here.
    shutil.copy(args.instruction, out_dir / "instruction.txt")

    cfg_path = out_dir / "imagentj_config.yaml"
    cfg_path.write_text(render_config(args.base_config, overrides), encoding="utf-8")

    env = {
        "IMAGENTJ_CONFIG":       "/benchmark/output/imagentj_config.yaml",
        "BENCHMARK_MODE":        "true",
        "BENCHMARK_INTERACTIVE": "false",
        "BENCHMARK_INPUT_DIR":   "/benchmark/input",
        "BENCHMARK_OUTPUT_DIR":  "/benchmark/output",
        "LEARNED_ROOT":          "/app/data/learned",
    }
    # The -f files must come BEFORE the subcommand, and every one of them that the
    # normal launch uses has to be here too: on the Spark the override carries the
    # GPU reservation, the HOST_UID build args and the unattended settings, so
    # leaving it out would quietly run a differently-configured container.
    cmd = ["docker", "compose"]
    for f in args.compose_file:
        cmd += ["-f", str(f)]
    cmd += ["run", "--rm"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "-v", f"{args.input_dir.resolve()}:/benchmark/input:ro",
        "-v", f"{out_dir.resolve()}:/benchmark/output",
        "-v", f"{learned_root.resolve()}:/app/data/learned",
        args.service,
    ]

    print(f"\n{'=' * 72}\n  ARM: {name}   "
          f"({', '.join(f'{k}={v}' for k, v in overrides.items()) or 'nothing removed'})"
          f"\n{'=' * 72}")
    print("  " + " ".join(cmd))
    if args.dry_run:
        return {"arm": name, "skipped": "dry-run"}

    started = time.time()
    proc = subprocess.run(cmd, cwd=args.repo)
    took = time.time() - started

    result_file = out_dir / "result.json"
    record = {
        "arm": name,
        "overrides": overrides,
        "exit_code": proc.returncode,
        "seconds": round(took, 1),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result_json": result_file.exists(),
    }
    if result_file.exists():
        try:
            record["result"] = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception as exc:
            record["result_error"] = str(exc)
    else:
        # Worth saying loudly: an arm with no result.json produced no measurement,
        # and a study that quietly skips it is comparing different sample sizes.
        print(f"  !! {name}: no result.json — this arm produced NO measurement")
    print(f"  {name}: exit={proc.returncode} in {took / 60:.1f} min")
    return record


def main():
    repo = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--instruction", type=Path, required=True, help="the task prompt (a .txt)")
    p.add_argument("--input-dir", type=Path, required=True, help="folder of input images")
    p.add_argument("--results", type=Path, required=True, help="where arm folders are written")
    p.add_argument("--base-config", type=Path, default=repo / "imagentj_config.yaml")
    p.add_argument("--learned-root", type=Path, default=None,
                   help="shared learned-memory store (default: <results>/learned)")
    p.add_argument("--fresh-learned", action="store_true",
                   help="empty the learned store before starting")
    p.add_argument("--service", default="imagentj", help="docker compose service name")
    p.add_argument("--compose-file", "-f", type=Path, action="append", default=None,
                   help="compose file, repeatable and order-sensitive. Defaults to "
                        "docker-compose.yml plus docker-compose.spark.yml when that "
                        "override exists — the same pair the normal launch uses.")
    p.add_argument("--only", nargs="+", help="run only these arms (e.g. baseline no_rag)")
    p.add_argument("--baseline", choices=("first", "last"), default="last",
                   help="where the all-on baseline runs (default: last)")
    p.add_argument("--isolate-learned", action="store_true",
                   help="give every arm its OWN copy of the learned store, so arms "
                        "cannot see each other's memory and run order stops mattering")
    p.add_argument("--dry-run", action="store_true", help="print the commands and stop")
    args = p.parse_args()
    args.repo = repo

    if not args.compose_file:
        args.compose_file = [repo / "docker-compose.yml"]
        spark = repo / "docker-compose.spark.yml"
        if spark.is_file():
            args.compose_file.append(spark)

    for path in (args.instruction, args.input_dir, args.base_config, *args.compose_file):
        if not path.exists():
            sys.exit(f"not found: {path}")

    learned = args.learned_root or (args.results / "learned")
    if args.fresh_learned and learned.exists():
        shutil.rmtree(learned)
        print(f"learned store emptied: {learned}")
    learned.mkdir(parents=True, exist_ok=True)

    selected = arms(args.only, args.baseline)
    print(f"{len(selected)} arm(s): {', '.join(n for n, _ in selected)}")
    print("learned store: " + (f"{learned} (a private COPY per arm)"
          if args.isolate_learned else f"{learned} (SHARED, carried forward)"))

    records = []
    for name, overrides in selected:
        if args.isolate_learned:
            # A private copy per arm, seeded from the same starting store, so no arm
            # can see what another learned and running order stops mattering.
            arm_learned = args.results / name / "learned"
            if arm_learned.exists():
                shutil.rmtree(arm_learned)
            shutil.copytree(learned, arm_learned)
        else:
            arm_learned = learned
        records.append(run_arm(name, overrides, args, arm_learned))

    summary = args.results / "summary.json"
    summary.write_text(json.dumps({
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instruction": str(args.instruction),
        "learned_root": str(learned),
        "learned_isolated": bool(args.isolate_learned),
        "note": ("each arm had its own copy of the learned store; order does not matter"
                 if args.isolate_learned else
                 "arms SHARE one learned store and are order-dependent; "
                 "the order below is the order run"),
        "arms": records,
    }, indent=2), encoding="utf-8")
    print(f"\nsummary: {summary}")

    missing = [r["arm"] for r in records if not r.get("result_json") and "skipped" not in r]
    if missing:
        print(f"arms with NO result.json: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

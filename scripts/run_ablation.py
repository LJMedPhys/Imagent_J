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
import signal
import subprocess
import sys
import threading
import time
import traceback
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


def _log_ref(log_path: Path, results_root: Path):
    """Where this arm's container log lives, relative to the results root if possible.

    Defensive on purpose. This is bookkeeping for summary.json, computed AFTER the
    arm has finished and its real outputs are on disk — so nothing it does may raise.
    An earlier version compared a relative path against a resolved one, and the
    ValueError threw away a completed arm and stopped the whole study.
    """
    try:
        if not log_path.exists():
            return None
        return str(log_path.resolve().relative_to(results_root.resolve()))
    except Exception:
        try:
            return str(log_path)
        except Exception:
            return None


def _write_summary(args, learned: Path, records: list) -> Path:
    """Write summary.json. Called after every arm, not only at the end.

    A study is hours long, and until now its only record appeared after the last
    arm — so anything that ended the run early left no summary at all, even for the
    arms that had finished cleanly.
    """
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
    return summary


def _writable(path: Path) -> Path:
    """Create a directory the CONTAINER can write to.

    It runs as `imagentj`, whose uid is baked at BUILD time from HOST_UID
    (default 1000). If the image was built with a different uid than the host
    user running this script, every bind mount is read-only to it — which is the
    "permission denied on /benchmark/output" a run hits. These are local result
    folders, so widening them beats rebuilding the image to match.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o777)
    except OSError:
        pass
    return path


# Learned-memory files that are ACCUMULATED run history, emptied for every arm so
# no study starts with what a previous one happened to learn. CORE is included at
# the user's instruction: every arm begins with no learned floor at all.
_EMPTY_FOR_EVERY_ARM = (
    "learned/pitfalls/CORE.Groovy.md", "learned/pitfalls/CORE.Python.md",
    "learned/recipes/CORE.Groovy.md",  "learned/recipes/CORE.Python.md",
    "learned/pitfalls/Groovy.md",      "learned/pitfalls/Python.md",
    "learned/recipes/Groovy.md",       "learned/recipes/Python.md",
    "learned/log.md",
)


def seed_arm_data(arm_dir: Path, repo: Path) -> None:
    """Give the arm a pristine /app/data, then empty the learned floor.

    An EMPTY /app/data is not a clean slate — `data/` ships content the app reads:
    `environment/container_snapshot.md` (699 lines) is what check_environment
    returns, and `learned/concepts/library.md` (723 lines) is the FIXED, curated
    concept library that recall_concepts retrieves from. Starting an arm with
    neither silently disables the concepts feature in EVERY arm, which would make
    the no_concepts comparison measure nothing, and leaves the agent unable to
    discover what is installed.

    So seed from the git-TRACKED data/ at HEAD — the shipped state, not the working
    copy, which carries whatever previous runs accumulated — and then blank only the
    learned floor. The concept library and the container snapshot stay.
    """
    tar = subprocess.run(["git", "archive", "HEAD", "data"], cwd=repo,
                         capture_output=True)
    if tar.returncode != 0:
        sys.exit(f"could not read the tracked data/ skeleton: "
                 f"{tar.stderr.decode('utf-8', 'replace')[:200]}")
    extract = subprocess.run(["tar", "-x", "--strip-components=1", "-C", str(arm_dir)],
                             input=tar.stdout, capture_output=True)
    if extract.returncode != 0:
        sys.exit(f"could not unpack the data/ skeleton: "
                 f"{extract.stderr.decode('utf-8', 'replace')[:200]}")

    emptied = 0
    for rel in _EMPTY_FOR_EVERY_ARM:
        f = arm_dir / rel
        if f.exists():
            f.write_text("", encoding="utf-8")
            emptied += 1
    # Directories AND files. Everything here is created by the HOST user, while the
    # container runs as `imagentj` — a uid baked from HOST_UID at image build time,
    # and not necessarily this one. Write permission on a directory lets that user
    # CREATE files in it, but never APPEND to an existing file it does not own.
    #
    # Chmodding only directories therefore produced a store the container could add
    # to but not update, and the failure was silent in the worst way: learned_memory
    # writes a recipe's CODE to a directory it creates itself (succeeds), then
    # appends the index entry to a seeded .md (EACCES). The code file was orphaned
    # with nothing pointing at it, `recall` reads only the index, and so returned
    # empty for every query in all 21 arms of the first three studies — including the
    # baselines, which made the no_code_memory comparison measure nothing at all.
    _writable(arm_dir)
    for sub in arm_dir.rglob("*"):
        try:
            sub.chmod(0o777 if sub.is_dir() else 0o666)
        except OSError:
            pass
    print(f"    seeded from tracked data/ (concept library + container snapshot kept; "
          f"{emptied} learned file(s) emptied)")


def run_arm(name, overrides, args, learned_root: Path,
            qdrant_src: Path | None = None) -> dict:
    # ONE directory per arm, serving as both /app/data and /benchmark/output. The
    # app needs /app/data for projects, chats and checkpoints, but nothing requires
    # it to be ./data — pointing it here means deliverables are written straight
    # where they belong instead of depending on the collector to copy them out.
    #
    # It also stops arms colliding: they all shared ./data before, so seven runs of
    # one task reused the same workspace name and overwrote each other, leaving
    # three project folders for seven arms.
    out_dir = _writable(args.results / name)
    seed_arm_data(out_dir, args.repo)

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
    # Two caps inside the container, both derived from --arm-timeout so there is one
    # knob. They exist because `docker rm -f` from out here is the worst way for an arm
    # to end: it produces no result.json, so the arm contributes nothing to the study
    # even when the agent had already done most of the work. A container that ends
    # ITSELF writes its numbers down first.
    #
    # Every derived value is CLAMPED POSITIVE. Subtracting a fixed margin from a small
    # --arm-timeout produced negatives, and a negative is not a small budget — it is a
    # different behaviour: the container reads DEADLINE <= 0 as "watchdog disabled",
    # and a negative SCRIPT_MAX makes every script fail its ceiling test on the first
    # check, reinstating the kill-a-working-script bug. Both fail silently.
    script_timeout = max(60, int(args.script_timeout * 60))
    silent_timeout = max(60, int(args.silent_timeout * 60))
    if args.arm_timeout:
        arm_seconds = int(args.arm_timeout * 60)
        # Comfortably inside the outer kill, so the self-ending path always wins.
        env["IMAGENTJ_BENCHMARK_DEADLINE"] = str(max(120, arm_seconds - 300))
        # A script still producing output may use the whole arm; the arm deadline is
        # the real budget, so there is no reason for a second, tighter ceiling.
        script_max = max(120, arm_seconds - 360)
        env["IMAGENTJ_BENCHMARK_SCRIPT_MAX"] = str(script_max)
        # A cap above the ceiling would never be reached, so the reprieve logic that
        # keeps a working script alive would never run at all.
        script_timeout = min(script_timeout, script_max)
    env["IMAGENTJ_BENCHMARK_SCRIPT_TIMEOUT"] = str(script_timeout)
    env["IMAGENTJ_BENCHMARK_SILENT_TIMEOUT"] = str(silent_timeout)
    env["IMAGENTJ_BENCHMARK_HEARTBEAT"] = str(max(5, int(args.heartbeat)))
    # The -f files must come BEFORE the subcommand, and every one of them that the
    # normal launch uses has to be here too: on the Spark the override carries the
    # GPU reservation, the HOST_UID build args and the unattended settings, so
    # leaving it out would quietly run a differently-configured container.
    cmd = ["docker", "compose"]
    for f in args.compose_file:
        cmd += ["-f", str(f)]
    container = f"imagentj_abl_{name}"
    cmd += ["run", "--rm", "--name", container]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "-v", f"{args.input_dir.resolve()}:/benchmark/input:ro",
        "-v", f"{out_dir.resolve()}:/benchmark/output",
        "-v", f"{learned_root.resolve()}:/app/data/learned",
        args.service,
    ]

    # IMAGENTJ_APP_DATA_DIR is a COMPOSE-FILE variable — `${IMAGENTJ_APP_DATA_DIR:-./data}`
    # in the volumes block — interpolated when compose parses the file, so it must be in
    # the environment of the `docker compose` PROCESS. Passing it with -e would set it
    # inside the container and leave the mount pointing at ./data.
    run_env = {**os.environ, "IMAGENTJ_APP_DATA_DIR": str(out_dir.resolve())}

    # Same trick for the vector store, and for two reasons. Qdrant in local mode takes
    # an EXCLUSIVE LOCK, so concurrent arms sharing ./qdrant_data simply cannot both
    # start — this is what makes --parallel possible at all. And even run sequentially
    # the store is written during a run, so one arm's ingests were reaching the next;
    # isolating it removes a contamination channel that had nothing to do with the
    # feature being ablated.
    #
    # The copy is NOT optional-and-empty: the store holds the ingested RAG corpus, so
    # an empty one would silently disable retrieval in every arm — the exact class of
    # bug that made the concept library matter in seed_arm_data. ~180 MB, seconds.
    if qdrant_src is not None:
        arm_qdrant = out_dir / "qdrant"
        if arm_qdrant.exists():
            shutil.rmtree(arm_qdrant)
        shutil.copytree(qdrant_src, arm_qdrant)
        for sub in arm_qdrant.rglob("*"):
            try:
                sub.chmod(0o777 if sub.is_dir() else 0o666)
            except OSError:
                pass
        _writable(arm_qdrant)
        run_env["IMAGENTJ_QDRANT_DIR"] = str(arm_qdrant.resolve())

    print(f"\n{'=' * 72}\n  ARM: {name}   "
          f"({', '.join(f'{k}={v}' for k, v in overrides.items()) or 'nothing removed'})"
          f"\n{'=' * 72}")
    print("  " + " ".join(cmd))
    if args.dry_run:
        return {"arm": name, "skipped": "dry-run"}

    started = time.time()
    timed_out = False
    # Every line the container prints is ALSO written next to that arm's results.
    # Until now it existed only in terminal scrollback, so a dropped ssh session took
    # the entire diagnostic record with it — and the heartbeats, stack dumps and
    # shutdown trace are the only way to explain an arm after the fact.
    log_path = out_dir / "container.log"
    try:
        proc = subprocess.Popen(cmd, cwd=args.repo, env=run_env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except Exception as exc:
        print(f"  !! {name}: could not start the container: {exc}")
        return {"arm": name, "overrides": overrides, "error": str(exc)}

    def _tee():
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                if args.parallel > 1:
                    continue          # interleaved arms are unreadable; the file has it
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except Exception:
                    # The terminal went away (ssh dropped). The file is the record
                    # that matters; losing the echo must not kill the study.
                    pass

    tee = threading.Thread(target=_tee, name=f"tee-{name}", daemon=True)
    tee.start()

    try:
        returncode = proc.wait(timeout=args.arm_timeout * 60 if args.arm_timeout else None)
        tee.join(timeout=15)
    except subprocess.TimeoutExpired:
        # Killing the compose CLIENT does not stop the container it started, so the
        # arm would keep running and the next one would contend for the same shared
        # mounts. Remove it by name — which is why the run is named at all.
        timed_out = True
        returncode = None
        print(f"  !! {name}: exceeded {args.arm_timeout} min — killing {container}")
        subprocess.run(["docker", "rm", "-f", container],
                       cwd=args.repo, capture_output=True)
        try:
            proc.kill()
        except Exception:
            pass
        tee.join(timeout=15)
    took = time.time() - started

    result_file = out_dir / "result.json"
    record = {
        "arm": name,
        "overrides": overrides,
        "exit_code": returncode,
        "timed_out": timed_out,
        "seconds": round(took, 1),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result_json": result_file.exists(),
        "container_log": _log_ref(log_path, args.results),
    }
    if result_file.exists():
        try:
            record["result"] = json.loads(result_file.read_text(encoding="utf-8"))
            # A provisional sentinel means the collect was cut short — the file is
            # there, so `result_json` is True, but the arm is NOT a clean measurement
            # and must not be read as one.
            if record["result"].get("metadata", {}).get("provisional"):
                record["partial"] = True
                print(f"  !! {name}: result.json is PROVISIONAL — output collection "
                      f"was cut short, treat this arm as partial")
        except Exception as exc:
            record["result_error"] = str(exc)
    else:
        # Worth saying loudly: an arm with no result.json produced no measurement,
        # and a study that quietly skips it is comparing different sample sizes.
        print(f"  !! {name}: no result.json — this arm produced NO measurement")
    print(f"  {name}: exit={returncode}{' TIMED OUT' if timed_out else ''} in {took / 60:.1f} min")
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
    p.add_argument("--parallel", type=int, default=1, metavar="N",
                   help="run N arms at once (default: 1). Arms are LLM-bound — model "
                        "thinking is ~99%% of each arm's wall clock — so this scales "
                        "nearly linearly. 2-3 is sensible; each arm still wants the "
                        "GPU for its segmentation steps. Requires --isolate-learned.")
    p.add_argument("--isolate-qdrant", action="store_true",
                   help="give every arm its own COPY of the vector store even when "
                        "running sequentially. Implied by --parallel > 1, which needs "
                        "it (Qdrant takes an exclusive lock). Worth it on its own: the "
                        "shared store is written during a run, so one arm's ingests "
                        "otherwise reach the next.")
    p.add_argument("--qdrant-root", type=Path, default=None,
                   help="the vector store to copy per arm (default: <repo>/qdrant_data)")
    p.add_argument("--arm-timeout", type=float, default=60,
                   help="minutes before an arm is killed and the study moves on "
                        "(0 = wait for ever). One wedged arm should not cost the "
                        "whole run. The container arms its own deadline 5 min inside "
                        "this, so it can still write result.json before being killed. "
                        "60 rather than 90 because the script cap is now silence-based: "
                        "a working arm is no longer at risk of the deadline, while a "
                        "stalled one used to burn the full 90 min for no measurement.")
    p.add_argument("--script-timeout", type=float, default=30,
                   help="minutes after which one script starts being CHECKED for "
                        "progress (default: 30). Passing it is not fatal — a script "
                        "still writing output keeps running.")
    p.add_argument("--silent-timeout", type=float, default=10,
                   help="minutes of NO output, past --script-timeout, that count as "
                        "stuck and get the script terminated (default: 10). This is "
                        "what actually kills a script; the wall clock only decides "
                        "when to start asking.")
    p.add_argument("--heartbeat", type=float, default=60,
                   help="seconds between 'still waiting' lines in the container log "
                        "while a script runs (default: 60). These are what tell a slow "
                        "run from a wedged one without attaching to the container.")
    p.add_argument("--dry-run", action="store_true", help="print the commands and stop")
    args = p.parse_args()
    args.repo = repo

    # Resolve the results root ONCE, here. `--results ./ablation_02` otherwise stays
    # relative while individual call sites resolve it, and mixing the two forms is
    # what made a path comparison blow up after an arm had already succeeded. It also
    # matters that the absolute form is what reaches docker: these become bind-mount
    # sources, and compose is run with cwd=repo, not from where you typed the command.
    if args.parallel < 1:
        sys.exit("--parallel must be at least 1")
    if args.parallel > 1 and not args.isolate_learned:
        # Concurrent arms writing one learned store would contaminate each other and
        # race on the same files — the very thing --isolate-learned exists to prevent.
        sys.exit("--parallel > 1 requires --isolate-learned, otherwise the arms share "
                 "one writable learned store and contaminate each other.")

    args.results = args.results.resolve()
    if args.learned_root:
        args.learned_root = args.learned_root.resolve()

    # An ablation is hours long and is nearly always started over ssh. A dropped
    # connection SIGHUPs the whole process group, which used to end the study
    # mid-arm with no result and a half-written output tree. Ignoring it means the
    # run continues to completion; the per-arm container.log is then the record,
    # since the echo to a dead terminal is silently discarded.
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass                       # not POSIX, or not on the main thread

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
    _writable(learned)

    selected = arms(args.only, args.baseline)
    print(f"{len(selected)} arm(s): {', '.join(n for n, _ in selected)}")
    print("learned store: " + (f"{learned} (a private COPY per arm)"
          if args.isolate_learned else f"{learned} (SHARED, carried forward)"))

    qdrant_src = None
    if args.parallel > 1 or args.isolate_qdrant:
        qdrant_src = (args.qdrant_root or (repo / "qdrant_data")).resolve()
        if not qdrant_src.is_dir():
            sys.exit(f"--parallel/--isolate-qdrant need a vector store to copy, but "
                     f"{qdrant_src} is not a directory. Point --qdrant-root at it.")
        print(f"vector store: a private COPY per arm from {qdrant_src}")

    records, _rec_lock = [], threading.Lock()

    def _one(name, overrides):
        if args.isolate_learned:
            # A private copy per arm, seeded from the same starting store, so no arm
            # can see what another learned and running order stops mattering.
            arm_learned = args.results / name / "learned"
            if arm_learned.exists():
                shutil.rmtree(arm_learned)
            shutil.copytree(learned, arm_learned)
            _writable(arm_learned)
        else:
            arm_learned = learned
        # One arm must never be able to end the study. Arms cost the better part of
        # an hour each; an exception in the last arm previously discarded every
        # earlier one, because summary.json is only written after the loop.
        try:
            rec = run_arm(name, overrides, args, arm_learned, qdrant_src)
        except Exception:
            print(f"  !! {name}: the runner itself raised — recording the arm as "
                  f"failed and carrying on:")
            traceback.print_exc()
            rec = {"arm": name, "overrides": overrides,
                   "runner_error": traceback.format_exc(limit=8)}
        with _rec_lock:
            records.append(rec)
            _write_summary(args, learned, records)  # after EVERY arm, not just at the end
        return rec

    if args.parallel > 1:
        # Arms are LLM-bound, not GPU-bound — thinking time is ~99% of every arm's wall
        # clock — so concurrency buys close to linear speedup. Kept modest by default
        # anyway: the segmentation steps inside each arm DO want the GPU.
        from concurrent.futures import ThreadPoolExecutor
        print(f"running {args.parallel} arms at a time; per-arm output goes to "
              f"<arm>/container.log (live echo is off while parallel)")
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [pool.submit(_one, n, o) for n, o in selected]
            try:
                for f in futures:
                    f.result()
            except KeyboardInterrupt:
                print("\ninterrupted — cancelling queued arms")
                for f in futures:
                    f.cancel()
    else:
        for name, overrides in selected:
            try:
                _one(name, overrides)
            except KeyboardInterrupt:
                print("\ninterrupted — writing the summary for the arms completed so far")
                break

    summary = _write_summary(args, learned, records)
    print(f"\nsummary: {summary}")

    missing = [r["arm"] for r in records if not r.get("result_json") and "skipped" not in r]
    if missing:
        print(f"arms with NO result.json: {', '.join(missing)}")
    partial = [r["arm"] for r in records if r.get("partial")]
    if partial:
        print(f"PARTIAL arms (collection cut short, not comparable): {', '.join(partial)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

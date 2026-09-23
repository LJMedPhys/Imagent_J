#!/usr/bin/env bash
# Run the parasite auto-mode tasks: baseline configuration, empty learned store,
# all three tasks SEQUENTIALLY IN ONE SESSION.
#
# One container, one conversation. When task 1 finishes, its outputs are
# collected into task_1/ and task 2 is sent to the same thread; the container
# exits only after the last task. The three tasks are one piece of work on one
# dataset at widening scope, so the later ones inherit what the earlier ones
# established — which is how a person would actually do this, and it avoids
# paying the container startup three times.
#
# WHAT THAT MEANS FOR THE EXPERIMENT: the tasks share a conversation, so task 2
# can see task 1's context. That is SESSION memory, and it is not removed by
# clearing data/learned. If you want the tasks independent, run this script once
# per task (pass a task number) — each invocation is a fresh container.
#
# NOT the ablation runner: that repoints /app/data at a per-arm directory seeded
# from the TRACKED data/ skeleton, and data/parasite_task is not tracked, so the
# dataset would not be there. These prompts read data/parasite_task directly and
# need the ordinary /app/data mount that plain `docker compose run` gives.
#
# The input directory is deliberately empty. The benchmark stages every image
# under /benchmark/input FLAT into /app/data/benchmark_images; aimed at the
# parasite folder that copies 40 positions x 263 frames into one directory, with
# name collisions, and still misses the .roi files. Only instruction files are
# required — _auto_send returns early on a missing instruction, never on missing
# images.
#
# Vision (VLM) and QA are already true in the shipped imagentj_config.yaml, so
# baseline runs with both on; nothing is overridden here.
#
# Usage:
#   scripts/run_parasite_auto.sh            # tasks 1,2,3 in one session
#   scripts/run_parasite_auto.sh 2          # just task 2, its own container
#   scripts/run_parasite_auto.sh 1 2        # tasks 1 and 2 in one session
set -euo pipefail

REPO="${REPO:-$PWD}"
TASKS="${TASKS:-$REPO/tasks}"
RUNS="${RUNS:-$REPO/parasite_runs}"
COMPOSE=(-f "$REPO/docker-compose.yml")
[ -f "$REPO/docker-compose.spark.yml" ] && COMPOSE+=(-f "$REPO/docker-compose.spark.yml")

if [ "$#" -gt 0 ]; then WHICH=("$@"); else WHICH=(1 2 3); fi

[ -d "$REPO/data/parasite_task" ] || {
    echo "data/parasite_task not found under $REPO — that is the path the prompts use" >&2
    exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$RUNS/session-$STAMP"
mkdir -p "$OUT" "$RUNS/_empty_input"
chmod 777 "$OUT"

# instruction_1.txt, instruction_2.txt … is the sequence form the auto-pilot
# reads; a single one is sent as a lone task and writes to the output root.
i=0
for n in "${WHICH[@]}"; do
    PROMPT="$TASKS/parasite_auto_${n}.txt"
    [ -f "$PROMPT" ] || { echo "missing prompt: $PROMPT" >&2; exit 1; }
    i=$((i + 1))
    if [ "${#WHICH[@]}" -eq 1 ]; then cp "$PROMPT" "$OUT/instruction.txt"
    else                              cp "$PROMPT" "$OUT/instruction_${i}.txt"; fi
done

echo "session   : $OUT"
echo "tasks     : ${WHICH[*]}  (${#WHICH[@]} in one conversation)"
echo

# Empty the learned store once, before the session. Not between tasks: the tasks
# deliberately share this session, so resetting mid-way would clear what task 1
# wrote while task 1's conversation context stayed — inconsistent, and worse
# than either choice made cleanly.
"$REPO/scripts/reset_learned.sh" --apply "$REPO/data/learned"
echo

docker compose "${COMPOSE[@]}" run --rm --name "parasite_auto_$STAMP" \
    -e BENCHMARK_MODE=true \
    -e BENCHMARK_INTERACTIVE=false \
    -e BENCHMARK_INPUT_DIR=/benchmark/input \
    -e BENCHMARK_OUTPUT_DIR=/benchmark/output \
    -v "$RUNS/_empty_input:/benchmark/input:ro" \
    -v "$OUT:/benchmark/output" \
    imagentj 2>&1 | tee "$OUT/container.log"

echo
echo "session finished: $OUT"
for d in "$OUT"/task_* "$OUT"; do
    [ -d "$d" ] || continue
    [ -f "$d/result.json" ] && echo "  $(basename "$d"): result.json present" \
                            || echo "  $(basename "$d"): NO result.json"
done

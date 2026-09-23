#!/usr/bin/env bash
# Run the parasite auto-mode tasks: baseline configuration, empty learned store.
#
# NOT the ablation runner. That runner repoints /app/data at a per-arm results
# directory seeded from the TRACKED data/ skeleton — and data/parasite_task is
# not tracked, so the dataset would simply not be there. These tasks read
# data/parasite_task directly, so the container needs its normal /app/data
# mount, which is what plain `docker compose run` gives.
#
# The input directory is deliberately EMPTY. The benchmark stages every image it
# finds under /benchmark/input FLAT into /app/data/benchmark_images; pointed at
# the parasite folder that would copy 40 positions x 263 frames into one
# directory, collide on names, and still miss the .roi files, which are not an
# image extension. The prompts name their own paths, and only instruction.txt is
# actually required — _auto_send returns early on a missing instruction, never on
# missing images.
#
# "No knowledge of data/learned" is enforced by emptying the store before EACH
# task, because a run writes to it: without the reset between tasks, task 2 would
# start with whatever task 1 learned.
#
# Usage:
#   scripts/run_parasite_auto.sh                 # all three
#   scripts/run_parasite_auto.sh 2               # just task 2
set -euo pipefail

REPO="${REPO:-$PWD}"
TASKS="${TASKS:-$REPO/tasks}"
RUNS="${RUNS:-$REPO/parasite_runs}"
COMPOSE=(-f "$REPO/docker-compose.yml")
[ -f "$REPO/docker-compose.spark.yml" ] && COMPOSE+=(-f "$REPO/docker-compose.spark.yml")

WHICH=("${@:-1 2 3}")
read -r -a WHICH <<< "${WHICH[@]}"

[ -d "$REPO/data/parasite_task" ] || {
    echo "data/parasite_task not found under $REPO — that is the path the prompts use" >&2
    exit 1; }

mkdir -p "$RUNS/_empty_input"

for n in "${WHICH[@]}"; do
    PROMPT="$TASKS/parasite_auto_${n}.txt"
    [ -f "$PROMPT" ] || { echo "missing prompt: $PROMPT" >&2; exit 1; }
    OUT="$RUNS/parasite_auto_${n}"

    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  TASK $n   ->  $OUT"
    echo "════════════════════════════════════════════════════════════════"

    # Empty learned BEFORE each task. reset_learned.sh keeps concepts/library.md,
    # which is shipped content: deleting it disables recall_concepts silently.
    "$REPO/scripts/reset_learned.sh" --apply "$REPO/data/learned"

    mkdir -p "$OUT"
    chmod 777 "$OUT"
    cp "$PROMPT" "$OUT/instruction.txt"

    docker compose "${COMPOSE[@]}" run --rm --name "parasite_auto_${n}" \
        -e BENCHMARK_MODE=true \
        -e BENCHMARK_INTERACTIVE=false \
        -e BENCHMARK_INPUT_DIR=/benchmark/input \
        -e BENCHMARK_OUTPUT_DIR=/benchmark/output \
        -v "$RUNS/_empty_input:/benchmark/input:ro" \
        -v "$OUT:/benchmark/output" \
        imagentj 2>&1 | tee "$OUT/container.log"

    echo "task $n finished; result.json: $([ -f "$OUT/result.json" ] && echo yes || echo NO)"
done

echo
echo "outputs under $RUNS/"

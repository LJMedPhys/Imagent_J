#!/usr/bin/env bash
# Stage the FEW-SHOT condition: put a small worked example back into the dataset
# and leave everything else out, so the agent has the convention but not the answers.
#
#   task 1  one_frame/nuclei_tunel_roi   -> one nucleus ROI + one background ROI
#   task 2  one_frame/parasite_roi       -> one subset (set_1)
#   task 3  3. Data Analysis ROIs        -> five position folders
#
# The full sets live in parasite-task-parts/ (moved out earlier). Nothing is
# moved back OUT of there: the examples are COPIED in, so the complete sets
# stay intact and a different example can be staged later without restoring
# anything first.
#
# Dry run by default — it prints what it would copy. Nothing happens without
# --apply, because the thing being constructed here is the experimental
# condition, and staging one file too many quietly turns a few-shot run into a
# guided one.
#
# Usage:
#   scripts/stage_fewshot_rois.sh                    # show what is available
#   scripts/stage_fewshot_rois.sh --apply
#   POSITIONS="1 10 20 30 40" scripts/stage_fewshot_rois.sh --apply
#   SUBSET=set_2 scripts/stage_fewshot_rois.sh --apply
set -euo pipefail

REPO="${REPO:-$PWD}"
PARTS="${PARTS:-$REPO/parasite-task-parts}"
DATA="${DATA:-$REPO/data/parasite_task}"
# Spread across the plate rather than the first five: consecutive positions sit
# next to each other on the dish and share whatever was locally odd about it.
POSITIONS="${POSITIONS:-1 10 20 30 40}"
SUBSET="${SUBSET:-set_1}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

[ -d "$PARTS" ] || { echo "no parasite-task-parts at $PARTS" >&2; exit 1; }
[ -d "$DATA" ]  || { echo "no dataset at $DATA" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
copy() {  # copy() SRC DST — reports, and only acts under --apply
    local src="$1" dst="$2"
    if [ ! -e "$src" ]; then say "   MISSING  $src"; return 1; fi
    say "   copy     $(basename "$src")  ->  ${dst#$REPO/}"
    if [ "$APPLY" -eq 1 ]; then mkdir -p "$(dirname "$dst")"; cp -a "$src" "$dst"; fi
}

say "=================================================================="
say "TASK 3 — five example position folders"
say "=================================================================="
SRC3="$PARTS/3. Data Analysis ROIs/Apoptotic cells"
DST3="$DATA/3. Data Analysis ROIs/Apoptotic cells"
if [ -d "$SRC3" ]; then
    say "available: $(ls "$SRC3" | wc -l) position folder(s)"
    for p in $POSITIONS; do
        copy "$SRC3/Position_$p" "$DST3/Position_$p" || true
    done
else
    say "   not found: $SRC3"
fi

say
say "=================================================================="
say "TASK 2 — one parasite subset ($SUBSET)"
say "=================================================================="
SRC2="$PARTS/one_frame/parasite_roi"
DST2="$DATA/one_frame/parasite_roi"
if [ -d "$SRC2" ]; then
    say "contents of parasite_roi:"
    ls "$SRC2" | sed 's/^/   /' | head -20
    # A subset may be a subdirectory or a filename prefix; handle both.
    if [ -d "$SRC2/$SUBSET" ]; then
        copy "$SRC2/$SUBSET" "$DST2/$SUBSET" || true
    else
        n=0
        for f in "$SRC2"/*"$SUBSET"*; do
            [ -e "$f" ] || continue
            copy "$f" "$DST2/$(basename "$f")" || true; n=$((n+1))
        done
        [ "$n" -eq 0 ] && say "   !! nothing matched '$SUBSET' — set SUBSET= to one of the names above"
    fi
else
    say "   not found: $SRC2"
fi

say
say "=================================================================="
say "TASK 1 — one nucleus ROI + one background ROI"
say "=================================================================="
SRC1="$PARTS/one_frame/nuclei_tunel_roi"
DST1="$DATA/one_frame/nuclei_tunel_roi"
if [ -d "$SRC1" ]; then
    say "contents of nuclei_tunel_roi:"
    find "$SRC1" -maxdepth 1 -type f -printf '   %f\n' | head -20
    say "   (total $(find "$SRC1" -type f | wc -l) file(s))"
    say
    say "PICK THESE BY HAND — which file is a nucleus and which a background is not"
    say "something a script can tell from the names alone, and staging the wrong"
    say "pair changes what the run is measuring. Then:"
    say "   cp -a '$SRC1/<nucleus>.roi'    '$DST1/'"
    say "   cp -a '$SRC1/<background>.roi' '$DST1/'"
else
    say "   not found: $SRC1"
fi

say
if [ "$APPLY" -eq 1 ]; then
    say "STAGED. What the dataset now exposes:"
    find "$DATA/3. Data Analysis ROIs" "$DATA/one_frame" -maxdepth 2 -mindepth 1 \
         -type d -printf '   %p\n' 2>/dev/null | sed "s|$REPO/||"
    say
    say "The two overview ROIs must still be present:"
    ls "$DATA/one_frame/"*.ROI 2>/dev/null | sed "s|$REPO/|   |" || say "   !! MISSING"
else
    say "(dry run — nothing copied. Re-run with --apply)"
fi

#!/usr/bin/env bash
# Empty the learned store before a run, WITHOUT removing what ships with it.
#
# The store holds two kinds of thing and they need opposite treatment:
#
#   ACCUMULATED  written by past runs — the nine markdown pages, the saved
#                scripts under recipes/code/, and the .runcount/.lintcursor
#                bookkeeping. This is what you want gone.
#
#   SHIPPED      concepts/library.md (the concept database recall_concepts
#                serves) and the READMEs. Removing these turns the concepts
#                feature off WITHOUT SAYING SO: the tool still exists, still
#                gets called, and returns nothing. That reads as "the feature
#                does not help" rather than "the feature is missing", which is
#                why this script names files explicitly instead of wiping a
#                directory.
#
# The nine pages are emptied rather than deleted so their parent structure and
# permissions survive intact.
#
# Usage:
#   scripts/reset_learned.sh                 # dry run against ./data/learned
#   scripts/reset_learned.sh --apply
#   scripts/reset_learned.sh --apply /path/to/learned
set -euo pipefail

APPLY=0
ROOT="./data/learned"
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        *) ROOT="$arg" ;;
    esac
done

[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 1; }
ROOT="$(cd "$ROOT" && pwd)"

EMPTY=(
    "log.md"
    "recipes/Python.md"        "recipes/Groovy.md"
    "recipes/CORE.Python.md"   "recipes/CORE.Groovy.md"
    "pitfalls/Python.md"       "pitfalls/Groovy.md"
    "pitfalls/CORE.Python.md"  "pitfalls/CORE.Groovy.md"
)
PURGE_FILES=(".runcount" ".lintcursor")
KEEP=("concepts/library.md" "concepts/README.md" "README.md")

echo "learned store: $ROOT"
echo
echo "WILL EMPTY (file kept, contents cleared):"
for rel in "${EMPTY[@]}"; do
    f="$ROOT/$rel"
    if [ -f "$f" ]; then printf '  %10s B  %s\n' "$(stat -c%s "$f")" "$rel"
    else               printf '  %12s  %s\n' "missing" "$rel"; fi
done

echo
echo "WILL DELETE:"
# `find` on a missing directory fails, and under `set -o pipefail` that would
# kill the whole script before it did anything — silently, since the error is
# discarded. Guard the directory instead of relying on the redirect.
if [ -d "$ROOT/recipes/code" ]; then
    n=$(find "$ROOT/recipes/code" -type f | wc -l)
else
    n=0
fi
printf '  %10s files  recipes/code/\n' "$n"
for rel in "${PURGE_FILES[@]}"; do
    [ -e "$ROOT/$rel" ] && printf '  %16s  %s\n' "present" "$rel" \
                        || printf '  %16s  %s\n' "absent" "$rel"
done

echo
echo "WILL KEEP (shipped — removing it disables the feature silently):"
for rel in "${KEEP[@]}"; do
    f="$ROOT/$rel"
    if [ -f "$f" ]; then printf '  %10s B  %s\n' "$(stat -c%s "$f")" "$rel"
    else               printf '  %12s  %s\n' "MISSING!" "$rel"; fi
done

if [ "$APPLY" -ne 1 ]; then
    echo
    echo "(dry run — nothing changed. Re-run with --apply)"
    exit 0
fi

BACKUP="${ROOT}.bak-$(date +%Y%m%d-%H%M%S)"
cp -a "$ROOT" "$BACKUP"
echo
echo "backed up to $BACKUP"

for rel in "${EMPTY[@]}"; do
    mkdir -p "$(dirname "$ROOT/$rel")"
    : > "$ROOT/$rel"
done
rm -rf "$ROOT/recipes/code"
mkdir -p "$ROOT/recipes/code"
for rel in "${PURGE_FILES[@]}"; do rm -f "$ROOT/$rel"; done

echo "cleared ${#EMPTY[@]} page(s), purged recipes/code/ and ${#PURGE_FILES[@]} marker file(s)"
echo "concepts/library.md left intact: $(stat -c%s "$ROOT/concepts/library.md" 2>/dev/null || echo MISSING) B"

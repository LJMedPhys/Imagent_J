#!/bin/bash
# Re-pin the uv lock files the Dockerfile installs. Run after editing a *.in file:
#     docker/requirements/compile.sh            # keep existing pins where possible
#     docker/requirements/compile.sh --upgrade  # move everything to latest
# cellpose.in is not compiled — see the comment at its top.
set -euo pipefail
cd "$(dirname "$0")"
for env in main napari; do
    echo "[compile] $env.in -> $env.txt"
    uv pip compile "$env.in" --python-version 3.13 --universal \
        --output-file "$env.txt" --quiet "$@"
done

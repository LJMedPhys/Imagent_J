#!/bin/bash
# conda / micromamba compatibility shim over the image's uv virtualenvs.
#
# The image has no conda. Python envs are uv venvs laid out conda-style under
# /opt/uv/envs/<name> (main, cellpose, napari-mcp). Two Fiji components still
# speak conda, and this shim answers them:
#
#   * TrackMate-Cellpose hardcodes /usr/local/opt/micromamba/bin/micromamba
#     (older builds) or /opt/micromamba/bin/micromamba (newer) and calls
#         micromamba run -n <CONDA_ENV> cellpose ...
#     with CONDA_ENV defaulting to 'base'.
#   * TrackMate v8's conda configurator (~/.imagej/trackmate-conda.prefs points
#     condaExecutable at /opt/uv/bin/conda, a copy of this file) lists envs with
#     `env list` to fill its dropdown.
#
# (The BIOP Cellpose wrapper does NOT need this: on Linux it runs
#  `<env_path>/bin/python -m cellpose ...` directly.)
#
# Env routing for `run`:
#   '-n base' / no env / '-n cellpose'  → cellpose  (cellpose 3.1.1.2, model cyto3 baked in)
#   '-n <name>' with /opt/uv/envs/<name> → that env
#   '-n cellpose4' / '-n omnipose' / a 'cpsam' argument → error: not installed in this image

ENVS_ROOT="${IMAGENTJ_ENVS_ROOT:-/opt/uv/envs}"

_die() { echo "[conda-shim] ERROR: $*" >&2; exit 1; }

_env_dir() {
    case "$1" in
        ""|base|cellpose)
            echo "$ENVS_ROOT/cellpose" ;;
        cellpose4)
            _die "env 'cellpose4' (Cellpose 4 / Cellpose-SAM) is not installed in this image — use the 'cellpose' env (Cellpose 3, model cyto3)." ;;
        omnipose)
            _die "Omnipose is not installed in this image — use the 'cellpose' env (Cellpose 3, model cyto3)." ;;
        *)
            [ -d "$ENVS_ROOT/$1" ] || _die "unknown env '$1' (available: $(ls "$ENVS_ROOT" | tr '\n' ' '))"
            echo "$ENVS_ROOT/$1" ;;
    esac
}

_list_envs() {
    # 'base' is TrackMate-Cellpose's default CONDA_ENV; list it so the dropdown
    # shows it, pointing at the env it is routed to.
    [ -x "$ENVS_ROOT/cellpose/bin/python" ] && echo "base $ENVS_ROOT/cellpose"
    for d in "$ENVS_ROOT"/*/; do
        d="${d%/}"
        [ -x "$d/bin/python" ] && echo "$(basename "$d") $d"
    done
}

CMD="${1:-}"
case "$CMD" in
    run)
        shift
        ENV_NAME="" PREFIX="" ARGS=()
        # Options conda/micromamba accept before the command; the first
        # non-option word starts the command, which is passed through untouched.
        while [ $# -gt 0 ] && [ ${#ARGS[@]} -eq 0 ]; do
            case "$1" in
                -n|--name)    ENV_NAME="$2"; shift 2 ;;
                -p|--prefix)  PREFIX="$2";   shift 2 ;;
                --cwd)        cd "$2" || _die "cannot cd to $2"; shift 2 ;;
                --no-capture-output|--live-stream|--attach|-a|-v|-vv|-vvv|--debug)
                              shift ;;
                --)           shift; ARGS=("$@"); break ;;
                -*)           shift ;;               # unknown option: ignore
                *)            ARGS=("$@"); break ;;
            esac
        done
        [ ${#ARGS[@]} -gt 0 ] || _die "'run' needs a command"
        for arg in "${ARGS[@]}"; do
            [ "$arg" = "cpsam" ] && _die "model 'cpsam' (Cellpose-SAM, Cellpose 4) is not installed in this image — use cyto3 (Cellpose 3)."
        done
        if [ -n "$PREFIX" ]; then
            ENV_DIR="$PREFIX"
            [ -d "$ENV_DIR" ] || _die "prefix '$PREFIX' does not exist"
        else
            ENV_DIR="$(_env_dir "$ENV_NAME")" || exit 1
        fi
        echo "[conda-shim] env='${ENV_NAME:-${PREFIX:-<none>}}' → $ENV_DIR" >&2
        export VIRTUAL_ENV="$ENV_DIR"
        export PATH="$ENV_DIR/bin:$PATH"
        exec "${ARGS[@]}"
        ;;
    env|info)
        if [ "$CMD" = "env" ] && [ "${2:-}" != "list" ]; then
            _die "only 'env list' is supported (envs are built into the image)"
        fi
        if [[ " $* " == *" --json "* ]]; then
            printf '{"envs": ['
            sep=""
            while read -r name path; do printf '%s"%s"' "$sep" "$path"; sep=", "; done < <(_list_envs)
            printf '], "root_prefix": "/opt/uv", "conda_prefix": "/opt/uv"}\n'
        elif [ "$CMD" = "info" ] && [[ " $* " == *" --base "* ]]; then
            echo /opt/uv
        else
            # micromamba-style table — the format TrackMate-Cellpose parses.
            printf "  Name                  Active  Path\n"
            printf -- "─%.0s" {1..62}; printf "\n"
            while read -r name path; do
                printf "  %-22s%-8s%s\n" "$name" " " "$path"
            done < <(_list_envs)
        fi
        ;;
    --version|-V|version)
        echo "conda 24.1.0 (Agentic-J uv shim)"
        ;;
    *)
        _die "unsupported command '$*' — this image has no conda; envs are prebuilt uv venvs under $ENVS_ROOT"
        ;;
esac

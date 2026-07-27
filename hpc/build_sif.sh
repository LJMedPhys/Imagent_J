#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Build the Imagent_J GPU or CPU Docker image and convert it to an Apptainer SIF
without sudo.

Usage:
  hpc/build_sif.sh [options]

Options:
  --variant NAME     Image variant: gpu or cpu (default: gpu)
  --cuda-tag TAG     GPU PyTorch CUDA wheel tag (default: cu126)
  --image NAME       Docker image/tag (default depends on --variant)
  --output PATH      SIF output path (default includes variant, git SHA, and arch)
  --skip-docker      Reuse an existing Docker image instead of building it
  --archive-only     Export a gzip-compressed docker-save archive instead of a SIF
  --archive PATH     Archive output path (default: .apptainer/<image>-<arch>.tar.gz)
  --apptainer-bin P  Apptainer executable to use
  --nested-docker    Run Apptainer in a privileged, AppArmor-unconfined Docker
                     container (for Ubuntu hosts that restrict user namespaces)
  --force            Allow replacing the requested output artifact
  -h, --help         Show this help

The script never invokes sudo. --nested-docker requires access to the Docker
daemon and uses an ephemeral privileged container. Otherwise direct conversion
requires `apptainer` or `singularity` on this machine. If neither is available,
use --archive-only and run the printed command once on the HPC.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
variant="gpu"
cuda_tag="cu126"
image=""
output=""
archive=""
apptainer_bin="${APPTAINER_BIN:-}"
skip_docker=0
archive_only=0
nested_docker=0
force=0

while (($#)); do
    case "$1" in
        --variant)
            variant="${2:?--variant requires gpu or cpu}"
            shift 2
            ;;
        --cuda-tag)
            cuda_tag="${2:?--cuda-tag requires a value}"
            shift 2
            ;;
        --image)
            image="${2:?--image requires a value}"
            shift 2
            ;;
        --output)
            output="${2:?--output requires a value}"
            shift 2
            ;;
        --skip-docker)
            skip_docker=1
            shift
            ;;
        --archive-only)
            archive_only=1
            shift
            ;;
        --archive)
            archive="${2:?--archive requires a value}"
            shift 2
            ;;
        --apptainer-bin)
            apptainer_bin="${2:?--apptainer-bin requires a path}"
            shift 2
            ;;
        --nested-docker)
            nested_docker=1
            shift
            ;;
        --force)
            force=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$variant" in
    gpu|cpu) ;;
    *)
        echo "--variant must be 'gpu' or 'cpu', got: $variant" >&2
        exit 2
        ;;
esac

if [[ "$variant" == "gpu" && ! "$cuda_tag" =~ ^cu[0-9]+$ ]]; then
    echo "--cuda-tag must look like cu126 or cu128, got: $cuda_tag" >&2
    exit 2
fi

if [[ -z "$image" ]]; then
    if [[ "$variant" == "gpu" ]]; then
        image="agenticj:gpu-local-napari"
    else
        image="agenticj:cpu-local-napari"
    fi
fi

command -v docker >/dev/null 2>&1 || {
    echo "docker is required to build or export the image." >&2
    exit 1
}

artifact_dir="$repo_root/.apptainer"
mkdir -p "$artifact_dir"

if ((skip_docker == 0)); then
    compose_files=(-f "$repo_root/docker-compose.yml")
    if [[ "$variant" == "gpu" ]]; then
        compose_files+=(-f "$repo_root/docker-compose.gpu.yml")
    fi
    echo "[sif] Building Docker variant '$variant' as $image"
    IMAGENTJ_IMAGE="$image" CUDA_TAG="$cuda_tag" docker compose \
        "${compose_files[@]}" \
        --project-directory "$repo_root" build imagentj
elif ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Docker image not found: $image" >&2
    exit 1
fi

image_arch="$(docker image inspect --format '{{.Architecture}}' "$image")"
case "$image_arch" in
    amd64) sif_arch="x86_64" ;;
    arm64) sif_arch="aarch64" ;;
    *) sif_arch="$image_arch" ;;
esac

git_sha="$(git -C "$repo_root" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
safe_image="${image//[^A-Za-z0-9_.-]/-}"
output="${output:-$artifact_dir/agenticj-${variant}-${git_sha}-${sif_arch}.sif}"
archive="${archive:-$artifact_dir/${safe_image}-${sif_arch}.tar.gz}"

refuse_existing() {
    local target="$1"
    if [[ -e "$target" && "$force" -ne 1 ]]; then
        echo "Refusing to replace existing artifact: $target" >&2
        echo "Pass --force or choose a different path." >&2
        exit 1
    fi
    mkdir -p "$(dirname -- "$target")"
}

write_manifest() {
    local artifact="$1"
    local manifest="${artifact}.sha256"
    refuse_existing "$manifest"
    sha256sum "$artifact" > "$manifest"
    echo "[sif] Checksum: $manifest"
}

if ((archive_only == 1)); then
    refuse_existing "$archive"
    echo "[sif] Exporting compressed Docker archive: $archive"
    docker save "$image" | gzip -1 > "$archive"
    write_manifest "$archive"
    cat <<EOF

Archive ready. On the HPC (no sudo required):

  export APPTAINER_CACHEDIR="\$PWD/.apptainer-cache"
  export APPTAINER_TMPDIR="\$PWD/.apptainer-tmp"
  mkdir -p "\$APPTAINER_CACHEDIR" "\$APPTAINER_TMPDIR"
  apptainer build agenticj-${variant}-${git_sha}-${sif_arch}.sif docker-archive:$(basename -- "$archive")
EOF
    exit 0
fi

if [[ -n "$apptainer_bin" ]]; then
    apptainer_bin="$(readlink -f -- "$apptainer_bin")"
    if [[ ! -x "$apptainer_bin" ]]; then
        echo "Apptainer executable is not executable: $apptainer_bin" >&2
        exit 1
    fi
elif command -v apptainer >/dev/null 2>&1; then
    apptainer_bin="$(command -v apptainer)"
elif command -v singularity >/dev/null 2>&1; then
    apptainer_bin="$(command -v singularity)"
else
    echo "No apptainer/singularity executable found." >&2
    echo "Pass --apptainer-bin, or use --archive-only and convert on the HPC." >&2
    exit 1
fi

refuse_existing "$output"
cache_dir="$artifact_dir/cache"
tmp_dir="$artifact_dir/tmp"
mkdir -p "$cache_dir" "$tmp_dir"

echo "[sif] Converting $image directly from the Docker daemon"
echo "[sif] Output: $output"
build_args=()
if ((force == 1)); then
    build_args+=(--force)
fi

if ((nested_docker == 1)); then
    apptainer_prefix="$(cd -- "$(dirname -- "$apptainer_bin")/.." && pwd)"
    docker run --rm \
        --privileged \
        --security-opt apparmor=unconfined \
        --user 0:0 \
        --volume /var/run/docker.sock:/var/run/docker.sock \
        --volume /etc/ssl/certs:/etc/ssl/certs:ro \
        --volume /etc/localtime:/etc/localtime:ro \
        --volume "$apptainer_prefix:$apptainer_prefix:ro" \
        --volume "$artifact_dir:$artifact_dir" \
        --env "PATH=$apptainer_prefix/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        --env SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
        --env "APPTAINER_CACHEDIR=$cache_dir" \
        --env APPTAINER_TMPDIR=/tmp \
        ubuntu:24.04 \
        "$apptainer_bin" build "${build_args[@]}" "$output" "docker-daemon:$image"
else
    apptainer_bin_dir="$(dirname -- "$apptainer_bin")"
    PATH="$apptainer_bin_dir:$PATH" \
    APPTAINER_CACHEDIR="$cache_dir" \
    APPTAINER_TMPDIR="$tmp_dir" \
    SINGULARITY_CACHEDIR="$cache_dir" \
    SINGULARITY_TMPDIR="$tmp_dir" \
    "$apptainer_bin" build "${build_args[@]}" "$output" "docker-daemon:$image"
fi

write_manifest "$output"
echo "[sif] Built successfully: $output"

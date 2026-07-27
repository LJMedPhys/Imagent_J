# Imagent_J on an HPC with Apptainer

This directory provides a no-`sudo` path from the Docker image to a SIF and an
external adapter shim for the unpublished bioimage benchmark. Nothing here
needs to modify the benchmark checkout.

## 1. Install Apptainer without sudo

One reproducible user-level installation is a dedicated Conda prefix:

```bash
conda create --prefix /path/to/apptainer-1.5.3 \
  --override-channels -c conda-forge apptainer=1.5.3 -y
```

Use `/path/to/apptainer-1.5.3/bin/apptainer` as `--apptainer-bin` below. A
non-setuid installation requires unprivileged user namespaces.

Ubuntu 24.04 hosts can restrict those namespaces through AppArmor even when the
kernel otherwise supports them. If a direct `apptainer exec docker://alpine`
fails with a user-namespace permission error, use `--nested-docker`. This runs
the installed Apptainer in an ephemeral privileged, AppArmor-unconfined Docker
container. It still does not invoke `sudo`, but Docker daemon access is
root-equivalent and should only be used on a trusted build host.

## 2. Build the GPU SIF

GPU with CUDA 12.6-compatible PyTorch is the default:

```bash
hpc/build_sif.sh \
  --apptainer-bin /path/to/apptainer-1.5.3/bin/apptainer \
  --nested-docker
```

The script applies `docker-compose.gpu.yml`, builds
`agenticj:gpu-local-napari` with `USE_GPU=true` and `CUDA_TAG=cu126`, then
converts it directly from the Docker daemon. The output filename includes
`gpu`, the Git SHA, and the architecture. Artifacts and SHA-256 manifests stay
below the local `.apptainer/` directory.

Useful alternatives:

```bash
# Reuse the existing GPU Docker image
hpc/build_sif.sh --skip-docker --apptainer-bin /path/to/apptainer --nested-docker

# Build a cu128 GPU image
hpc/build_sif.sh --cuda-tag cu128 --apptainer-bin /path/to/apptainer --nested-docker

# Build the CPU variant
hpc/build_sif.sh --variant cpu --apptainer-bin /path/to/apptainer --nested-docker

# Export a compressed Docker archive for conversion on the cluster
hpc/build_sif.sh --archive-only
```

Do not use GitHub Release assets for this image: each Release asset is limited
to 2 GiB, while this application is much larger. Prefer one of:

1. Push the Docker/OCI image to an organization registry such as GHCR, then run
   `apptainer pull agenticj.sif docker://ghcr.io/<org>/<image>:<tag>` on the
   cluster. GHCR limits each individual layer to 10 GB. The current CPU image
   has an 11.2 GB uncompressed Conda layer (`docker history`), so treat this
   route as experimental until a test push succeeds or that Dockerfile layer
   is split.
2. Push the final SIF as an ORAS artifact with
   `apptainer push agenticj.sif oras://<registry>/<namespace>/<name>:<tag>`.
3. For an unpublished/private benchmark, place the SIF in the institute's
   access-controlled project storage and verify it with the generated SHA-256
   file after transfer.

Option 3 is the least surprising initial route for a very large private image.

## 3. Keep benchmark execution out of a colleague's checkout

The benchmark writes run outputs, submissions, Python bytecode, and sometimes
adapter state. Use a personal checkout or a personal scratch copy for actual
runs. Treat a colleague's path only as a read-only reference.

The examples below use:

```bash
export IMAGENTJ_DIR=/absolute/path/to/Imagent_J
export BENCHMARK_DIR=/absolute/path/to/your-own/bioimage-agent-bench
```

Prepare `IMAGENTJ_DIR/.env` with an API key. Edit
`IMAGENTJ_DIR/imagentj_config.yaml` to choose models and enable/disable the VLM
and QA agents. The external adapter bind-mounts this file, so those edits do not
require a SIF rebuild.

Copy `hpc/adapter.example.json` to a private run-config file and replace its
absolute paths. Keep that run-config outside a colleague's directory.

## 4. Run with the config-aware adapter

From your personal benchmark checkout:

```bash
cd "$BENCHMARK_DIR"
PYTHONPATH="$IMAGENTJ_DIR:$BENCHMARK_DIR" \
python -m bioimage_agent_bench.cli run-export-submission \
  --task-dir benchmark_tasks/fluo-cell-counting-2d-cellfmcount \
  --agent agentic_j_apptainer \
  --agent-class hpc.benchmark_adapter:ImagentJApptainerAdapter \
  --agent-init-json "$IMAGENTJ_DIR/hpc/adapter.json" \
  --output-base outputs/results \
  --submission-out outputs/submissions \
  --agent-version local-sif \
  --prompt-version v1 \
  --zip
```

The shim defaults to `interactive=false`, `unattended=true`, and `nv=true`.
Apptainer receives `--nv` so CUDA applications use the cluster's NVIDIA driver
and devices. Xvfb and the Fiji GUI still run for screenshots and vision
judging, but x11vnc/noVNC are skipped to avoid ports 5900/6080 colliding across
jobs.

Persistent container state is kept under
`IMAGENTJ_DIR/.apptainer/volumes/`. Benchmark inputs are mounted read-only; run
results are written only to the personal benchmark checkout selected above.

## 5. Slurm notes

Set Apptainer cache and temporary directories to node-local scratch when the
cluster provides it, especially for a multi-gigabyte image:

```bash
export APPTAINER_CACHEDIR="${SLURM_TMPDIR:-$PWD}/apptainer-cache"
export APPTAINER_TMPDIR="${SLURM_TMPDIR:-$PWD}/apptainer-tmp"
mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"
```

The SIF contains CUDA-enabled Python packages, but not the host kernel driver.
Submit the benchmark to an NVIDIA GPU partition and keep `nv=true` in the
adapter configuration.

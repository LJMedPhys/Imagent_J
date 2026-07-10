# Cellpose (BIOP wrapper) — Groovy Script API

All identifiers below are verified against the installed jar
`/opt/Fiji.app/jars/ijl-utilities-wrappers-0.12.1.jar`.

## Commands

| Class | Use for | conda env |
|-------|---------|-----------|
| `ch.epfl.biop.wrappers.cellpose.ij2commands.Cellpose` | cellpose v3 models: `cyto3`, `cyto2`, `nuclei`, `tissuenet_cp3`, `livecell_cp3`, `bact_*`, custom | `/opt/conda/envs/cellpose` (cellpose **3.1.1.2**) |
| `ch.epfl.biop.wrappers.cellpose.ij2commands.CellposeSAM` | Cellpose-SAM model `cpsam` | `/opt/conda/envs/cellpose4` (cellpose **4.1.1**) |

The verified, primary path is the `Cellpose` command with `cyto3`/`nuclei` in the
`cellpose` env. `CellposeSAM` inherits the same fields (`imp`, `env_path`, `env_type`,
`model`, `model_path`, `verbose`, `cellpose_imp`) but targets the `cellpose4` env + `cpsam`
model, and **does not use `ch1`/`ch2` (channel-agnostic) or `diameter` (dropped in
Cellpose 4)** — don't set them. Cellpose-SAM is heavy on CPU; prefer a GPU. See SKILL.md.

## Fields on the `Cellpose` command

Set as plain Groovy properties (`cp.field = value`). Inject the SciJava context first
(`ctx.inject(cp)`); the official BIOP template instantiates the command with `new Cellpose()`.

| Field | Java type | Meaning |
|-------|-----------|---------|
| `imp` | `ij.ImagePlus` | **Input** image to segment |
| `env_path` | `java.io.File` | conda env directory, e.g. `new File("/opt/conda/envs/cellpose")` |
| `env_type` | `String` | `"conda"` (only conda works on Linux; venv is Windows-only in this wrapper) |
| `model` | `String` | pre-trained model name (resolved from `~/.cellpose/models`). Leave `""` if using `model_path` |
| `model_path` | `java.io.File` | path to a **custom** model file; set `model = ""` when using this |
| `diameter` | `float` | expected object diameter in px. `0f` = auto-estimate (cyto* only, needs a `size_*.npy`) |
| `ch1` | `int` | channel to segment (`0` = grayscale/single channel) |
| `ch2` | `int` | optional second/nucleus channel (`0` = none) |
| `additional_flags` | `String` | comma- or space-separated extra cellpose CLI flags, e.g. `"--use_gpu"`, `"--cellprob_threshold, -1"`, `"--flow_threshold, 0.6"` |
| `verbose` | `Boolean` | **set this** (`Boolean.TRUE`/`FALSE`). Nullable → can NPE if left null. TRUE logs the exact command + cellpose output |
| `cellpose_imp` | `ij.ImagePlus` | **Output** label image, populated after `run()`. 32-bit; background 0, objects 1..N |

## What `run()` actually does (for debugging)

With `verbose = TRUE` the wrapper logs, e.g.:

```
Running [-m, cellpose, --dir, /tmp/cellpose<rand>, --pretrained_model, cyto3,
         --chan, 0, --chan2, 0, --diameter, 30.0, --use_gpu, --verbose, --save_tif, --no_npy]
[bash -c /opt/conda/envs/cellpose/bin/python -m cellpose --dir /tmp/cellpose<rand> ...]
```

The `--use_gpu` flag comes from `additional_flags` (the templates set it by default). With a GPU
+ CUDA torch, cellpose logs `** TORCH CUDA version installed and working. **` / `>>>> using GPU (CUDA)`;
with no GPU it silently falls back to CPU.

It writes `imp` to a temp dir as a TIFF, runs cellpose in the conda env, reads the
`*_cp_masks.tif` back, and assigns it to `cellpose_imp`. **You never touch the temp dir** —
unlike the TrackMate-Cellpose path. The temp dir is the wrapper's concern, not the script's.

## Pre-downloaded models (`/home/imagentj/.cellpose/models`)

Pass the name as `cp.model`. Common, useful ones:

| `model` value | Target |
|---------------|--------|
| `cyto3` | general cells / cytoplasm (current default, robust). Has a size model → `diameter=0f` works |
| `cyto2` | cells / cytoplasm (previous generation) |
| `nuclei` | nuclei (fluorescence). Set `ch1=0` for a single nuclei channel |
| `tissuenet_cp3` | tissue / multiplexed |
| `livecell_cp3` | label-free / phase live cells |
| `bact_phase_cp3`, `bact_fluor_cp3`, `deepbacs_cp3` | bacteria (phase / fluorescence) |
| `general` | mixed/general |
| `cpsam` | Cellpose-SAM — use the **`CellposeSAM` command + `cellpose4` env**, not this command |

Also present (legacy / specialized): `CP`, `CPx`, `LC1`–`LC4`, `TN1`–`TN3`,
`neurips_cellpose_default`, `neurips_cellpose_transformer`, `neurips_grayscale_cyto2`,
and the `cyto*torch_*` / `nucleitorch_*` raw checkpoints. The `size_*.npy` files are size
models, not segmentation models — don't pass them as `model`.

> Note: these are raw Cellpose checkpoints, NOT BioImage-Model-Zoo bundles, so they are
> usable here (BIOP wrapper / cellpose CLI) and by TrackMate-Cellpose, but **not** by
> deepImageJ.

## Environment requirements (already handled in this image)

- **conda activation**: `BASH_ENV=/opt/conda/etc/profile.d/conda.sh` is exported before the
  JVM starts (`src/imagentj/imagej_context.py`) so the wrapper's `conda activate` works.
- **tifffile**: the `cellpose` env ships `tifffile==2025.5.10` (Dockerfile). The cellpose
  default `2023.2.28` crashes on NumPy 2.0 when reading the big-endian TIFFs ImageJ writes
  (`ndarray.newbyteorder` removed in NumPy 2.0).

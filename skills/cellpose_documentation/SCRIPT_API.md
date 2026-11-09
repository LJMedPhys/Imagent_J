# Cellpose (BIOP wrapper) — Groovy Script API

All identifiers below are verified against the installed jar
`/opt/Fiji.app/jars/ijl-utilities-wrappers-0.12.1.jar`.

## Commands

| Class | Use for | env |
|-------|---------|-----------|
| `ch.epfl.biop.wrappers.cellpose.ij2commands.Cellpose` | cellpose v3 models: `cyto3`, `cyto2`, `nucleitorch_0`, `tissuenet_cp3`, `livecell_cp3`, `bact_*`, custom | `/opt/uv/envs/cellpose` (cellpose **3.1.1.2**) |

The jar also contains a `CellposeSAM` command (Cellpose 4 / `cpsam`). It has **no backend in this
image** — Cellpose 4 is not installed — so do not use it.

The verified path is the `Cellpose` command with `cyto3` (pre-installed) or another v3 model in
the `cellpose` env.

## Fields on the `Cellpose` command

Set as plain Groovy properties (`cp.field = value`). Inject the SciJava context first
(`ctx.inject(cp)`); the official BIOP template instantiates the command with `new Cellpose()`.

| Field | Java type | Meaning |
|-------|-----------|---------|
| `imp` | `ij.ImagePlus` | **Input** image to segment |
| `env_path` | `java.io.File` | env directory, e.g. `new File("/opt/uv/envs/cellpose")` (a uv venv; keep `env_type = "conda"`) |
| `env_type` | `String` | `"conda"` (only conda works on Linux; venv is Windows-only in this wrapper) |
| `model` | `String` | pre-trained model name (resolved from `~/.cellpose/models`). Leave `""` if using `model_path` |
| `model_path` | `java.io.File` | path to a **custom** model file; set `model = ""` when using this |
| `diameter` | `float` | expected object diameter in px. `0f` = auto-estimate (cyto* only, needs a `size_*.npy`) |
| `ch1` | `int` | channel to segment (`0` = grayscale/single channel) |
| `ch2` | `int` | optional second/nucleus channel (`0` = none) |
| `additional_flags` | `String` | **comma-separated** extra cellpose CLI flags. See [Passing flags](#passing-flags-additional_flags) — a space-separated string silently breaks the run |
| `verbose` | `Boolean` | **set this** (`Boolean.TRUE`/`FALSE`). Nullable → can NPE if left null. TRUE logs the exact command + cellpose output |
| `cellpose_imp` | `ij.ImagePlus` | **Output** label image, populated after `run()`. 32-bit; background 0, objects 1..N |

## Passing flags (`additional_flags`)

The wrapper does `additional_flags.split(",")`, trims each token, and passes the tokens
straight to the cellpose CLI as argv. **It splits on commas only — never on whitespace.**
Every flag *and every value* is its own comma-separated token:

```groovy
// CORRECT — 5 argv tokens
cp.additional_flags = "--use_gpu, --cellprob_threshold, -1.0, --flow_threshold, 0.4"

// WRONG — 1 argv token containing spaces
cp.additional_flags = "--use_gpu --cellprob_threshold -1.0 --flow_threshold 0.4"
```

The wrong form fails in a way that does not point at the flags. cellpose's argparse rejects
the single blob with `error: unrecognized arguments` and exits, so no `*_cp_masks.tif` is
written, `cp.cellpose_imp` comes back **null**, and the next field access throws a
`NullPointerException` on `cellpose_t_imp`. A lone `"--use_gpu"` happens to work because it
contains no spaces — so a script can look fine until the day a second flag is added.

`flow_threshold` and `cellprob_threshold` are **not** settable fields on the command
(`cp.flow_threshold = 0.6` throws `MissingPropertyException`). They exist only as flags here.

### Threshold semantics — the directions are not symmetric

| Flag | Default | Range | Effect |
|------|---------|-------|--------|
| `--cellprob_threshold` | `0` | ~`-6`…`6` | **Decrease** → more and larger masks. **Increase** → fewer, smaller masks |
| `--flow_threshold` | `0.4` | `0`…~`1` | Flow-error QC. **Increase** → *more* masks pass QC (looser). **Decrease** → fewer (stricter). `0` disables the QC step |

A common mistake is to raise both, believing both are "stricter". Raising
`cellprob_threshold` tightens; raising `flow_threshold` *loosens*. To suppress spurious
background objects: raise `cellprob_threshold`, lower `flow_threshold`. To fix cells that
are split or clipped: lower `cellprob_threshold`.

`--norm_percentile` takes two values, so it needs three tokens:
`"--use_gpu, --norm_percentile, 1, 99"`.

### Brightfield / bright-background images

Cellpose expects objects **brighter** than their background. On bright-field data with a
bright background (dark cells) it will happily segment the background instead of the cells —
this is the classic cause of "cellpose found the background".

| Command / env | How to flip polarity |
|---|---|
| `Cellpose` (v3, cellpose 3.1.1.2) | either `IJ.run(imp, "Invert", "")` in ImageJ, **or** pass `"--use_gpu, --invert"` — v3's CLI still implements `--invert` ("invert grayscale channel") |

Inverting in ImageJ *before* assigning `cp.imp` is the simplest, most explicit answer.

Likewise, ImageJ's `Subtract Background...` assumes a dark background unless you pass the
`light` option — on bright-background data, omitting it estimates the background envelope
from the cells themselves and erases them.

## What `run()` actually does (for debugging)

With `verbose = TRUE` the wrapper logs, e.g.:

```
Running [-m, cellpose, --dir, /tmp/cellpose<rand>, --pretrained_model, cyto3,
         --chan, 0, --chan2, 0, --diameter, 30.0, --use_gpu, --verbose, --save_tif, --no_npy]
[bash -c /opt/uv/envs/cellpose/bin/python -m cellpose --dir /tmp/cellpose<rand> ...]
```

The `--use_gpu` flag comes from `additional_flags` (the templates set it by default). With a GPU
+ CUDA torch, cellpose logs `** TORCH CUDA version installed and working. **` / `>>>> using GPU (CUDA)`;
with no GPU it silently falls back to CPU.

It writes `imp` to a temp dir as a TIFF, runs cellpose in the cellpose env, reads the
`*_cp_masks.tif` back, and assigns it to `cellpose_imp`. **You never touch the temp dir** —
unlike the TrackMate-Cellpose path. The temp dir is the wrapper's concern, not the script's.

## Models (`/home/imagentj/.cellpose/models`) — `cyto3` pre-installed, the rest download on first use

Pass the name as `cp.model`. Common, useful ones:

| `model` value | Target |
|---------------|--------|
| `cyto3` | general cells / cytoplasm (current default, robust). Has a size model → `diameter=0f` works |
| `cyto2` | cells / cytoplasm (previous generation) |
| `nucleitorch_0` | nuclei (fluorescence). Set `ch1=0` for a single nuclei channel |
| `tissuenet_cp3` | tissue / multiplexed |
| `livecell_cp3` | label-free / phase live cells |
| `bact_phase_cp3`, `bact_fluor_cp3`, `deepbacs_cp3` | bacteria (phase / fluorescence) |
| `general` | mixed/general |

Also present (legacy / specialized): `CP`, `CPx`, `LC1`–`LC4`, `TN1`–`TN3`,
`neurips_cellpose_default`, `neurips_cellpose_transformer`, `neurips_grayscale_cyto2`,
and the `cyto*torch_*` / `nucleitorch_*` raw checkpoints. The `size_*.npy` files are size
models, not segmentation models — don't pass them as `model`.

> Note: these are raw Cellpose checkpoints, NOT BioImage-Model-Zoo bundles, so they are
> usable here (BIOP wrapper / cellpose CLI) and by TrackMate-Cellpose.

## Environment requirements (already handled in this image)

- **No conda**: on Linux with `env_type = "conda"` the wrapper runs
  `<env_path>/bin/python -m cellpose` directly, so the uv env needs no activation.
- **Models**: only `cyto3` (+ `size_cyto3.npy`) is pre-installed; any other model name above is
  downloaded by Cellpose on first use (needs network once, then cached in `~/.cellpose/models`).
- **tifffile**: the `cellpose` env ships `tifffile>=2025.5.10` (docker/requirements/cellpose.in). The cellpose
  default `2023.2.28` crashes on NumPy 2.0 when reading the big-endian TIFFs ImageJ writes
  (`ndarray.newbyteorder` removed in NumPy 2.0).

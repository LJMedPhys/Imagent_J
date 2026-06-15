---
name: cellpose_documentation
description: Cellpose (BIOP wrapper) is a Fiji/ImageJ plugin for deep-learning instance segmentation of cells and nuclei in 2D — cytoplasm, whole cells, bright-field, and non-star-convex objects where StarDist is weak. It runs Cellpose DIRECTLY (ch.epfl.biop.wrappers.cellpose) and returns the label image in-process as `cp.cellpose_imp`, with NO TrackMate and NO scraping of masks from /tmp. Use the pre-downloaded models in ~/.cellpose/models (cyto3, nuclei, cyto2, tissuenet, livecell, bact_*, cpsam, ...) or your own custom model file. Use this skill for single-image (or per-frame) Cellpose segmentation. For linking objects across TIME (tracking), use TrackMate-Cellpose instead. Read the files listed at the end for the verified API, models, and pitfalls.
---

# Cellpose (BIOP wrapper) — Documentation Index

This is the **direct** Cellpose path: the BIOP wrapper (`ch.epfl.biop.wrappers.cellpose`)
runs Cellpose and hands you the label image **in-process**. It replaces the old
workaround of routing single-image segmentation through TrackMate-Cellpose (which runs a
full tracking pipeline just to segment, then recovers masks from a random `/tmp` directory).

**When to use this skill vs. alternatives**
- **Cellpose (this skill)** — cytoplasm / whole cells / bright-field / irregular (non-star-convex) objects, 2D, single image. The pre-downloaded models cover most cases.
- **StarDist** — star-convex **nuclei** in fluorescence or H&E. Faster, no conda subprocess.
- **TrackMate-Cellpose** — only when you need to **link objects across time frames** (tracking). Not for a still image.

## Scripting in Groovy — The Only Pattern You Need

Cellpose is **not** driven by `IJ.run()` parameter strings. In Groovy, instantiate the
BIOP command, inject the SciJava context, set fields, call `run()`, and read the
output label image off the command object.

```groovy
#@ Context ctx

import ch.epfl.biop.wrappers.cellpose.ij2commands.Cellpose
import ij.IJ
import ij.process.ImageConverter

def imp = IJ.getImage()                       // or IJ.openImage("/path/to.tif")

def cp = new Cellpose()
ctx.inject(cp)                                // REQUIRED — injects LogService/PlatformService
cp.imp              = imp
cp.env_path         = new File("/opt/conda/envs/cellpose")  // cellpose v3.1.1.2 env (conda)
cp.env_type         = "conda"
cp.model            = "cyto3"                  // a pre-downloaded model in ~/.cellpose/models
cp.diameter         = 30f                      // float; expected object diameter in px (0f = auto-estimate, cyto* only)
cp.ch1              = 0                         // channel to segment (0 = grayscale / single channel)
cp.ch2              = 0                         // optional nucleus channel (0 = none)
cp.additional_flags = ""                       // e.g. "--use_gpu" if a GPU is present (this image is CPU-only)
cp.verbose          = Boolean.TRUE             // set TRUE — null would NPE; also logs the exact cellpose command
cp.run()                                       // blocks; runs cellpose as a conda subprocess

def labels = cp.cellpose_imp                   // <-- the instance label image (NO /tmp scraping)
if (labels.getBitDepth() == 32) {              // labels come back 32-bit float (values 1..N)
    ImageConverter.setDoScaling(false)         // CRITICAL: don't rescale, or label IDs get mapped to 0..65535
    IJ.run(labels, "16-bit", "")
    ImageConverter.setDoScaling(true)
}
labels.setCalibration(imp.getCalibration())
labels.show()
```

`cp.cellpose_imp` is a label image where background = 0 and each object = a unique integer
1..N. The number of objects is the max pixel value. There is no ROI Manager step unless you
want one (`IJ.run(labels, "Label image to ROIs", "")`, provided by the same BIOP jar).

## Using your OWN / pre-downloaded custom model

To use a custom model file (e.g. one you trained or downloaded as a single file), set
`model_path` and leave `model` empty:

```groovy
cp.model      = ""
cp.model_path = new File("/home/imagentj/.cellpose/models/my_custom_model")
```

The built-in pre-downloaded models (used via `cp.model = "<name>"`) live in
`/home/imagentj/.cellpose/models`: `cyto3`, `cyto2`, `nuclei`, `general`, `tissuenet_cp3`,
`livecell_cp3`, `bact_fluor_cp3`, `bact_phase_cp3`, `deepbacs_cp3`, `cpsam`, and more.
See `SCRIPT_API.md` for the full list and which env each needs.

## Cellpose-SAM (cpsam) — newest, highest-accuracy model

`cpsam` is the Cellpose 4 (Cellpose-SAM) model — a SAM-based transformer that generally
gives the best, most general segmentation. It uses a **different command and env**:

```groovy
import ch.epfl.biop.wrappers.cellpose.ij2commands.CellposeSAM

def cp = new CellposeSAM()
ctx.inject(cp)
cp.imp              = imp
cp.env_path         = new File("/opt/conda/envs/cellpose4")   // cellpose 4.1.1 (NOT the v3 env)
cp.env_type         = "conda"
cp.model            = "cpsam"
cp.additional_flags = ""                                     // "--use_gpu" if a GPU is present
cp.verbose          = Boolean.TRUE
cp.run()
def labels = cp.cellpose_imp
```

Differences from the v3 `Cellpose` command:
- **No `ch1`/`ch2`** — Cellpose-SAM is channel-agnostic and segments using all channels;
  the `CellposeSAM` command does not expose channel fields (don't set them).
- **`diameter` is ignored** — Cellpose 4 dropped the diameter concept (it logs that the
  flag is deprecated). You may leave the default.
- **Env is `cellpose4`**, which already has a modern tifffile/NumPy 2 stack.
- **Very slow on CPU.** The SAM transformer is heavy; on this CPU-only image even a small
  crop takes several minutes. Use a GPU deployment (`--use_gpu`) for cpsam in practice;
  prefer `cyto3`/`nuclei` (v3) when you only have CPU.

Full runnable cpsam pipeline (open → segment → 16-bit labels + CSV):
`GROOVY_WORKFLOW_CELLPOSE_SAM_SEGMENTATION.groovy`.

## Critical pitfalls (READ before generating a script)

- **conda activation.** The wrapper segments by spawning `bash -c "conda activate <env> && python -m cellpose ..."`. A bare `bash -c` cannot run `conda activate` ("Run 'conda init' first"). In this container that is solved by `BASH_ENV=/opt/conda/etc/profile.d/conda.sh`, set before the JVM starts in `src/imagentj/imagej_context.py`. If you run Fiji standalone for testing, export `BASH_ENV` yourself first.
- **`cp.verbose` must be set** (`Boolean.TRUE`/`FALSE`). It is a `Boolean` (nullable); leaving it null can NPE in `run()`. TRUE also prints the exact cellpose command + cellpose's own log — invaluable for debugging.
- **Labels come back 32-bit — convert to 16-bit WITHOUT scaling.** `IJ.run(labels, "16-bit", "")` alone *rescales* pixel values to 0..65535 and destroys the integer label IDs (a verified trap: a 15-object image reported a max label of 65535). Always wrap it: `ImageConverter.setDoScaling(false)` → convert → `setDoScaling(true)`. Needed for MorphoLibJ / Analyze Particles / saving a normal label TIFF.
- **Calibration is lost** on the cellpose output — re-apply `labels.setCalibration(imp.getCalibration())` before any measurement.
- **CPU is slow.** cellpose-v3 cyto3 on CPU is ~minutes for a ~1 MP image (the flow-dynamics step dominates). Crop/downsample for quick checks; add `--use_gpu` to `additional_flags` only if the deployment has a GPU. This image (`agenticj:cpu-local`) is CPU-only.
- **Channels.** `ch1` is the channel to segment; for a single-channel/grayscale image use `0`. For a 2-channel cyto image, `ch1` = cytoplasm channel, `ch2` = nucleus channel (cellpose's 1-based channel convention as exposed by the wrapper; `0` = none/grayscale).
- **cpsam / Cellpose-SAM** uses a different command (`CellposeSAM`) and env (`cellpose4`) — see the dedicated section above. The `cyto3`/`nuclei` v3 path is the default on CPU; cpsam is GPU-ideal.

## Files — and which workflow to use

**Pick the workflow by model:**
- **v3 models** (`cyto3`, `nuclei`, `cyto2`, `tissuenet_cp3`, `livecell_cp3`, `bact_*`, custom) →
  `GROOVY_WORKFLOW_CELLPOSE_SEGMENTATION.groovy` (the `Cellpose` command, `cellpose` env). **Default on CPU.**
- **cpsam** (Cellpose-SAM, Cellpose 4) →
  `GROOVY_WORKFLOW_CELLPOSE_SAM_SEGMENTATION.groovy` (the `CellposeSAM` command, `cellpose4` env). Newest/most accurate, **GPU-ideal** — very slow on CPU.

The two are NOT interchangeable: cpsam uses a different command + env, has no `ch1`/`ch2`, and ignores `diameter`. Don't copy v3 fields into the cpsam script (setting `ch1`/`ch2` on `CellposeSAM` throws).

| File | What it covers |
|------|---------------|
| `SCRIPT_API.md` | Complete Groovy API: every field on the `Cellpose`/`CellposeSAM` commands, env config, the full pre-downloaded model list + which conda env each needs, output handling |
| `GROOVY_WORKFLOW_CELLPOSE_SEGMENTATION.groovy` | **v3 models.** Verified ready-to-run: open image → BIOP `Cellpose` → 16-bit label image + per-label area/centroid CSV; `FINAL STATUS:` convention; tested to produce 97 objects on a DAPI crop with cyto3 |
| `GROOVY_WORKFLOW_CELLPOSE_SAM_SEGMENTATION.groovy` | **cpsam (Cellpose-SAM).** Same pipeline via the `CellposeSAM` command + `cellpose4` env; no `ch1`/`ch2`/`diameter`. Verified end-to-end (valid 16-bit label image). GPU strongly recommended — a 256px crop took ~23 min on this CPU-only image |

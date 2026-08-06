---
name: cellpose_documentation
description: >-
  Cellpose (BIOP wrapper) is a Fiji/ImageJ plugin for deep-learning instance segmentation of cells
  and nuclei in 2D — cytoplasm, whole cells, bright-field, and non-star-convex objects where StarDist
  is weak. It runs Cellpose DIRECTLY (ch.epfl.biop.wrappers.cellpose) and returns the label image
  in-process as `cp.cellpose_imp` — no TrackMate, no scraping masks from /tmp. Route a SEGMENTATION
  step here for a single still image or for per-frame masks; for LINKING objects across TIME
  (tracking), use TrackMate-Cellpose instead. Uses the pre-downloaded models in ~/.cellpose/models
  (cyto3, nucleitorch_0, cyto2, tissuenet, livecell, bact_*, cpsam, ...) or a custom model file.
  Read the files listed at the end for the verified API, the model list, `additional_flags` syntax,
  bright-field handling, and pitfalls.
---

# Cellpose (BIOP wrapper) — Documentation Index

The **direct** Cellpose path: the BIOP wrapper (`ch.epfl.biop.wrappers.cellpose`) runs Cellpose and hands you the label image **in-process** as `cp.cellpose_imp` — no TrackMate, no scraping masks from `/tmp`.

**When to use this vs. alternatives**
- **Cellpose (this skill)** — cytoplasm / whole cells / bright-field / irregular (non-star-convex) 2D objects, single image.
- **StarDist** — star-convex **nuclei** (fluorescence / H&E); faster, no conda subprocess.
- **TrackMate-Cellpose** — only to **link objects across time** (tracking), not for a still image.

## Which model — decide by GPU first

Check the GPU state (`check_environment`, query `"cuda"` → the **CUDA** row), then choose:

- **GPU active → prefer `cpsam` (Cellpose-SAM / Cellpose 4).** It is the most accurate, most general model. Use the **`CellposeSAM` command + `cellpose4` env** (see the Cellpose-SAM section).
- **CPU only → prefer a v3 model (`cyto3`, `nucleitorch_0`, …).** cpsam is far too slow on CPU. Use the **`Cellpose` command + `cellpose` env** (the main template below).

In one line: **cpsam is the default whenever the GPU is on; v3 (cyto3/nuclei) is the fallback** — and the preferred choice on CPU-only deployments.

## The one pattern you need — copy it, keep it linear

> **DO NOT** wrap the cellpose call in a helper method, add GPU→CPU fallback branches, or depend on a pre-opened window. Every past failure came from exactly these. `--use_gpu` already falls back to CPU on its own. Keep the call in the **main script body**; if a run fails, simplify *toward* this template — don't add structure.

```groovy
#@ Context ctx

import ch.epfl.biop.wrappers.cellpose.ij2commands.Cellpose
import ij.IJ
import ij.process.ImageConverter

def imp = IJ.openImage("/app/data/your_image.tif")   // robust for scripts; use IJ.getImage() only for the active window
if (imp == null) { println("FINAL STATUS: FAILURE - could not open image"); return }

def cp = new Cellpose()
ctx.inject(cp)                                        // REQUIRED — injects LogService/PlatformService
cp.imp              = imp
cp.env_path         = new File("/opt/conda/envs/cellpose")  // cellpose 3.1.1.2 (v3 models: cyto3, nucleitorch_0, ...)
cp.env_type         = "conda"
cp.model            = "cyto3"                          // v3 model (CPU-preferred). On GPU, prefer cpsam — see Cellpose-SAM below
cp.diameter         = 30f                              // px; 0f = auto-estimate (cyto* only)
cp.ch1              = 0                                // channel to segment (0 = grayscale)
cp.ch2              = 0                                // optional nucleus channel (0 = none)
cp.additional_flags = "--use_gpu"                     // COMMA-separated flags AND values, never spaces (see SCRIPT_API.md)
cp.verbose          = Boolean.TRUE                    // MUST set (nullable → NPE); also logs the exact cellpose command
cp.run()

def labels = cp.cellpose_imp
if (labels == null) {                                 // cellpose subprocess failed — read the verbose log above
    println("FINAL STATUS: FAILURE - cellpose returned null (see cellpose log)")
    return
}
if (labels.getBitDepth() == 32) {                     // 32-bit float labels → 16-bit WITHOUT scaling,
    ImageConverter.setDoScaling(false)                // else IDs are remapped to 0..65535 and destroyed
    IJ.run(labels, "16-bit", "")
    ImageConverter.setDoScaling(true)
}
labels.setCalibration(imp.getCalibration())           // cellpose drops calibration
labels.show()
println("FINAL STATUS: SUCCESS")
```

`cp.cellpose_imp` is a label image: background = 0, each object a unique integer 1..N (max pixel value = object count). For ROIs: `IJ.run(labels, "Label image to ROIs", "")` (same BIOP jar).

## Flags (`additional_flags`) — comma-separated, always

**This is the single most common way to break a Cellpose script.** The wrapper does
`additional_flags.split(",")` and passes the trimmed tokens to the cellpose CLI as argv. It
splits on **commas only, never on whitespace**. Every flag *and every value* is its own token:

```groovy
cp.additional_flags = "--use_gpu, --cellprob_threshold, -1.0, --flow_threshold, 0.4"  // CORRECT
cp.additional_flags = "--use_gpu --cellprob_threshold -1.0 --flow_threshold 0.4"      // WRONG
```

The wrong form does not report a flag error. cellpose's argparse rejects the whole blob with
`error: unrecognized arguments` and exits, so no masks are written, `cp.cellpose_imp` is
**null**, and the next access throws `NullPointerException ... "cellpose_t_imp" is null`. A
lone `"--use_gpu"` works only because it contains no spaces — scripts look fine until a second
flag is added.

`flow_threshold` and `cellprob_threshold` are **not fields**; `cp.flow_threshold = 0.6` throws
`MissingPropertyException`. They exist only as flags.

**Tuning (the directions are not symmetric):**

| Flag | Default | Effect |
|------|---------|--------|
| `--cellprob_threshold` | `0` (range ~ −6…6) | **lower → more and larger masks**; higher → fewer, smaller |
| `--flow_threshold` | `0.4` (range 0…~1) | flow-error QC. **higher → *more* masks pass (looser)**; lower → stricter; `0` disables |

Too many spurious background objects → raise `cellprob_threshold`, lower `flow_threshold`.
Cells split or clipped → lower `cellprob_threshold`. Raising both is the classic mistake:
raising `flow_threshold` *loosens*, it does not tighten. Full details → `SCRIPT_API.md`.

## Bright-field with a bright background (dark cells)

Cellpose expects objects **brighter** than their background. On bright-background data it will
happily segment the background instead of the cells. Invert before segmenting:

```groovy
IJ.run(imp, "Invert", "")    // then assign cp.imp = imp
```

With the v3 `Cellpose` command you may instead pass `--invert` in `additional_flags`. With
`CellposeSAM`/`cpsam` you **cannot** — `--invert` is deprecated and silently ignored in
cellpose ≥ 4.0.1, so the ImageJ-side invert is the only option.

Related: ImageJ's `Subtract Background...` assumes a *dark* background unless you pass the
`light` option. Omitting it on bright-background data estimates the background envelope from
the cells themselves and destroys them.

## GPU vs CPU

`additional_flags` selects it: `"--use_gpu"` (default) uses the GPU when present and **falls back to CPU automatically**; `""` forces CPU (use to avoid GPU contention on a shared node). Safe to leave `--use_gpu` on everywhere. To confirm the container's actual state, call `check_environment` (query `"cuda"`) and read the **CUDA** row. On GPU, cellpose logs `>>>> using GPU (CUDA)`.

**Speed & model choice:** GPU ≈ seconds → **prefer cpsam** there. On CPU, cyto3 is ~minutes per ~1 MP image (flow-dynamics dominates) and **cpsam is far too slow** (many minutes even for a small crop) → **prefer `cyto3`/`nucleitorch_0`** on CPU.

## Setting `diameter` from user-drawn ROIs (stock v3 models)

On a **non-fine-tuned** v3 model (`cyto3`, `nucleitorch_0`, …) `diameter` is the single
biggest accuracy lever: cellpose rescales the image by `diameter / training_diameter`
(30 px for cyto\*, 17 px for nuclei), so a wrong value shrinks or inflates every object
before the network ever sees it. When the user is unsure of the value, measure it instead
of guessing:

1. Ask the user to open the image in Fiji, pick the **polygon** or **freehand** selection
   tool, outline **~8–15 representative objects** — whatever they actually want segmented
   (whole cell outline, or just the nucleus) — pressing **`T`** after each to add it to the
   ROI Manager.
2. Call **`estimate_cellpose_diameter()`**. It reads every ROI, converts each to an
   equivalent circular diameter `2*sqrt(area/pi)` **in pixels**, and returns the
   distribution plus a recommendation.
3. Pass the returned value(s) as `cp.diameter`.

The headline number is `diameter_from_median_area_px` — the **median** area converted, not
the mean. Averaging areas first is fragile: `sqrt` is concave, so the mean-area variant is
dominated by the largest outlines (one oversized polygon among 11 tight ~30 px nuclei pulled
it to 42.7 px, vs a correct 30.0 px from the median).

Since `d = 2*sqrt(A/pi)` is monotonic, for an **odd** number of ROIs this is exactly the
median of the per-ROI diameters. For an **even** count the two middle values get averaged,
and averaging areas ≠ averaging their diameters — normally a rounding-level difference, but
it widens when the two middle ROIs straddle a size gap (measured: 43.0 vs 48.3 px on a
bimodal 12-ROI set). That only happens when the population is genuinely bimodal, where a
single diameter is the wrong answer regardless and the two-run split below takes over.

`diameter = 0f` (auto-estimate) is the alternative, but it needs a `size_*.npy` size model
and is often less reliable than a handful of honest outlines — prefer measured ROIs when
the user can draw them.

> **Why pixels matter here.** ImageJ reports `ImageStatistics.area` in *calibrated* units on
> a calibrated image, but cellpose's `diameter` is *always* px. On a 0.645 µm/px image a
> 40×40 px ROI reports `area = 665.64` (µm²) while `pixelCount = 1600` — using the former
> gives 29.1 px instead of 45.1 px, a silent **1.55× error** squarely in the range that
> degrades segmentation. `estimate_cellpose_diameter` sources `pixelCount` for this reason;
> if you ever compute a diameter in a Groovy script yourself, do the same.

### One run or two?

If objects vary a lot in size, one `diameter` cannot serve them all and the extremes get
missed. The tool decides on the metric that actually governs cellpose quality — **the ratio
`d / diameter` per object**, not an abstract spread score:

- It computes what fraction of objects a single (median) diameter would scale outside
  `[1/1.5, 1.5]` — the `scale_tolerance`.
- **≤ 25 % outside → one run** at the median diameter.
- **> 25 % outside → try splitting** into two size groups (exact 1-D 2-means on *log*
  diameters, so a 2× gap counts the same at 20 px as at 200 px). It recommends two runs
  only if both groups are substantial (≥ 15 % of ROIs, ≥ 2 objects), the two centres are
  ≥ `scale_tolerance` apart, and splitting genuinely lowers the mis-scaled fraction —
  otherwise a couple of outliers or one broad continuous spread would trigger a pointless
  second run.

Both cutoffs (`scale_tolerance=1.5`, `max_out_of_tolerance=0.25`) are **tunable heuristics**,
grounded in how the rescaling works rather than measured from a benchmark — cellpose
tolerates roughly a 1.5× size error before quality visibly drops. Treat them as a starting
point and loosen/tighten per dataset.

**For two runs:** run the template below twice with the two diameters, saving each label
image, then call **`merge_cellpose_diameter_runs()`** to combine them. Do **NOT** add, `max`,
or otherwise combine the two label images by hand — IDs from the two runs collide, so
addition invents objects with fused IDs and `max` silently merges touching neighbours.

The merge resolves the fact that both runs detect some of the same physical cells:

1. Every object is measured and assigned to the run it *should* have come from, split at the
   **geometric** mean of the two diameters (geometric, because cellpose scaling error is
   multiplicative).
2. Candidates are accepted best-first, scored by `|log(ecd / own run's target)|`.
3. A candidate is dropped as a duplicate if the overlap test fails in **either** direction —
   more than `overlap_threshold` of its own pixels are already claimed (a finer duplicate),
   **or** it would swallow that much of an already-accepted object (a coarser duplicate,
   e.g. the large-diameter run fusing several small cells the small run resolved correctly).
   The bidirectional check matters: a big fused blob covers only a small fraction of *its
   own* area, so a one-directional test lets it through on top of the correct objects.
4. A final pass re-admits any object assigned away in step 1 that overlaps nothing accepted,
   so a cell found by only one run — on the "wrong" side of the size boundary — is not lost.

Output is a sequential `uint32` label image (0 = background), ready for
`regionprops_table` / `cp_measure` like any other mask.

## Custom / pre-downloaded models

Set `model_path`, leave `model` empty:
```groovy
cp.model = ""
cp.model_path = new File("/home/imagentj/.cellpose/models/my_model")
```
Built-ins live in `/home/imagentj/.cellpose/models`: `cyto3`, `cyto2`, `nucleitorch_0`, `tissuenet_cp3`, `livecell_cp3`, `bact_*`, `cpsam`, … (full list + which env each needs → `SCRIPT_API.md`). Note: cyto3/nuclei expect microscopy images — on a non-cell image (e.g. a photo) they legitimately find ~0 objects; that is not a failure.

## Custom / fine-tuned models the user provides

The user's own fine-tuned Cellpose model files (e.g. from `cellpose --train`) belong in
`/app/data/fine-tuned-models/` (host: `./data/fine-tuned-models`) — never write a script that
asks the user to place a model file directly under `/home/imagentj/.cellpose/models` (that's a
named Docker volume, not something they can reach from a normal file browser). Two ways to use
a file once it's there, with different readiness:

- **`cp.model_path = new File("/app/data/fine-tuned-models/<file>")`** — works immediately, no
  restart. `model_path` accepts any existing path directly; nothing needs registering.
- **`cp.model = "<file>"`** — same bare-name convention as `cyto3`/`nucleitorch_0`, but only
  works **after the container has been restarted once** since the file was added. On every
  start, `docker-entrypoint.sh` symlinks each file in `data/fine-tuned-models/` into
  `~/.cellpose/models/` AND registers its name in `~/.cellpose/models/gui_models.txt` — both
  are required for cellpose to resolve a bare name (verified from the installed package's
  `cellpose/models.py`: `get_model_params()` matches `model_type` against built-ins plus every
  line in `gui_models.txt`, THEN expects the file at `~/.cellpose/models/<name>` — a symlink
  with no `gui_models.txt` entry, or vice versa, does not work).

**Expected file format:** a raw PyTorch `state_dict` (`torch.save(model.state_dict(), path)`) —
verified from both loaders (`resnet_torch.py` for v3, `vit_sam.py` for cpsam): both call
`torch.load(filename, weights_only=True)` then `load_state_dict(...)`, which rejects anything
that isn't a plain tensor dict (no full pickled model, ONNX, or safetensors). The state dict's
key names must match the architecture it was fine-tuned from — **v3 and cpsam are not
interchangeable**: a v3-fine-tuned file (keys like `output.2.weight`) only loads through the
`Cellpose` command (`env_path = .../envs/cellpose`); a cpsam-fine-tuned file only loads through
`CellposeSAM` (`env_path = .../envs/cellpose4`). Loading one through the wrong command's env
raises a `state_dict` key-mismatch error, not a clear "wrong model type" message — if a custom
model fails immediately on load with missing/unexpected key errors, check which command was
used before assuming the file is corrupt. A companion `size_<file>.npy` is optional (enables
`diameter=0` auto-estimate, same as `size_cyto3.npy`); without it just pass `cp.diameter`.

If the user just added a file and a script fails with "model not found" for a bare name, that
almost always means the container hasn't been restarted since — prefer `model_path` if you
can't ask them to restart, or tell them to restart first.

## Cellpose-SAM (cpsam) — newest, most general model (prefer this when the GPU is active)

The default choice on a GPU deployment. Use the **`CellposeSAM` command + `cellpose4` env** (cellpose 4.1.1), NOT the v3 `Cellpose`:
```groovy
import ch.epfl.biop.wrappers.cellpose.ij2commands.CellposeSAM
def cp = new CellposeSAM()
ctx.inject(cp)
cp.imp              = imp
cp.env_path         = new File("/opt/conda/envs/cellpose4")
cp.env_type         = "conda"
cp.model            = "cpsam"
cp.additional_flags = "--use_gpu"     // COMMA-separated flags AND values — see the Flags section
cp.verbose          = Boolean.TRUE
cp.run()
def labels = cp.cellpose_imp   // then null-guard + 16-bit convert exactly as in the main template
```
Differences from v3:
- **No `ch1`/`ch2`** — they are declared on the v3 `Cellpose` class only, so setting them on `CellposeSAM` throws `MissingPropertyException`. cpsam is channel-agnostic.
- **`diameter` exists but leave it at the default.** It is inherited from the shared parent class and the wrapper *always* forwards it (`--diameter 30.0`). Cellpose 4 uses it to rescale the image to its 30 px training diameter, so the default is a no-op — but a non-30 value **does** change the result. It is not "ignored".
- **GPU strongly preferred** — cpsam is very slow on CPU.
- **`--invert` does not work** (deprecated in cellpose ≥ 4.0.1). Invert in ImageJ instead.

## Pitfalls (read before generating a script)

- **No helper methods.** In Fiji's SciJava Groovy runner (`#@`-param scripts) a script-level `def`/`final` — even `@Field` — is NOT reliably visible inside a method body: referencing it throws `MissingPropertyException: No such property: X for class: script`, so `cp.run()` never happens and you get a downstream `cellpose_imp is null` NPE. Keep the call in the main body, or pass everything (`env_path`/`model`/`diameter`/`ch1`/`ch2`/flags) as method arguments.
- **`additional_flags` is COMMA-separated, never space-separated** — `"--use_gpu, --cellprob_threshold, -1.0"`, not `"--use_gpu --cellprob_threshold -1.0"`. The space form makes cellpose exit with `unrecognized arguments`, which surfaces only as null labels + `NullPointerException ... "cellpose_t_imp" is null`. Never diagnose that NPE as "bad threshold value" — check the flag string first.
- **`cellprob_threshold` / `flow_threshold` are flags, not fields.** `cp.flow_threshold = 0.6` throws `MissingPropertyException`.
- **Bright background (bright-field) → invert first.** Cellpose segments the background otherwise. `--invert` is a no-op on cpsam.
- **Always null-guard `cp.cellpose_imp`** before `getBitDepth()` (see template) — a null means the cellpose subprocess failed; check the verbose log, don't NPE.
- **`cp.verbose` MUST be set** (`Boolean.TRUE`) — it is nullable and null NPEs in `run()`.
- **32-bit labels → 16-bit WITHOUT scaling** (wrap the conversion in `setDoScaling(false)`/`(true)`), or label IDs are remapped to 0..65535 and destroyed.
- **Calibration is lost** on the output — re-apply `labels.setCalibration(imp.getCalibration())`.
- **conda activation** is handled by `BASH_ENV=/opt/conda/etc/profile.d/conda.sh` (set in `src/imagentj/imagej_context.py`); export it yourself only if running Fiji standalone.
- **Channels** use the wrapper's 1-based convention; `0` = none/grayscale.

## Files

| File | What it covers |
|------|---------------|
| `SCRIPT_API.md` | Full field reference for `Cellpose`/`CellposeSAM`, **flag syntax + threshold tuning**, bright-field handling, env config, the complete pre-downloaded model list, output handling |
| `GROOVY_WORKFLOW_CELLPOSE_SEGMENTATION.groovy` | **v3 models** — verified end-to-end: open → `Cellpose` → 16-bit labels + per-label area/centroid CSV |
| `GROOVY_WORKFLOW_CELLPOSE_SAM_SEGMENTATION.groovy` | **cpsam** — `CellposeSAM` + `cellpose4` env; no `ch1`/`ch2`, leave `diameter` alone |

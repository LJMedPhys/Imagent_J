---
name: micro_sam
description: >-
  micro_sam ("Segment Anything for Microscopy") is a napari plugin + Python API that brings the SAM
  foundation model to microscopy, with models finetuned for light microscopy (LM), electron microscopy
  (EM), histopathology and medical imaging. Route a SEGMENTATION step here when there is NO trained
  StarDist/Cellpose model for the object, when objects are arbitrary/novel, when the data are difficult
  (EM, low contrast), or when the user wants promptable, human-in-the-loop, correctable segmentation.
  Prefer StarDist/Cellpose for standard nuclei and cells (faster, often better) — micro_sam is the
  specialist for the hard, novel or interactive cases. Installed in the `napari-mcp` conda env. TWO
  backends: interactive in the live napari viewer (backend "napari"), or headless batch (backend
  "python_data_analyst", first line `# imagentj-env: napari-mcp`). The model table, the annotator
  commands and the batch API are in the files listed at the end.
---

# micro_sam — Segment Anything for Microscopy

`micro_sam` wraps Meta's **Segment Anything (SAM)** with microscopy-finetuned models and a napari
annotation UI. It does **instance segmentation**: interactively (click a point / draw a box → mask,
then correct), or automatically over the whole image. Installed in the **`napari-mcp`** env.

**When the plugin_manager should route here** (see also `../napari_general/SKILL.md`):
- No pretrained StarDist/Cellpose model fits the object (novel/arbitrary structures).
- Difficult data where StarDist/Cellpose underperform (EM, low SNR, unusual textures).
- The user wants **promptable** or **human-in-the-loop, correctable** segmentation.
- **Do NOT** default here for ordinary fluorescence nuclei or cells — StarDist / Cellpose (BIOP)
  via `imagej_coder` are faster and usually more accurate for those.

## Backend A — headless / batch (python_data_analyst, env `napari-mcp`)

The analyst writes a script whose FIRST line selects the env. `get_predictor_and_segmenter` builds the
model once; `automatic_instance_segmentation` returns a label image (and can save it).

```python
# imagentj-env: napari-mcp
import numpy as np, tifffile
from micro_sam.automatic_segmentation import (
    get_predictor_and_segmenter, automatic_instance_segmentation,
)

image = tifffile.imread("/app/data/projects/demo/raw_images/cells.tif")   # 2D grayscale or RGB

import torch
# Pick the backbone from the hardware, don't hard-code it: vit_b_lm is ~9x larger
# and far slower to embed on CPU. See "Model selection" below.
MODEL = "vit_b_lm" if torch.cuda.is_available() else "vit_t_lm"

predictor, segmenter = get_predictor_and_segmenter(
    model_type=MODEL,             # vit_t_lm on CPU builds, vit_b_lm on GPU
    device=None,                  # None auto-selects the GPU when available, else CPU.
                                   # Do NOT hard-code "cuda" — it crashes on the CPU-only image.
    segmentation_mode="ais",      # decoder-based Automatic Instance Segmentation (recommended)
)
labels = automatic_instance_segmentation(
    predictor=predictor, segmenter=segmenter,
    input_path=image,             # a numpy array OR a file path
    ndim=2,                       # REQUIRED when input_path is an array
    output_path="/app/data/projects/demo/processed/cells_masks.tif",  # optional: also writes the mask
    verbose=False,
)
print("objects:", len(np.unique(labels)) - 1)
```

The returned `labels` is a standard integer label image — feed it straight to `python_data_analyst`
Stage 0 measurement (`skimage.measure.regionprops_table` or `cp_measure`) exactly like a StarDist/
Cellpose mask.

## Backend B — interactive in the live napari viewer (supervisor via napari MCP)

> ### THE ONE RULE: never compute inside `mcp__napari_mcp__execute_code`
>
> That tool runs your code **on napari's main Qt thread**, wrapped in a hard
> `IMAGENTJ_MCP_TOOL_TIMEOUT_SECONDS` timeout (**90 s** default). So anything slow —
> model build, embeddings, segmentation — has two failure modes at once:
> the event loop stalls (viewer + whole VNC desktop freeze, no progress bar), AND the
> call dies with `TimeoutError` while the work keeps running invisibly in the server.
>
> Meanwhile `python_data_analyst` with `# imagentj-env: napari-mcp` runs in a
> supervised subprocess with a **7200 s** limit (`IMAGENTJ_SCRIPT_HARD_TIMEOUT`),
> covered by the stop button and the memory watchdog — **80x the headroom, and
> interruptible**. It is the same conda env, so the model and results are identical.
>
> **Route every heavy step there, and let MCP do only what is instant: adding a layer.**

### Pattern 1 — automatic segmentation (two steps)

**Step 1 — compute in `python_data_analyst`** (supervised, not the viewer):
```python
# imagentj-env: napari-mcp
import tifffile, torch, numpy as np
from micro_sam.automatic_segmentation import get_predictor_and_segmenter, automatic_instance_segmentation

IMG  = "/app/data/projects/demo/raw_images/cells.tif"
MASK = "/app/data/projects/demo/processed/cells_masks.tif"
MODEL = "vit_b_lm" if torch.cuda.is_available() else "vit_t_lm"

img = tifffile.imread(IMG)
predictor, segmenter = get_predictor_and_segmenter(model_type=MODEL, device=None, segmentation_mode="ais")
labels = automatic_instance_segmentation(
    predictor=predictor, segmenter=segmenter, input_path=img, ndim=2,
    output_path=MASK, verbose=False,
)
print("objects:", len(np.unique(labels)) - 1)
```

**Step 2 — display it via MCP** (a file read + a layer add; milliseconds):
```python
# code passed to mcp__napari_mcp__execute_code
import tifffile
img    = tifffile.imread("/app/data/projects/demo/raw_images/cells.tif")
labels = tifffile.imread("/app/data/projects/demo/processed/cells_masks.tif")
viewer.add_image(img, name="raw")
viewer.add_labels(labels.astype("uint32"), name="micro_sam")   # user can now correct it
```
(`viewer` is pre-bound inside napari-mcp's execute_code.)

### Pattern 2 — click-prompted annotator (human corrects with points/boxes)

The annotator cannot compute embeddings on the Qt thread without freezing — so
**precompute them to disk first**, then point the annotator at that cache.

**Step 1 — precompute embeddings in `python_data_analyst`:**
```python
# imagentj-env: napari-mcp
import torch
from micro_sam.precompute_state import precompute_state

MODEL = "vit_b_lm" if torch.cuda.is_available() else "vit_t_lm"
precompute_state(
    input_path="/app/data/projects/demo/raw_images/cells.tif",
    output_path="/app/data/projects/demo/processed/embed.zarr",   # the embedding cache
    model_type=MODEL,
    ndim=2,
)
```

**Step 2 — open the annotator against that cache via MCP** (loads, does not compute):
```python
from micro_sam.sam_annotator import annotator_2d
import tifffile, torch
img = tifffile.imread("/app/data/projects/demo/raw_images/cells.tif")
MODEL = "vit_b_lm" if torch.cuda.is_available() else "vit_t_lm"
annotator_2d(img, model_type=MODEL, viewer=viewer,
             embedding_path="/app/data/projects/demo/processed/embed.zarr",
             return_viewer=True)
```

`embedding_path` is **required practice here, not an optimisation** — without it the
annotator recomputes embeddings on the Qt thread and you are back to a frozen viewer.
Reuse the same path across sessions on the same image and startup is near-instant.

`precompute_state` also takes `precompute_amg_state=True`, which additionally caches the AMG/AIS
**decoder** state (speeds up a later "Automatic Segmentation" click in-session) — it does **NOT**
touch the ~60 s model-weight loading below, so it does not help with the 90 s MCP timeout risk.
Embeddings + a raised timeout are the only fix for that.

`return_viewer=True` is **mandatory over MCP**. Without it `annotator_2d` ends by calling
`napari.run()`, which blocks until the user closes the annotator window — so the tool call
can never return while annotation is in progress. No timeout value fixes that; the call is
designed never to return. Worse, the resulting bare `TimeoutError` kills the entire agent
turn, so you get no usable error back — just a blank "Agent error".
With `return_viewer=True` the annotator docks into the viewer `init_viewer` already created
and the call returns, leaving the widget live for the user to annotate in VNC. A second
`napari.run()` event loop would be wrong here in any case.

**Budget ~85 s for the launch, and raise the MCP cap before calling.** `return_viewer=True`
alone is not enough: `initialize_predictor` always rebuilds the model via `util.get_sam_model`
(there is no way to inject a cached predictor), and that call alone measures **~60 s for
`vit_t_lm`** — on GPU *and* CPU; it is state-dict loading, not device transfer. Measured
end-to-end through MCP with embeddings precomputed, the full `annotator_2d` launch took
**83.9 s** — inside the 90 s default by ~6 s, i.e. it straddles the limit and fails on a
slow run. Set `IMAGENTJ_MCP_TOOL_TIMEOUT_SECONDS=300` (the adapter hard-clamps to 600)
before launching an annotator. A larger backbone such as `vit_b_lm` will exceed 90 s outright.

The plugin is also in the napari GUI: **Plugins → Segment Anything for Microscopy**. After the user
finishes, save the committed label layer to a TIFF so the next pipeline step can read it.

**Guiding a human through the UI → read `UI_GUIDE.md`.** It covers the annotator end-to-end for a
napari beginner: Compute Embeddings first (nothing works before it), click a point → `S` to segment →
`T` to toggle negative prompts for corrections → `C` to commit each object into `committed_objects`
(the only permanent layer), `Shift+S` to propagate through a 3D volume, plus shortcuts and embedding
caching.

## Model selection

`model_type` = a SAM backbone (`vit_t` < `vit_b` < `vit_l` < `vit_h`, bigger = slower + more accurate)
optionally suffixed with a domain finetune:

| Suffix | Domain | `vit_t`? | Use for |
|---|---|---|---|
| `_lm` | Light microscopy | ✅ **baked** | Fluorescence / brightfield cells & nuclei — **the default** |
| `_em_organelles` | Electron microscopy | ✅ **baked** | Organelles / structures in EM |
| `_histopathology` | H&E histopathology | ❌ none — `vit_b` is the floor (~419 MB) | Stained tissue sections |
| `_medical_imaging` | Medical | ❌ none — `vit_b` is the floor (~772 MB) | CT / MRI-style data |
| *(none)* | Natural-image SAM | ✅ but **no AIS decoder** | Non-microscopy fallback only |

**`vit_t` does not exist for every domain.** LM and EM have a tiny variant (both pre-baked);
histopathology and medical imaging start at `vit_b` and must be downloaded before use.

`segmentation_mode`: `"ais"` (decoder-based Automatic Instance Segmentation — recommended, uses the
`*_lm`/`*_em` finetuned decoder) · `"amg"` (Automatic Mask Generation — original SAM, slower, no
finetuned decoder) · `"apg"`. Default picks AIS when a decoder model is available.

> **Model choice and `segmentation_mode` are coupled — the un-suffixed models have NO decoder.**
> With a generic `vit_t`/`vit_b`/`vit_l`/`vit_h`, `segmentation_mode="ais"` raises
> `RuntimeError: ...your model does not contain a decoder`, and `segmentation_mode=None` silently
> falls back to `"amg"`. That fallback is the usual cause of an automatic run blowing past the
> 90 s MCP timeout: AIS is ~one decoder pass per image, while AMG runs the mask decoder over a
> dense grid of point prompts — hundreds to thousands of passes. If automatic segmentation is
> mysteriously slow, check you are on a `_lm`/`_em`-suffixed model, not a generic one.
>
> Interactive point/box prompting works on **every** model, decoder or not — the decoder gap only
> affects automatic mode.

**Fine-tuned / custom weights instead of a stock model:** `get_predictor_and_segmenter(checkpoint=...)`
(batch) or `checkpoint_path=`/`decoder_path=` (interactive annotators — see `SCRIPT_API.md` for the
per-function asymmetry, e.g. `image_series_annotator` has no `decoder_path`). Actually fine-tuning a new
checkpoint (`micro_sam.training`) is a separate, GPU-hours, labeled-data workflow **out of scope for
this skill** — only reach for it if no stock `*_lm`/`*_em`/`*_histopathology` model is remotely usable.

**Before a heavy run, a free sanity check:** the `napari-mcp` env installs `micro_sam.info` as a CLI
command — run it by **full path** (its `bin/` is not on PATH just from the `# imagentj-env` header) in
a `python_data_analyst` script:
`subprocess.run(["/opt/conda/envs/napari-mcp/bin/micro_sam.info"], capture_output=True, text=True)`.
~2 s, prints the installed version, cache directory, every supported model with its checkpoint version
tag, and whether this process actually sees a GPU. Cheaper than finding out 60 s into a launch.

## Pitfalls that actually bite

1. **`vit_t` / `vit_t_lm` (tiny) needs `mobile_sam`.** Without it: `RuntimeError: 'mobile_sam' is
   required for the vit-tiny`. It is installed in this env; if a rebuild drops it, `vit_b_lm` is the
   safe default. Tiny is the **fastest on CPU** — prefer it there once mobile_sam is present.
2. **Two models are PRE-BAKED into the image; everything else downloads on first use.**
   Baked (no download, works offline): **`vit_t_lm`** and **`vit_t_em_organelles`**, each with its AIS
   decoder — the tiny tier, ~162 MB, in `$MICROSAM_CACHEDIR` (`/home/imagentj/.cache/micro_sam`).
   These run on GPU too, so the same cache serves the CPU and GPU builds.

   Any OTHER model downloads on first use (`vit_b_*` ≈ 375 MB + decoder; `vit_b_medical_imaging`'s
   decoder is a 397 MB outlier). **Never let that first call be an interactive one** — a download
   inside `annotator_2d` freezes the viewer with no progress indicator, and an interrupted one leaves
   a partial temp file that never resumes. Warm it from a `# imagentj-env: napari-mcp` script first
   (see the WARNING under Backend B), then work on the verification image.
3. **GPU vs CPU — pass `device=None` and let it auto-select** (`"cuda"` if a GPU is present, else
   `"cpu"`). GPU acceleration is available only in the **GPU image build** (`USE_GPU=true`, which ships
   a CUDA torch); the default CPU image runs micro_sam on CPU. Never hard-code `device="cuda"` — it
   raises `Torch not compiled with CUDA enabled` on the CPU image. CPU is slow, so on CPU prefer the
   tiny `vit_t_lm`; on GPU `vit_b_lm`/`vit_l_lm` are fine. Confirm with `torch.cuda.is_available()`.
4. **`ndim` is REQUIRED when `input_path` is a numpy array** (2 for a plane, 3 for a z-stack). Omitting
   it on an array raises or mis-segments. For a file path it can infer.
5. **Build the model ONCE.** `get_predictor_and_segmenter` loads weights — call it once and reuse
   `(predictor, segmenter)` across a folder, never per image.
6. **The mask is a label image**, not a binary — background is 0, each object a unique integer. Cast to
   `uint32` before `viewer.add_labels`.
7. **Env is `napari-mcp`, not `main`.** A micro_sam script MUST start with `# imagentj-env: napari-mcp`;
   the main env has no micro_sam/torch. Interactive code runs in the same env via napari's execute_code.

## Files

| File | What it covers |
|---|---|
| `UI_GUIDE.md` | **Operating the interactive napari annotator**, written for someone who has never used napari: window/layer orientation, the micro_sam layers (`point_prompts`, `prompts`, `current_object`, `committed_objects`, `auto_segmentation`), the click→`S`→correct→`C` workflow, positive/negative prompts (`T`), 3D `Shift+S` propagation, tracking, keyboard shortcuts, embedding caching, saving results |
| `SCRIPT_API.md` | Verified signatures (`get_predictor_and_segmenter`, `automatic_instance_segmentation`, `precompute_state`, all four annotator widgets incl. `checkpoint_path`/`decoder_path`), the full model-name list, mode semantics, the `micro_sam.info` CLI check, and CLI entry points |
| `WORKFLOW_AUTOMATIC_SEGMENTATION.py` | Batch script (`# imagentj-env: napari-mcp`): folder → per-image label TIFF + object counts CSV, model built once, GPU/CPU auto-select |

---
name: napari_general
description: >-
  napari is the Python-native n-dimensional image viewer in this container. Use it as a ROUTING
  option, not a default. Reach for napari when the task needs (1) fluid viewing of n-D data —
  3D/4D volumes, multi-channel stacks, label/point/shape layers — that Fiji shows awkwardly; or
  (2) the interactive windows of the Cellpose FINE-TUNING workflow (the user picks tiles and DRAWS
  corrections) — see skills/python/cellpose/FINETUNING.md. There is NO foundation-model /
  Segment Anything (micro_sam) segmentation in this deployment. Fiji/ImageJ remains the DEFAULT:
  do NOT use napari to replace Fiji plugins or Cellpose for hands-off batch work, and do NOT use it
  for statistics or plotting. Every napari step that needs CODE is written by python_data_analyst
  with `# imagentj-env: napari-mcp`; the supervisor's mcp__napari_mcp__* tools are for DISPLAY ONLY.
---

# napari — when to route here vs Fiji / Fiji plugins

napari is a fast, **Python-native** viewer for n-dimensional images. In this container it is
provided by the **napari-mcp** server running in the isolated `napari-mcp` env
(`/opt/uv/envs/napari-mcp`: napari + Qt, no deep-learning packages). The viewer opens **lazily** —
nothing appears until the first napari tool call — and shares the same VNC desktop (port 6080) as
Fiji.

napari is a **routing option the plugin_manager can assign to a step**, not the default engine.
Fiji/ImageJ stays the default for bioimage analysis because of its mature, battle-tested plugin
catalogue and reproducible Groovy scripting.

## Decision guide — which software for a step?

| Situation | Route to | Why |
|---|---|---|
| Deep-learning segmentation of cells / nuclei, one image | **Cellpose (BIOP)** via `imagej_coder` (`cellpose_documentation`) | Label image straight into Fiji |
| Deep-learning segmentation over a folder | **Cellpose** Python API via `python_data_analyst`, env `cellpose` (`python/cellpose`) | Model loaded once — far faster |
| Classical segmentation (threshold, watershed, morphology) | **Fiji** (MorphoLibJ, Auto Threshold) via `imagej_coder` | Mature, reproducible |
| Tracking objects across time | **TrackMate** via `imagej_coder` | Purpose-built linking |
| Registration / stitching / tracing | **Fiji** (TurboReg/StackReg, MIST, BigStitcher, SNT) via `imagej_coder` | Proven implementations |
| Quick manual ROI, line profile, one-off measurement | **Fiji itself** (core / UI-guided) | Fastest for a human at the microscope |
| Measurement / feature extraction, ML, stats, plots | **Python** via `python_data_analyst` | scikit-image, cp_measure, scikit-learn, statistics, plotting |
| **The user wants to correct the segmentation by hand / teach the model** | **Cellpose fine-tuning** (`python/cellpose/FINETUNING.md`) — napari windows via `python_data_analyst`, env `napari-mcp` | Hand-drawn annotation of a few tiles, then Cellpose 3 training, measured before use |
| **Viewing 3D/4D volumes, multi-channel overlays, label layers interactively** | **napari** (viewer only) | n-D rendering Fiji handles awkwardly |

Rule of thumb: **prefer a Fiji plugin or a Python package when one clearly fits.** Choose napari for
*n-D visual inspection* or for the fine-tuning windows. A single pipeline may legitimately mix
families — e.g. Fiji-register → Cellpose-segment (Python) → napari-inspect → Python-measure.

## The two napari backends

1. **Display only (backend = "napari")** — the **supervisor** drives the live viewer with the MCP
   tools. This backend is for showing things, never for computing them:
   - `mcp__napari_mcp__add_layer(path)` — open an image/label layer (call once, stop on status=ok)
   - `mcp__napari_mcp__list_layers`, `mcp__napari_mcp__screenshot`, `mcp__napari_mcp__session_information`
   - `mcp__napari_mcp__execute_code(code)` — Python **inside the napari process**; use it ONLY for
     instant work such as `viewer.add_labels(...)`.
   Use in-container paths like `/app/data/...`. On `status=error`, report the exact message.

2. **Everything that needs code (backend = "python_data_analyst", env = "napari-mcp")** — the
   analyst writes a normal Python script whose first line is `# imagentj-env: napari-mcp`. A script
   may open its own napari window (the fine-tuning tile picker and annotator) and block on
   `napari.run()` until the user closes it. That blocking IS the design — the script returning is
   the signal that the human finished. Deep-learning compute (Cellpose) does not run in this env;
   it runs in env `cellpose`, and its label images are then shown here.

### Which backend does what — this split is not optional

`execute_code` runs on napari's **main Qt thread** under a **90 s** timeout
(`IMAGENTJ_MCP_TOOL_TIMEOUT_SECONDS`). The analyst subprocess gets **7200 s**
(`IMAGENTJ_SCRIPT_HARD_TIMEOUT`) plus stop-button and memory-watchdog coverage.

| Do this in the **analyst** | Do this over **MCP** |
|---|---|
| segmentation and any per-pixel compute (env `cellpose` / `main`) | `add_layer`, `viewer.add_image/add_labels` |
| batch over a folder | reading layer state, `list_layers`, `screenshot` |
| **opening a window the user works in** (env `napari-mcp`) | nothing else |
| **fine-tuning Cellpose on the user's annotations** | |

Putting compute in `execute_code` fails **two** ways at once: the viewer and the whole VNC
desktop freeze (no progress bar), *and* the call dies with `TimeoutError` while the work keeps
running invisibly in the server. Compute first in the analyst and write the result to disk (a
label TIFF), then display it over MCP — even for a single image that will be shown interactively.

## What napari is NOT for here

- **Not** a replacement for Fiji's plugin ecosystem or Cellpose in automated pipelines.
- **Not** for statistics or plotting — that is always `python_data_analyst`.
- **Not** for simple thresholding / Analyze Particles — that is core Fiji.
- **No** Segment Anything / micro_sam / promptable segmentation — not installed.

## Files

| File | What it covers |
|---|---|
| `../../python/cellpose/FINETUNING.md` | Teaching Cellpose on the user's own corrections: the four-stage workflow (napari tile picker + drawing annotator), what to tell the human, and the verified pitfalls |

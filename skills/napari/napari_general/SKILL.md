---
name: napari_general
description: >-
  napari is the Python-native n-dimensional image viewer in this container. Use it as a ROUTING
  option, not a default. Reach for napari when the task needs (1) INTERACTIVE, promptable,
  human-in-the-loop segmentation, correction, or FINE-TUNING a model on the user's own
  annotations — that is micro_sam, see the napari/micro_sam skill; (2) fluid viewing of n-D data
  — 3D/4D volumes, multi-channel stacks, label/point/shape layers — that Fiji shows awkwardly; or
  (3) a Python-ecosystem plugin with no Fiji equivalent. Fiji/ImageJ remains the DEFAULT: do NOT
  use napari to replace mature Fiji plugins (StarDist, Cellpose, MorphoLibJ, TrackMate) for
  hands-off batch work, and do NOT use it for statistics or plotting. Every napari step that needs
  CODE — batch AND interactive alike — is written by python_data_analyst with
  `# imagentj-env: napari-mcp`; the supervisor's mcp__napari_mcp__* tools are for DISPLAY ONLY.
---

# napari — when to route here vs Fiji / Fiji plugins

napari is a fast, GPU-accelerated, **Python-native** viewer for n-dimensional images. In this
container it is provided by the **napari-mcp** server running in the isolated `napari-mcp` conda
env. The viewer opens **lazily** — nothing appears until the first napari tool call — and shares the
same VNC desktop (port 6080) as Fiji.

napari is a **routing option the plugin_manager can assign to a step**, not the default engine.
Fiji/ImageJ stays the default for bioimage analysis because of its mature, battle-tested plugin
catalogue and reproducible Groovy scripting.

## Decision guide — which software for a step?

| Situation | Route to | Why |
|---|---|---|
| Established segmentation model (nuclei, cells, membranes), hands-off/batch | **Fiji plugin** (StarDist, Cellpose (BIOP), MorphoLibJ) via `imagej_coder` | Mature, fast, reproducible, no manual clicking |
| Tracking objects across time | **TrackMate** via `imagej_coder` | Purpose-built linking |
| Registration / stitching / tracing | **Fiji** (TurboReg/StackReg, MIST, BigStitcher, SNT) via `imagej_coder` | Proven implementations |
| Quick manual ROI, line profile, one-off measurement | **Fiji itself** (core / UI-guided) | Fastest for a human at the microscope |
| Measurement / feature extraction, ML, stats, plots | **Python** via `python_data_analyst` | scikit-image, cp_measure, scikit-learn, statistics, plotting |
| **Arbitrary/novel objects, no trained model, promptable "segment anything", or interactive correction** | **napari + micro_sam** | SAM foundation model + click prompts; see napari/micro_sam |
| **Segmentation the user wants to steer/correct by hand** | **napari + micro_sam (interactive)** | Human-in-the-loop annotation loop |
| **Viewing 3D/4D volumes, multi-channel overlays, label layers interactively** | **napari** (viewer only) | n-D rendering Fiji handles awkwardly |
| Hands-off SAM segmentation over a folder | **micro_sam batch** via `python_data_analyst` (env `napari-mcp`) | Same model, no GUI, writes label masks |

Rule of thumb: **prefer a Fiji plugin or a Python package when one clearly fits.** Choose napari when
the value is *interactivity/promptability* (micro_sam) or *n-D visual inspection*. A single pipeline
may legitimately mix all three — e.g. Fiji-register → micro_sam-segment (napari) → Python-measure.

## The two napari backends

1. **Display only (backend = "napari")** — the **supervisor** drives the live viewer with the MCP
   tools. This backend is for showing things, never for computing them:
   - `mcp__napari_mcp__add_layer(path)` — open an image/label layer (call once, stop on status=ok)
   - `mcp__napari_mcp__list_layers`, `mcp__napari_mcp__screenshot`, `mcp__napari_mcp__session_information`
   - `mcp__napari_mcp__execute_code(code)` — Python **inside the napari process**; use it ONLY for
     instant work such as `viewer.add_labels(...)`. A guard rejects model builds, embedding
     precomputes, segmentation, training and annotator launches sent here.
   Use in-container paths like `/app/data/...`. On `status=error`, report the exact message.

2. **Everything that needs code (backend = "python_data_analyst", env = "napari-mcp")** — the
   analyst writes a normal Python script whose first line is `# imagentj-env: napari-mcp`. It runs
   in the same env that backs the viewer, so a mask made in a script and a mask made interactively
   come from an identical model. This covers BOTH headless batch work AND interactive sessions:
   a script may open its own napari window (micro_sam annotators, the object classifier, the
   fine-tuning workflow) and block on `napari.run()` until the user closes it. That blocking IS
   the design — the script returning is the signal that the human finished.

### Which backend does what — this split is not optional

`execute_code` runs on napari's **main Qt thread** under a **90 s** timeout
(`IMAGENTJ_MCP_TOOL_TIMEOUT_SECONDS`). The analyst subprocess gets **7200 s**
(`IMAGENTJ_SCRIPT_HARD_TIMEOUT`) plus stop-button and memory-watchdog coverage.

| Do this in the **analyst** (env `napari-mcp`) | Do this over **MCP** |
|---|---|
| model download / build, embedding precompute | `add_layer`, `viewer.add_image/add_labels` |
| automatic segmentation, any per-pixel compute | reading layer state, `list_layers`, `screenshot` |
| batch over a folder | nothing else |
| **opening an annotator the user works in** | |
| **fine-tuning a model on the user's annotations** | |

Putting compute in `execute_code` fails **two** ways at once: the viewer and the whole VNC
desktop freeze (no progress bar), *and* the call dies with `TimeoutError` while the work
keeps running invisibly in the server. Batch is not just "for folders" — it is where **all**
compute belongs, including for a single image that will be shown interactively afterwards.
See `../micro_sam/SKILL.md` → Backend B for the two-step patterns.

## What napari is NOT for here

- **Not** a replacement for Fiji's plugin ecosystem in automated pipelines.
- **Not** for statistics or plotting — that is always `python_data_analyst`.
- **Not** for simple thresholding / Analyze Particles — that is core Fiji.

## Files

| File | What it covers |
|---|---|
| `../micro_sam/FINETUNING.md` | Teaching a model on the user's own corrections: the four-stage workflow, what to tell the human, and the verified pitfalls |
| `../micro_sam/SKILL.md` | The main reason to use napari here: Segment Anything for Microscopy — interactive + automatic instance segmentation, model selection, both backends, pitfalls |

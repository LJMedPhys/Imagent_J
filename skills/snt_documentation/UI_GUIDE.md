# SNT - UI Guide

This guide covers only UI actions described in the official SNT manual, walkthroughs, and analysis documentation.

## Launch

- Start SNT from `Plugins > NeuroAnatomy > SNT...`.
- The startup prompt lets you choose:

| Field | Behavior |
|------|----------|
| `Image / Image file` | Use an already open image or browse for one from disk |
| `Reconstruction file` | Preload a reconstruction file such as `.traces`, `.swc`, `.ndf`, or `.json` |
| `User interface` | Choose which orthogonal views to open for 3D tracing |
| `Tracing Channel` | Choose the image channel for tracing in multichannel data |

If no image is chosen, SNT can open an empty canvas from the reconstruction bounding box.

## Main Interfaces

| Window | Purpose |
|--------|---------|
| `SNT` | Main tracing and path-editing interface |
| `Rec. Viewer` | Interactive 3D viewer for analysis and quantification of reconstructions |
| `Reconstruction Plotter` | 2D rendering utility for illustrations and vector export |

## File and I/O Commands

Noteworthy commands under `File`:

- `Choose Tracing Image... > From Open Image...`
- `Choose Tracing Image... > From File...`
- `Load Tracings > Local Files > TRACES / SWC / NDF / JSON`
- `Load Tracings > Remote Databases`
- `Load Demo Dataset...`
- `Save Tracings...`
- `Export As SWC...`
- `Save Tables & Analysis Plots...`
- `Backup Tracings`

Documented behavior:

- `Load Demo Dataset...` opens a demo image, reconstruction, or both.
- `Save Tracings...` writes a TRACES file.
- `Export As SWC...` exports all traced paths in SWC format.
- `Save Tables & Analysis Plots...` saves analysis tables as CSV and saves generated plots.

## Interactive Tracing Controls

Documented tracing controls include:

| Action | Shortcut | Behavior |
|--------|----------|----------|
| Toggle cursor auto-snapping | `S` | Snap the cursor to the brightest local voxel |
| Undo last temporary segment | `Z` | Remove the last segment from the unfinished path |
| Finish path | `F` | Finalize the temporary path |
| Finish path | double-click | Alternate way to finalize the current path |
| Edit mode | `Shift + E` | Select the nearest path for node-level editing |

Documented tracing options:

- `Cursor Auto-snapping` can be configured for local maxima search volume.
- `Enable A* search algorithm` controls semi-automatic tracing between clicked points.
- If a search is taking too long during tracing, the walkthrough documents canceling it with `C` or `Esc` and placing a closer point.

## Analysis Entry Points

- `Analysis > Measure...` measures complete cells from the main SNT dialog.
- `Path Manager > Analyze > Measurements` measures selected paths only.
- `Analysis > Sholl Analysis...` runs morphology-based Sholl analysis.
- `Analysis > Sholl Analysis (by Focal Point)...` runs Sholl analysis around an exact user-defined focal point.
- `image contextual menu > Sholl Analysis at Nearest Node` runs a node-centered Sholl command near the clicked node.

From the `Neuroanatomy Shortcuts` panel under `Plugins > Neuroanatomy`:

- `Sholl Analysis (Image)`
- `Sholl Analysis (Tracings)`
- `Sholl Analysis Scripts`

## Scripting Entry Points

- `Scripts > New...` from the main SNT dialog opens Fiji's Script Editor with SNT boilerplate or Script Recorder assembly.
- Save a script under `Fiji.app/scripts/` with `SNT` in the filename, then use `Scripts > Reload...`.
- `Scripts > Full List...` shows all discovered scripts.
- `Scripting > Record Script...` from Reconstruction Viewer opens SNT's recorder with boilerplate imports and script parameters.

## Scope Boundary

- This guide does not document an end-to-end macro string for driving SNT dialogs.
- The validated scripted workflow in this repo is the SWC-based analysis path in `GROOVY_WORKFLOW_SWC_ANALYSIS.groovy`.

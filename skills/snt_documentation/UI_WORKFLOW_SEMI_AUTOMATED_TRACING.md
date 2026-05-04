# SNT - UI Workflow: Semi-automated Tracing and Export

## Purpose

Trace a path on a demo dataset, finish the reconstruction segment, and export the result for downstream analysis.

## Prerequisites

- Fiji with the `Neuroanatomy` update site enabled
- SNT installed and available at `Plugins > NeuroAnatomy > SNT...`
- A mouse or trackpad for point placement and stack navigation

## Demo Dataset

Use the built-in SNT sample:

- Launch SNT first
- Then choose `File > Load Demo Dataset...`
- Select `Drosophila OP neuron (Complete 3D reconstruction)`

The official walkthrough notes that this dataset already contains traced paths, so remove or hide paths in `Path Manager` if you want to retrace a subset manually.

## Step 1 - Launch SNT

1. Open SNT from `Plugins > NeuroAnatomy > SNT...`.
2. In the startup prompt, keep the default interface settings or choose the orthogonal views you want for 3D tracing.
3. Click through to open the main SNT dialog.

## Step 2 - Load the Demo Dataset

1. In the SNT main dialog, open `File > Load Demo Dataset...`.
2. Choose `Drosophila OP neuron (Complete 3D reconstruction)`.
3. Wait for the image and reconstruction to load.
4. If the image already contains paths you do not want to keep, remove them from `Path Manager` before starting a new trace.

## Step 3 - Confirm Tracing Aids

1. Keep `Cursor Auto-snapping` enabled unless you want manual node placement.
2. Keep `Enable A* search algorithm` enabled for semi-automatic tracing between clicked points.
3. Move through the stack until the branch you want to trace is clearly visible.

## Step 4 - Start a Path

1. Left-click the first point of the structure to trace.
2. Move along the same neurite or process and left-click a second point.
3. Let SNT compute the connecting path.

If the search takes too long or follows the wrong route:

- cancel the search with `C` or `Esc`
- choose a second point closer to the first one
- use `Z` to undo the last temporary segment when needed

## Step 5 - Extend and Finish the Path

1. Continue placing subsequent points along the same structure.
2. Inspect the provisional path after each segment.
3. Finish the current path with `F` or by double-clicking.

Use `Shift + E` to enter edit mode if you need to select a nearby path for node-level edits.

## Step 6 - Save the Reconstruction

Choose the format that matches the downstream task:

- `File > Save Tracings...` to save all current paths as a TRACES session file
- `File > Export As SWC...` to export all current paths as SWC for morphometry, Sholl analysis, or external tools

## Step 7 - Run Measurements or Sholl Analysis

After tracing or importing a reconstruction:

1. Use `Analysis > Measure...` for tree-level measurements.
2. Use `Analysis > Sholl Analysis...` for morphology-based Sholl analysis.
3. Use `Analysis > Sholl Analysis (by Focal Point)...` if you need an exact user-defined analysis center.

If you only want to analyze a subset of paths, select or filter them in `Path Manager` first and use the commands under `Path Manager > Analyze > Measurements`.

## Step 8 - Save Tables and Plots

When analysis tables or plots are open:

1. Go to `File > Save Tables & Analysis Plots...`.
2. Save the generated tables as CSV.
3. Save plots from the same command or from the plot window export actions.

For scripted SWC analysis after export, use `GROOVY_WORKFLOW_SWC_ANALYSIS.groovy`.

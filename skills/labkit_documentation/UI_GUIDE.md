# Labkit — UI Guide

This guide covers only UI actions explicitly described in the official Labkit
overview, UI documentation, and quick-start tutorials.

## Launch

- Start with an image already open in Fiji.
- Open Labkit from `Plugins > Labkit > Open Current Image With Labkit`.

## Labeling Tools

The Labeling panel is where you create and manage manual annotations.

| Action | Behavior |
|--------|-------------------|
| `Add label` | Add a labeling layer. |
| Rename a label | Double-click the current label name. |
| Change a label color | Click the color flag once. |
| Hide/show labels | Use the eye icon globally or per layer. |
| Remove all labels | Use `Remove all` at the bottom right. |
| Jump to most-labeled slice | Use the target button for that layer. |

Documented shortcuts:

| Shortcut | Tool |
|----------|------|
| `D` + left click | Draw / pencil |
| `E` + left click | Erase / pencil |
| `F` + left click | Flood fill |
| `R` + left click | Remove connected component |
| `N` | Switch to next label |

## Labeling Menu

Documented actions under the `Labeling` menu:

- `Open Labeling` loads a `.labeling` file in place of the current labels.
- `Save Labeling` saves the current labeling layers as a `.labeling` file.
- `Show Labeling in ImageJ` exports all labeling layers to ImageJ.
- `Import Labeling` adds layers from a `.labeling` file.
- `Import Bitmap` adds layers from a bitmap `.tif` file.
- `Export selected Label as Bitmap` exports the selected layer(s) as `.tiff`.

## Segmentation Panel

The Segmentation panel is where you add a pixel classifier, tune it, run it,
and export its outputs.

| UI element | Behavior |
|------------|-------------------|
| `Labkit Pixel Classifier` button | Adds a pixel classifier entry. |
| Gear / wheel icon | Opens classifier settings, including filter choices. |
| Play button | Runs the classifier and overlays the segmentation on the image. |
| Small arrow or Segmentation menu | Import/export classifier or segmentation-related outputs. |

## Segmentation Import / Export

Documented actions in the official UI docs:

- `Open Classifier...` or `Save Classifier...` imports or exports a classifier.
- Save the segmentation result as `.tif` or `.h5`.
- `Show segmentation in ImageJ` exports the segmentation result to ImageJ.
- `Create a label layer from a segmented class` converts a segmented class into
  a new label layer for curation.

## Scope Boundary

- This guide does not document a macro or Groovy command for launching the
  interactive Labkit window.
- This guide does not document a scripted training API.
- For batch application of a saved classifier, use `GROOVY_API.md` and
  `GROOVY_WORKFLOW_BATCH_SEGMENTATION.groovy`.

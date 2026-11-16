---
name: ilastik_documentation
description: >-
  ilastik (interactive machine-learning segmentation, v1.4.2 at /opt/ilastik) and its Fiji plugin
  ilastik4ij 2.1.0 (Plugins > ilastik) are installed. Use for random-forest pixel classification
  trained from a few brush strokes, object classification (incl. classifying Cellpose/StarDist
  instances via a label image), Autocontext, Multicut and ilastik tracking, and the TrackMate
  ilastik detector. Covers opening the ilastik GUI for the user to train, applying a trained .ilp
  to one image (Fiji wrapper) or a whole folder (headless batch), HDF5 import/export, and verified
  pitfalls. Read the file index below before writing any ilastik code.
---

# ilastik in Agentic-J

**Installed (verified 2026-11-16):** ilastik **1.4.2** (CPU build) at `/opt/ilastik`, executable
`$ILASTIK_EXECUTABLE` = `/opt/ilastik/run_ilastik.sh`; Fiji plugin **ilastik4ij 2.1.0**
(`Plugins > ilastik`, update site `ilastik`); **TrackMate-Ilastik 2.0.0** detector. The ilastik4ij
executable preference is preset at container start, so the menu commands and TrackMate-Ilastik work
without opening the configure dialog. No GPU is needed (random forest); the separate ilastik GPU
build is only for Neural Network Classification and is not installed.

## Which route?

| Situation | Route | File |
|---|---|---|
| No trained project yet — the user must paint labels | Open the ilastik GUI on the desktop; user trains, saves, **closes** ilastik | `GROOVY_LAUNCH_ILASTIK_GUI.groovy`, `GUI_TRAINING.md` |
| Trained `.ilp`, **a folder** of images (preferred for >1 image) | One headless ilastik call over all files | `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy`, `HEADLESS_CLI.md` |
| Trained `.ilp`, **one image** / result needed as a Fiji image | Fiji wrapper command (ilastik4ij) | `GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy` (+ AUTOCONTEXT, OBJECT_CLASSIFICATION, MULTICUT, TRACKING) |
| Classify existing instance labels (Cellpose, StarDist, …) | Project type "Object Classification [Inputs: Raw Data, Label Image]" — **headless batch only** (`secondInputRole = label_image`) | `HEADLESS_CLI.md` |
| Tracking with an ilastik pixel classifier as detector | TrackMate `IlastikDetectorFactory` | `TRACKMATE_ILASTIK.md` |
| Move data to/from ilastik's HDF5 | Export/Import HDF5 | `GROOVY_WORKFLOW_EXPORT_HDF5.groovy`, `GROOVY_WORKFLOW_IMPORT_HDF5.groovy` |

ilastik is the right tool when objects are defined by texture/context that a threshold cannot
capture and no pretrained deep model fits; for ordinary nuclei/cells try Cellpose/StarDist first.
Training only exists in the GUI: never claim to "train ilastik" headlessly.

## Verified pitfalls

1. **Dimensions and channels must match the training data** (2D vs 3D, time axis, channel count and
   order). The largest 3D filter (~3.5 × largest sigma) must fit inside the image.
2. **Axis order in headless batch:** a project trained on Fiji-exported HDF5 stores 5-D `tzyxc`; a
   plain 2-D TIFF then fails with `UnsuitedAxistagsException ... No data for some axes` — pass
   `inputAxes = "yx"` (or `yxc`, `zyx`, `tyx`). The axes apply to every input: with a multichannel
   raw image, give label/segmentation images as HDF5 with a trailing channel `(y, x, 1)`
   (`HEADLESS_CLI.md` → "Multichannel raw + label image").
3. **Outputs:** `Probabilities` = one float channel per label class (0–1);
   `Segmentation` / `Simple Segmentation` = class index **1..N (no 0)**, saved as float — select a
   class with `== k`, not with a threshold. Object Predictions: 0 = background, 1..N = class.
   Tracking: lineage IDs. Multicut: instance labels.
4. **Fiji wrapper output is 5-D** `[X, Y, Channel, Z, Time]` with singleton axes.
5. **Label-image object classification cannot run through the Fiji wrapper**: ilastik4ij always
   passes `--segmentation_image`/`--prediction_maps`; a label-image project then stops with
   "You can only have trailing file paths if no other role was set by name". Use the headless batch.
6. **Feature table (`--table_filename`)** only works if the table export was configured once in the
   GUI ("You can't export the CSV object table unless you configure it in the GUI first").
7. **Close the project in the ilastik GUI** before applying it headless.
8. **Very old projects** (ilastik 0.x/1.2) may fail to load in 1.4.2 (e.g. "Rois do not intersect") and
   lack the `shape` entry TrackMate-Ilastik reads — open and re-save them in the bundled ilastik.
9. **Script parameters persist** between Fiji runs: always pass every `#@` parameter explicitly when
   running a workflow; never rely on the `value=` defaults (they point at validation data).
10. The `.ilp` stores paths to its training images (often `inputdata/` next to it); keep them for
    retraining. Prediction does not need them.

## File index

| File | When to read it |
|---|---|
| `OVERVIEW.md` | Capabilities, installed versions, compatibility matrix (what was run and verified). |
| `GUI_TRAINING.md` | Opening the ilastik GUI for the user, what to tell them, then applying the project. |
| `GROOVY_LAUNCH_ILASTIK_GUI.groovy` | Run to open ilastik (new or existing project) on the desktop. |
| `HEADLESS_CLI.md` | ilastik command-line batch: flags, export sources, second-input roles, label images, tables. |
| `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy` | Run to apply a trained project to a folder (all workflows). |
| `GROOVY_API.md` | ilastik4ij command classes, parameters, outputs, options handling. |
| `GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy` | One image, Pixel Classification (Probabilities / Segmentation). |
| `GROOVY_WORKFLOW_AUTOCONTEXT.groovy` | One HDF5 dataset, Autocontext. |
| `GROOVY_WORKFLOW_OBJECT_CLASSIFICATION.groovy` | One image + probability map or binary segmentation. |
| `GROOVY_WORKFLOW_MULTICUT.groovy` | One HDF5 raw + boundary-probability dataset, Multicut. |
| `GROOVY_WORKFLOW_TRACKING.groovy` | One HDF5 time series + probability/segmentation, Tracking. |
| `GROOVY_WORKFLOW_EXPORT_HDF5.groovy` / `GROOVY_WORKFLOW_IMPORT_HDF5.groovy` | HDF5 transfer. |
| `TRACKMATE_ILASTIK.md` | TrackMate ilastik detector: settings keys, class index, quality, limits. |
| `UI_GUIDE.md`, `UI_WORKFLOW_*.md` | Menu paths and manual walkthroughs for the user. |

Sources: ilastik4ij README and source (github.com/ilastik/ilastik4ij, tag ilastik4ij-2.1.0); ilastik
headless docs (ilastik.org/documentation/basics/headless); ilastik 1.4.2 release notes
(github.com/ilastik/ilastik/releases/tag/1.4.2); TrackMate-Ilastik source
(github.com/trackmate-sc/TrackMate-Ilastik); Berg et al. 2019, *Nat Methods* 16:1226,
doi:10.1038/s41592-019-0582-9.

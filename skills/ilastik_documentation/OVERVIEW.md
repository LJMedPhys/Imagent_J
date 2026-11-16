# ilastik — Overview

`ilastik4ij` wraps selected ilastik workflows inside Fiji. The plugin moves data
between Fiji and ilastik through temporary HDF5 files, and it can also expose
the HDF5 transfer steps directly as menu commands.

## Installed in Agentic-J

| Component | Version | Where |
|---|---|---|
| ilastik application (CPU build) | 1.4.2 (2026-05-28) | `/opt/ilastik`, `$ILASTIK_EXECUTABLE=/opt/ilastik/run_ilastik.sh` |
| ilastik4ij Fiji plugin | 2.1.0 (2026-02-10), update site `ilastik` | `plugins/ilastik4ij-2.1.0.jar` |
| TrackMate-Ilastik | 2.0.0 | `jars/TrackMate-Ilastik-2.0.0.jar` |

The ilastik4ij executable preference is preset by the container entrypoint (never overwrites a
user-set path). A plugin regression check (class linkage of all 4 000+ plugin classes plus
Bio-Formats, MorphoLibJ, TrackMate, StarDist/TensorFlow, CLIJ2, 3D ImageJ Suite, Labkit, n5-hdf5
smoke tests) gave identical results with and without ilastik (2026-11-16).

## Verified matrix (2026-11-16)

| Workflow | Fiji wrapper (ilastik4ij) | Headless CLI | Test project |
|---|---|---|---|
| Pixel Classification | ✅ Probabilities + Segmentation | ✅ (identical result) | `pixel_class_2d_cells_apoptotic.ilp` (ilastik4ij tests) |
| Autocontext | ✅ | ✅ `Probabilities Stage 2` | `Autocontext2d3c.ilp` (ilastik tests) |
| Object Classification, prediction map input | ✅ | – | `obj_class_2d_cells_apoptotic.ilp` |
| Object Classification, label image input | ❌ not supported by the wrapper | ✅ `--label_image` | `ObjectClassification2d3c_wLabels.ilp` |
| Multicut | ✅ | – | `Boundary-basedSegmentationwMulticut3d1c.ilp` |
| Tracking (with learning, prediction maps) | ✅ | – | `TrackingwLearning5t2d_wPred.ilp` |
| HDF5 export / import / list | ✅ | – | – |
| TrackMate ilastik detector | ✅ (projects saved by ilastik ≥ 1.3.3) | – | `pixel_class_2d_cells_apoptotic.ilp` |
| ilastik GUI on the desktop (training) | ✅ new + existing projects | – | – |

## Core Capabilities

- HDF5 export from Fiji to ilastik-compatible `.h5`
- HDF5 import from `.h5` into Fiji with explicit dataset selection
- HDF5 dataset inspection before import
- Pixel Classification inference from a trained `.ilp` project
- Autocontext inference from a trained `.ilp` project
- Object Classification inference from a trained `.ilp` project plus a second
  probability or segmentation image
- Multicut inference from a trained `.ilp` project plus a boundary-probability
  image
- Tracking inference from a trained `.ilp` project plus a second probability or
  segmentation time series

## Committed Workflow Coverage

The committed Groovy workflows in this skill cover:

- `Export HDF5`
- `Import HDF5`
- `List HDF5 Datasets`
- `Run Pixel Classification Prediction`
- `Run Autocontext Prediction`
- `Run Object Classification Prediction`
- `Run Multicut`
- `Run Tracking`

## Compatibility Boundary

- Configure the ilastik executable before running any prediction wrapper.
- Close the `.ilp` project in ilastik before Fiji runs it.
- Keep spatial dimensionality, channel count, and channel order consistent
  between training and inference.
- Use `Export HDF5` for training data preparation when you want Fiji-to-ilastik
  HDF5 compatibility.
- Some external example projects expect a sibling `inputdata/` directory with
  referenced datasets next to the `.ilp` file. Keep that directory layout when
  reusing those bundles.

## File Map

- `SKILL.md`: route table and verified pitfalls (read first)
- `GUI_TRAINING.md` + `GROOVY_LAUNCH_ILASTIK_GUI.groovy`: open ilastik for the user to train
- `HEADLESS_CLI.md` + `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy`: batch-apply a project to a folder
- `TRACKMATE_ILASTIK.md`: TrackMate ilastik detector

- `GROOVY_API.md`: command classes, parameters, and helper calls
- `GROOVY_WORKFLOW_EXPORT_HDF5.groovy`: TIFF to HDF5 export
- `GROOVY_WORKFLOW_IMPORT_HDF5.groovy`: HDF5 dataset import
- `GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy`: pixel-classification inference
- `GROOVY_WORKFLOW_AUTOCONTEXT.groovy`: autocontext inference
- `GROOVY_WORKFLOW_OBJECT_CLASSIFICATION.groovy`: object-classification inference
- `GROOVY_WORKFLOW_MULTICUT.groovy`: multicut inference
- `GROOVY_WORKFLOW_TRACKING.groovy`: tracking inference
- `UI_GUIDE.md`: menu paths and wrapper inputs
- `UI_WORKFLOW_PIXEL_CLASSIFICATION.md`: manual pixel-classification steps
- `UI_WORKFLOW_AUTOCONTEXT.md`: manual autocontext steps
- `UI_WORKFLOW_OBJECT_CLASSIFICATION.md`: manual object-classification steps
- `UI_WORKFLOW_MULTICUT.md`: manual multicut steps
- `UI_WORKFLOW_TRACKING.md`: manual tracking steps

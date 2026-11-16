# ilastik — headless command line (batch processing)

`run_ilastik.sh --headless` applies a trained project to any number of files in one call. It is what
ilastik4ij runs internally, minus the per-image HDF5 copy. `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy`
wraps it for a folder; the flags below are what that script passes. All examples were run against the
bundled ilastik 1.4.2 (2026-11-16).

Official reference: https://www.ilastik.org/documentation/basics/headless

## Minimal call

```bash
$ILASTIK_EXECUTABLE --headless \
  --project=/path/MyPixelClassifier.ilp --readonly=1 \
  --export_source="Simple Segmentation" \
  --output_format=tiff \
  --output_filename_format=/path/out/{nickname}_{result_type} \
  --input_axes=yx \
  --raw_data /path/in/img_0.tif /path/in/img_1.tif
```

- `{nickname}` = input file stem (for HDF5 inputs it includes the dataset, e.g. `2d3c-data`), `{result_type}` = export source (contains spaces — the Groovy
  workflow renames them to `_`). ilastik adds the extension itself (`.tiff`, `.h5`).
- `--readonly=1` never modifies the project.
- Environment: `LAZYFLOW_THREADS=<n>` and `LAZYFLOW_TOTAL_RAM_MB=<MiB>` limit threads / RAM.
- HDF5 inputs: `file.h5/internal/path` (a single-dataset file also works without the path).
- From a Groovy/Java `ProcessBuilder`, pass each argument as its own list element (no shell quoting
  needed; the ilastik docs warn against spaces in values when using a shell).

## Export sources (`--export_source`, exact strings)

| Workflow (project type) | Export sources |
|---|---|
| Pixel Classification | `Probabilities`, `Simple Segmentation`, `Uncertainty`, `Features`, `Labels` |
| Autocontext | `<name> Stage <k>` for name in Probabilities, Simple Segmentation, Uncertainty, Features, Labels, Input (e.g. `Probabilities Stage 2` = final stage of a 2-stage project), plus `Probabilities All Stages` |
| Object Classification (all input types) | `Object Predictions` (default), `Object Probabilities`, `Object Identities` |
| Tracking | `Tracking-Result`, `Object-Identities`, `Merger-Result` |
| Multicut / Boundary-based Segmentation | `Multicut Segmentation` |

## Second inputs — must match the project type

| Project type (ilastik GUI name) | Flag for the second input |
|---|---|
| Object Classification [Inputs: Raw Data, Pixel Prediction Map] | `--prediction_maps` |
| Object Classification [Inputs: Raw Data, Segmentation] (binary mask) | `--segmentation_image` |
| **Object Classification [Inputs: Raw Data, Label Image]** (new in 1.4.2) | **`--label_image`** |
| Tracking [Inputs: Raw Data, Pixel Prediction Map] / [..., Segmentation Image] | `--prediction_maps` / `--segmentation_image` |

Files of the two roles are paired by position: `--raw_data a.tif b.tif --label_image a_lab.tif b_lab.tif`.
A wrong flag ends with `ValueError: You can only have trailing file paths if no other role was set by name`.

**Label-image projects are the way to classify objects that another tool segmented** (Cellpose,
StarDist, watershed) while keeping their IDs. ilastik4ij's `Run Object Classification Prediction`
cannot drive them (it only passes `--prediction_maps` / `--segmentation_image`), so use this CLI
(verified: `ObjectClassification2d3c_wLabels.ilp` + `--label_image` → Object Predictions 0/1/2).

## Feature table

`--table_filename=/path/objects.csv` writes per-object features and predictions (object
classification, tracking) — **only if** the project's table export was configured once in the GUI
(4. Object Information Export → Configure Feature Table Export, then save the project). Otherwise:
`RuntimeError: You can't export the CSV object table unless you configure it in the GUI first.`

## Axis order

If the file has no axis metadata ilastik takes the axes of the project's first training lane. A
project trained on HDF5 exported from Fiji stores `tzyxc`, so a 2-D TIFF fails with
`UnsuitedAxistagsException: The given axis interpretation does not match the data shape: No data for
some axes`. Fix: `--input_axes=yx` (2-D grey), `yxc` (2-D multichannel), `zyx`, `tyx`, …

### Multichannel raw + label/segmentation image

`--input_axes` applies to **every** input role. With a multichannel raw image (`yxc`) the label
image must carry a channel axis too — and ilastik's TIFF reader cannot read a single-channel `yxc`
TIFF (`ValueError: could not broadcast input array from shape (73,1) into shape (187,1)`). Write the
label image to HDF5 with a trailing singleton channel and pass `--input_axes=yxc`:

```python
import h5py, tifffile
lab = tifffile.imread("cells_labels.tif")            # (y, x) instance labels, e.g. from Cellpose
with h5py.File("cells_labels.h5", "w") as f:
    f.create_dataset("labels", data=lab[..., None].astype("uint32"))   # (y, x, 1)
```
```bash
$ILASTIK_EXECUTABLE --headless --project=classify_objects.ilp --readonly=1 \
  --export_source="Object Predictions" --output_format=tiff \
  --output_filename_format=/out/{nickname}_pred.tif --input_axes=yxc \
  --raw_data cells.tif --label_image cells_labels.h5/labels
```
(Verified: identical predictions to the all-HDF5 run.) Pass the user's raw TIFF path to ilastik unchanged —
do not open, convert or "Make Composite" it in Fiji first (an `IJ.run(..., "")` with empty options opens a
modal dialog and blocks an unattended script). Only the label image needs converting. For a single-channel raw image, plain `yx`
TIFFs for both roles with `--input_axes=yx` are fine. In `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy` set
`inputAxes="yxc"` and point the second input folder at the `.h5` label files.

## Other useful flags

- `--stack_along=z|t|c` + a glob (`"slices/*.tif"`) to assemble one volume from many files.
- `--export_dtype=uint8`, `--export_drange="(0,255)"`, `--pipeline_result_drange="(0.0,1.0)"` to
  rescale exported probabilities.
- `--logfile=/path/ilastik.log`.

## Verified run (2026-11-16)

| Case | Result |
|---|---|
| 3 × 2-D TIFF, `pixel_class_2d_cells_apoptotic.ilp`, Simple Segmentation, `--input_axes=yx` | 3 files in 9 s; identical (100 % of pixels) to the Fiji-wrapper segmentation |
| Same without `--input_axes` | `UnsuitedAxistagsException` (see above) |
| `ObjectClassification2d3c_wLabels.ilp`, `--label_image` | Object Predictions written (values 0/1/2) |
| Same project with `--segmentation_image` | `ValueError: ... trailing file paths ...` |
| Autocontext2d3c.ilp, `Probabilities Stage 2` | `2d3c-data_Probabilities Stage 2.tiff` written |
| Same with raw TIFF `yxc` + label TIFF `yx` | `UnsuitedAxistagsException`; label as HDF5 `(y,x,1)` + `--input_axes=yxc` works |
| `--table_filename` on a project without configured table export | `RuntimeError: ... configure it in the GUI first` |

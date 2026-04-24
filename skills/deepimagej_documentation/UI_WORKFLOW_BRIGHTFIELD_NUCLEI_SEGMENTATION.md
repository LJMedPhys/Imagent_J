# DeepImageJ - UI Workflow: brightfield_nuclei Segmentation

This walkthrough uses the local `brightfield_nuclei` model bundle that is
installed under `Fiji.app/models/brightfield_nuclei`.

It is a good first DeepImageJ workflow because the bundle already contains:

- `sample_input_0.tif`
- `sample_output_0.tif`
- `rdf.yaml`
- the required preprocessing and postprocessing macros

---

## Prerequisites

- Fiji with the `DeepImageJ` update site enabled
- The local model folder `Fiji.app/models/brightfield_nuclei`
- A 3-channel image that matches the model, or the packaged sample input

For a first run, prefer the packaged sample input:

`/opt/Fiji.app/models/brightfield_nuclei/sample_input_0.tif`

---

## Pipeline Overview

```
Open sample input
      |
[Step 1] Inspect the model bundle
      |
[Step 2] Optional: validate the model
      |
[Step 3] Run DeepImageJ with the bundle's settings
      |
[Step 4] Inspect the label image output
      |
[Step 5] Save the prediction
```

---

## Step 1 - Inspect the Model Bundle

Before the first run, inspect `rdf.yaml` in the model folder.

The important values for `brightfield_nuclei` are:

- model name: `brightfield_nuclei`
- framework: Torchscript, used in DeepImageJ as `pytorch`
- preprocessing macro: `instanseg_preprocess.ijm`
- postprocessing macro: `instanseg_postprocess.ijm`
- input axes: `bcyx`
- runtime axes: `C,Y,X`
- minimum tile: `3,128,128`
- valid larger tiles: keep channel `3`, increase Y and X in `32` pixel steps

---

## Step 2 - Open the Sample Input

1. In Fiji, choose `File > Open...`
2. Open:
   `/opt/Fiji.app/models/brightfield_nuclei/sample_input_0.tif`
3. Keep that image as the active window

The packaged sample image is sized for a safe first run and matches the model
bundle exactly.

---

## Step 3 - Optional: Run DeepImageJ Validate

1. Open `Plugins > DeepImageJ > DeepImageJ Validate`
2. Choose the installed `brightfield_nuclei` model if the dialog asks for one
3. Let the validation finish before continuing

If the model was installed manually or copied between Fiji installations, this is
a useful sanity check before the real run.

---

## Step 4 - Run DeepImageJ

1. Open `Plugins > DeepImageJ > DeepImageJ Run`
2. Fill the run settings from the model bundle:
   - model: `brightfield_nuclei`
   - format: `pytorch`
   - preprocessing: `instanseg_preprocess.ijm`
   - postprocessing: `instanseg_postprocess.ijm`
   - axes: `C,Y,X`
   - tile: `3,256,256`
   - logging: `debug`
3. Run the model and wait for the new output windows

For this sample input, `3,256,256` is a known-good tile and covers the full
image in one patch.

---

## Step 5 - Inspect the Output

After a successful run, DeepImageJ opens the prediction image in a new window.
For the packaged sample input, the main output title includes:

`brightfield_nuclei_instance_sample_input_0`

A helper window such as `Visited` may also appear. Focus on the prediction image,
not the helper window.

To inspect the label image:

1. Make the prediction image active
2. Apply `Image > Lookup Tables > Glasbey on Dark` for easier label inspection
3. Use `Analyze > Histogram` or `Analyze > Measure` to confirm the image is not empty

---

## Step 6 - Save the Prediction

1. Make the prediction image active
2. Choose `File > Save As > Tiff...`
3. Save the output to your working folder

Keep `sample_output_0.tif` from the model bundle nearby if you want a reference
result for visual comparison.

---

## Adapting the Workflow to Your Own Images

When you move from the packaged sample image to your own data:

- keep the channel order compatible with the model
- keep the runtime axes in `C,Y,X` order
- choose a valid tile such as `3,128,128`, `3,160,160`, `3,224,224`, or `3,256,256`
- expect larger images to run more slowly because DeepImageJ will process more patches

If your image is much larger than the sample input, start with a conservative
valid tile and increase only after the model runs reliably.

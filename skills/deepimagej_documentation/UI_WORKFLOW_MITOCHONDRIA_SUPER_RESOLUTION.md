# DeepImageJ - UI Workflow: Mitochondria Super-resolution

This walkthrough uses the local super-resolution model installed under:

`Fiji.app/models/organized-cricket`

The model display name in DeepImageJ is:

`Mitochondria resolution enhancement Wasserstein GAN`

It is a non-segmentation example that upsamples a `128x128` mitochondria image
to `512x512`.

---

## Prerequisites

- Fiji with the `DeepImageJ` update site enabled
- The local model folder `Fiji.app/models/organized-cricket`
- The packaged sample image:
  `/opt/Fiji.app/models/organized-cricket/sample_input_0.tif`

For a first run, use the packaged sample input instead of your own data.

---

## Pipeline Overview

```
Open sample input
      |
[Step 1] Inspect rdf.yaml
      |
[Step 2] Optional: validate the model
      |
[Step 3] Run DeepImageJ with the model's settings
      |
[Step 4] Inspect the super-resolved output
      |
[Step 5] Save the result
```

---

## Step 1 - Inspect the Model Bundle

The key values in `rdf.yaml` are:

- display name: `Mitochondria resolution enhancement Wasserstein GAN`
- nickname / local folder: `organized-cricket`
- framework: Torchscript, used in DeepImageJ as `pytorch`
- preprocessing: `no preprocessing`
- postprocessing: `no postprocessing`
- input axes: `bcxy`
- runtime axes: `C,X,Y`
- input tile: `1,128,128`
- output shape: `1,1,512,512`

This is a good example of a model whose run string uses the dialog model name,
not only the local folder nickname.

---

## Step 2 - Open the Sample Input

1. In Fiji, choose `File > Open...`
2. Open:
   `/opt/Fiji.app/models/organized-cricket/sample_input_0.tif`
3. Keep that image as the active window

---

## Step 3 - Optional: Run DeepImageJ Validate

1. Open `Plugins > DeepImageJ > DeepImageJ Validate`
2. Select the installed model if the dialog asks for it
3. Let the validation finish before continuing

This is useful after manual installation or when testing a new model bundle for
the first time.

---

## Step 4 - Run DeepImageJ

1. Open `Plugins > DeepImageJ > DeepImageJ Run`
2. Set:
   - model: `Mitochondria resolution enhancement Wasserstein GAN`
   - format: `pytorch`
   - preprocessing: `no preprocessing`
   - postprocessing: `no postprocessing`
   - axes: `C,X,Y`
   - tile: `1,128,128`
   - logging: `Debug`
3. Run the model and wait for the output window to appear

For this sample image, the model processes one `128x128` input tile and returns
one `512x512` output image.

---

## Step 5 - Inspect the Output

After a successful run, the output window title includes:

`Mitochondria resolution enhancement Wasserstein GAN_output_sample_input_0`

To inspect the result:

1. Make the output image active
2. Zoom in and compare fine structures against the original sample input
3. Use `Image > Show Info...` or `Analyze > Measure` to confirm the output image
   size is larger than the input

This model is not returning labels or ROIs. The main product is an enhanced
image.

---

## Step 6 - Save the Result

1. Make the output image active
2. Choose `File > Save As > Tiff...`
3. Save the result to your working folder

The packaged `sample_output_0.tif` in the model folder is a useful reference for
quick visual comparison.

---

## Adapting the Workflow to Your Own Images

When switching to your own images:

- keep the input layout compatible with the model's single-channel expectation
- keep the runtime axes in `C,X,Y` order
- use the fixed input tile `1,128,128`
- remember that the output is an upsampled image, not a segmentation mask

If your own data does not match the model's training domain, the result may look
sharp but still be biologically wrong. Always compare against known reference
data before relying on the output.

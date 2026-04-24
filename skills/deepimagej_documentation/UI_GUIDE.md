# DeepImageJ - UI GUIDE

DeepImageJ appears in Fiji at `Plugins > DeepImageJ`.

The installed menu entries are:

- `DeepImageJ Run`
- `DeepImageJ Install Model`
- `DeepImageJ Validate`

This guide focuses on how to use those menu entries safely and how to connect
what you see in the UI to the model bundle on disk.

---

## Before You Start

Confirm the plugin is installed:

1. Open `Help > Update... > Manage update sites`
2. Enable `DeepImageJ`
3. Apply changes and restart Fiji

Then confirm `Plugins > DeepImageJ` is visible in the menu bar.

---

## What Each Menu Entry Is For

### DeepImageJ Run

Use this to run an installed model on the active image, or on an image path if
the run dialog is configured that way. The key settings come from the model
bundle:

- model name
- framework format
- preprocessing macro
- postprocessing macro
- input axes
- tile size
- logging level

When a run completes, DeepImageJ opens one or more output windows in Fiji.

### DeepImageJ Install Model

Use this to install a model zip into Fiji's `models` directory. After
installation, inspect the unpacked folder and confirm it contains:

- `rdf.yaml`
- weight files
- preprocessing and postprocessing macros
- sample input or output files

### DeepImageJ Validate

Use this before processing your own data when you want a quick check that the
installed model bundle is healthy. Validation is especially useful after manual
model installation or after moving a model folder between Fiji installations.

---

## Where To Find Models

The official DeepImageJ project points users to the BioImage Model Zoo for
compatible models.

Use these sources first:

- `https://deepimagej.github.io/models.html`
- `https://deepimagej.github.io/`
- `https://bioimage.io/`

The DeepImageJ about page also states that `DeepImageJ Install Model` can
install compatible models from the BioImage Model Zoo, a given URL, or a local
path.

For a reproducible collection listing, see `MODEL_DISCOVERY.md`.

---

## Where the Run Settings Come From

DeepImageJ model settings are not universal. Before running a model, inspect its
folder under `Fiji.app/models/<model_name>`.

Use these files as your reference:

| Bundle file | What it tells you |
|-------------|-------------------|
| `rdf.yaml` | model name, axes, framework, tiling rules, and test info |
| `*_preprocess*.ijm` | preprocessing macro names |
| `*_postprocess*.ijm` | postprocessing macro names |
| `config.deepimagej.prediction.* = null` in `rdf.yaml` | use `no preprocessing` or `no postprocessing` |
| `sample_input_0.tif` | a safe test image for the first run |
| `sample_output_0.tif` | reference output for comparison |
| `*_README.md` | model-specific scope and citations |

If a model uses `inputs[0].axes: bcyx`, the runtime axes you pass to DeepImageJ
drop the batch axis and become `C,Y,X`.

If a model uses `inputs[0].axes: bcxy`, the runtime axes become `C,X,Y`.

---

## Running a Model From the GUI

1. Open an image that matches the model's expected axes and channel layout.
2. Make that image the active Fiji window.
3. Open `Plugins > DeepImageJ > DeepImageJ Run`.
4. Use the selected model's bundle to fill in the framework, pre/post macros,
   axes, and tile settings.
5. Run the model and wait for the output windows to appear.
6. Save the real prediction image explicitly with `File > Save As`.

If you are trying a new model for the first time, start with the packaged sample
input from the model folder rather than a large project image.

---

## Concrete Example: brightfield_nuclei

The local `brightfield_nuclei` model bundle uses:

- model: `brightfield_nuclei`
- format: `pytorch`
- preprocessing: `instanseg_preprocess.ijm`
- postprocessing: `instanseg_postprocess.ijm`
- axes: `C,Y,X`
- valid tile sizes: `3,128,128` minimum, larger tiles in `32` pixel Y/X steps

`3,256,256` is a known-good tile for the packaged sample input.

See `UI_WORKFLOW_BRIGHTFIELD_NUCLEI_SEGMENTATION.md` for a full walkthrough.

---

## Concrete Example: organized-cricket

The local `organized-cricket` super-resolution model bundle uses:

- dialog model name: `Mitochondria resolution enhancement Wasserstein GAN`
- local folder / nickname: `organized-cricket`
- format: `pytorch`
- preprocessing: `no preprocessing`
- postprocessing: `no postprocessing`
- axes: `C,X,Y`
- input tile: `1,128,128`

This model upsamples its packaged sample input from `128x128` to `512x512`.

See `UI_WORKFLOW_MITOCHONDRIA_SUPER_RESOLUTION.md` for a full walkthrough.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Plugins > DeepImageJ` missing | Plugin not installed | Enable the `DeepImageJ` update site and restart Fiji |
| Run fails with a missing `format` error | Wrong macro or run syntax | Use the `model`, `format`, `preprocessing`, `postprocessing`, `axes`, `tile`, `logging` form |
| Run fails because the model is not found | Wrong `model=` string | Use the model name shown in the DeepImageJ Run dialog |
| Run finishes but output is wrong shape | Wrong `axes` or tile order | Re-read `rdf.yaml` and match the model input order |
| Run is very slow | Large image split into many patches | Reduce image size, choose a larger valid tile, or use GPU support if available |
| No useful output image appears | Helper window selected instead of prediction | Save the main prediction image, not helper images such as `Visited` |
| Manual install seems fine but run fails | Model bundle missing files | Confirm `rdf.yaml`, weights, and pre/post macros are all present in the model folder |

# DeepImageJ - OVERVIEW

## What It Is

DeepImageJ is a Fiji/ImageJ plugin for running packaged deep-learning models
inside Fiji without leaving the ImageJ workflow. It is designed for inference,
not training. A DeepImageJ model bundle typically contains an `rdf.yaml`
description file, one or more framework weights, preprocessing and
postprocessing macros, and sample test data.

In the Fiji menu bar, the installed plugin exposes:

- `Plugins > DeepImageJ > DeepImageJ Run`
- `Plugins > DeepImageJ > DeepImageJ Install Model`
- `Plugins > DeepImageJ > DeepImageJ Validate`

DeepImageJ is a good fit when you want to apply a published model from a local
bundle, keep the workflow inside Fiji, and preserve model-specific preprocessing
and postprocessing steps.

---

## Typical Inputs and Use Cases

### Segmentation

- Input: microscopy images that match a packaged segmentation model
- Output: label image, mask, or probability map depending on the model
- Examples: nuclei segmentation, cell segmentation, object masking

### Super-resolution

- Input: diffraction-limited fluorescence images
- Output: higher-resolution or upsampled reconstruction
- Examples: widefield fluorescence super-resolution, mitochondria resolution enhancement

### Virtual staining / in-silico labeling

- Input: brightfield, phase-contrast, or unlabeled microscopy images
- Output: synthetic fluorescence-like label image
- Examples: nuclei virtual staining, mitochondria artificial labeling

### Denoising and restoration

- Input: noisy fluorescence or brightfield images
- Output: restored or denoised images with the same spatial footprint
- Examples: CARE-style restoration, content-aware denoising, deblurring

### Background removal and sparse imaging

- Input: fluorescence images with structured background or sparse signal
- Output: cleaned image, sparse component, or density-like representation
- Examples: STORM background removal, density estimation pipelines

### Model evaluation inside Fiji

- Input: a model bundle plus its packaged sample data
- Output: a quick functional check before processing real data
- Examples: confirm a newly installed model runs, compare sample output windows, verify preprocessing macros are present

---

## Model Bundle Anatomy

DeepImageJ models are folder-based. The local `brightfield_nuclei` example
under `Fiji.app/models` contains:

| File | Purpose |
|------|---------|
| `rdf.yaml` | Model metadata, axes, weights, tiling rules, and test information |
| `instanseg.pt` | Torchscript weights used for inference |
| `instanseg_preprocess.ijm` | Model-specific preprocessing macro |
| `instanseg_postprocess.ijm` | Model-specific postprocessing macro |
| `sample_input_0.tif` | Example input image |
| `sample_output_0.tif` | Example output image |
| `test-input.npy` / `test-output.npy` | Validation tensors used by the model package |
| `brightfield_nuclei_README.md` | Model-specific documentation |

The most important file for scripting is `rdf.yaml`, because it tells you:

- which framework to use
- what the input axes are
- which pre/post macros belong to the model
- what tile sizes are valid

---

## Installation

### Install the plugin

1. Start Fiji.
2. Open `Help > Update... > Manage update sites`.
3. Enable `DeepImageJ`.
4. Apply changes and restart Fiji.

If the `DeepImageJ` menu is missing after restart, run the updater again and
refresh update sites before retrying.

### Install a model bundle

Use the GUI entry `Plugins > DeepImageJ > DeepImageJ Install Model`, or place a
compatible model folder directly under `Fiji.app/models/<model_name>`.

After installation, inspect the model folder and make sure `rdf.yaml` is at the
top level and the referenced pre/post macro files are present.

For official model sources and a reproducible way to list current DeepImageJ
models from the BioImage Model Zoo, see `MODEL_DISCOVERY.md`.

---

## Automation Level

DeepImageJ is GUI-first, but inference is scriptable through the menu command
`DeepImageJ Run`.

- IJ Macro: `run("DeepImageJ Run", "...")`
- Groovy: `IJ.run("DeepImageJ Run", "...")`

The arguments are model-specific. Derive them from `rdf.yaml` rather than
guessing them or copying examples from unrelated models.

This documentation skill covers the user-facing `DeepImageJ Run` path. It does
not treat internal Java classes as the stable API surface.

---

## Validated Local Example Models

### brightfield_nuclei

| Property | Value |
|---------|-------|
| Model name | `brightfield_nuclei` |
| Framework | Torchscript weights, passed to DeepImageJ as `format=pytorch` |
| Input tensor | `raw` |
| Input axes in `rdf.yaml` | `bcyx` |
| Working axes for `DeepImageJ Run` | `C,Y,X` |
| Preprocessing macro | `instanseg_preprocess.ijm` |
| Postprocessing macro | `instanseg_postprocess.ijm` |
| Minimum tile | `3,128,128` |
| Tile step | `0,32,32` |
| Example valid tile | `3,256,256` |
| Output tensor | `instance` |

When this model is run on its packaged sample image, the main output is a label
image window whose title includes the model name, output tensor name, and input
image title.

### organized-cricket

The local `organized-cricket` bundle is a non-segmentation DeepImageJ example
for super-resolution.

| Property | Value |
|---------|-------|
| Dialog model name | `Mitochondria resolution enhancement Wasserstein GAN` |
| Local folder / nickname | `organized-cricket` |
| Framework | Torchscript weights, passed to DeepImageJ as `format=pytorch` |
| Input axes in `rdf.yaml` | `bcxy` |
| Working axes for `DeepImageJ Run` | `C,X,Y` |
| Preprocessing | `no preprocessing` |
| Postprocessing | `no postprocessing` |
| Input tile | `1,128,128` |
| Output tensor | `output` |
| Sample output size | `512x512` |

When this model is run on its packaged sample image, DeepImageJ produces a
single upsampled output image window whose title includes the model name,
output tensor name, and input image title.

---

## Known Limitations

- This skill documents the scriptable `DeepImageJ Run` surface, not every internal Java API.
- Model arguments are not universal. `axes`, `tile`, `preprocessing`, and `postprocessing` change from model to model.
- Large images can be slow when DeepImageJ has to process many patches. Reduce the tile size or use a GPU-capable runtime if available.
- Helper output windows may appear alongside the main prediction image. Save the real output image explicitly.
- The validated workflow in this skill assumes a single active input image and a single primary output image.

---

## Links

| Resource | URL |
|----------|-----|
| DeepImageJ home page | https://deepimagej.github.io/ |
| DeepImageJ models page | https://deepimagej.github.io/models.html |
| DeepImageJ about page | https://deepimagej.github.io/about.html |
| GitHub plugin repository | https://github.com/deepimagej/deepimagej-plugin |
| Nature Methods paper | https://doi.org/10.1038/s41592-021-01262-9 |
| BioImage Model Zoo | https://bioimage.io/ |
| BioImage Model Zoo collection JSON | https://uk1s3.embassy.ebi.ac.uk/public-datasets/bioimage.io/collection.json |

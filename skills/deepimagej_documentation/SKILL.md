---
name: deepimagej_documentation
description: DeepImageJ is a Fiji/ImageJ plugin for running packaged deep-learning models from local model bundles or the BioImage Model Zoo. Use it to install a model, validate it, discover compatible models, and run inference from the GUI or via `IJ.run("DeepImageJ Run", "...")`. This skill includes validated examples for `brightfield_nuclei` segmentation and the `Mitochondria resolution enhancement Wasserstein GAN` super-resolution model. Read the files listed at the end of this SKILL for installation, model discovery, GUI workflows, scripting patterns, and common pitfalls.
---

Install the plugin from the Fiji update site:
`Help > Update... > Manage update sites > DeepImageJ`

---

## The Only Verified Automation Surface

DeepImageJ automation in Fiji is driven by the menu command `DeepImageJ Run`.

- IJ Macro: `run("DeepImageJ Run", "...")`
- Groovy: `IJ.run("DeepImageJ Run", "...")`

Do not assume DeepImageJ is exposed as a SciJava `command.run(...)` command.
Do not assume older upstream `model_path/input_path/output_folder` examples match the installed Fiji release.

For the DeepImageJ release documented in this repo, the working `DeepImageJ Run`
arguments are:

- required: `model`, `format`, `preprocessing`, `postprocessing`, `axes`, `tile`, `logging`
- optional: `model_dir`

### Minimal validated segmentation example

```groovy
import ij.IJ

IJ.run("DeepImageJ Run",
    "model=brightfield_nuclei " +
    "format=pytorch " +
    "preprocessing=instanseg_preprocess.ijm " +
    "postprocessing=instanseg_postprocess.ijm " +
    "axes=C,Y,X " +
    "tile=3,256,256 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models")
```

### Minimal validated super-resolution example

```groovy
import ij.IJ

IJ.run("DeepImageJ Run",
    "model=[Mitochondria resolution enhancement Wasserstein GAN] " +
    "format=pytorch " +
    "preprocessing=[no preprocessing] " +
    "postprocessing=[no postprocessing] " +
    "axes=C,X,Y " +
    "tile=1,128,128 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models")
```

### How to derive the arguments from a model bundle

Read `<model>/rdf.yaml`:

- `name` -> user-facing `model` value shown in the DeepImageJ dialog
- `weights` -> `format`
- `config.deepimagej.prediction.preprocess[].kwargs` -> `preprocessing`
- `config.deepimagej.prediction.postprocess[].kwargs` -> `postprocessing`
- `inputs[0].axes` with batch axis removed -> `axes`
- `inputs[0].shape.min` and `inputs[0].shape.step` with batch axis removed -> valid `tile` sizes
- `config.bioimageio.nickname` or local folder name -> useful install identifier, but not always the same string passed to `model=`

Framework mapping used by this skill:

- Torchscript weights -> `format=pytorch`
- TensorFlow SavedModel bundle -> `format=tensorflow`
- ONNX weights -> `format=onnx`

When a value contains spaces, wrap it in brackets inside the option string:

- `model=[Mitochondria resolution enhancement Wasserstein GAN]`
- `preprocessing=[no preprocessing]`
- `postprocessing=[no postprocessing]`

If a model has no bundled preprocessing or postprocessing macros, use the exact
special values `no preprocessing` and `no postprocessing`.

For `brightfield_nuclei`, the input tensor is `bcyx`, so the working axes are
`C,Y,X`. The minimum tile is `3,128,128`, and valid larger tiles follow the
`0,32,32` step rule.

For `Mitochondria resolution enhancement Wasserstein GAN`, the input tensor is
`bcxy`, so the working axes are `C,X,Y`. The fixed input tile is `1,128,128`,
and the model upsamples its output to `512x512`.

---

## Finding Models

The official DeepImageJ sources point users to the BioImage Model Zoo for
compatible models.

- DeepImageJ models page: `https://deepimagej.github.io/models.html`
- DeepImageJ home page with example categories: `https://deepimagej.github.io/`
- BioImage Model Zoo: `https://bioimage.io/`

Use `MODEL_DISCOVERY.md` for a source-grounded way to list current
DeepImageJ-compatible model entries from the official collection JSON.

---

## Common Pitfalls

- If a run fails with `Missing argument: format`, you are using the wrong macro syntax.
- `model=` must match the model name shown in the DeepImageJ Run dialog, not always the folder nickname.
- Tile order follows the model working axes, not always `Y,X,C`.
- `preprocessing` and `postprocessing` are filenames from the model folder.
- Some models use the special values `no preprocessing` and `no postprocessing`.
- This skill treats `DeepImageJ Install Model` and `DeepImageJ Validate` as GUI actions, not headless APIs.

---

## File Index

| File | Contents |
|------|---------|
| `OVERVIEW.md` | Plugin capabilities, installation, model layout, and limitations |
| `MODEL_DISCOVERY.md` | Official model sources, example model categories, and a reproducible way to list DeepImageJ-compatible models |
| `UI_GUIDE.md` | Fiji menu structure and model install/run concepts |
| `UI_WORKFLOW_BRIGHTFIELD_NUCLEI_SEGMENTATION.md` | End-to-end GUI walkthrough using the local `brightfield_nuclei` model |
| `UI_WORKFLOW_MITOCHONDRIA_SUPER_RESOLUTION.md` | End-to-end GUI walkthrough using the local super-resolution model `organized-cricket` |
| `SCRIPT_API.md` | Verified IJ Macro and Groovy automation patterns for `DeepImageJ Run` |
| `GROOVY_WORKFLOW_BRIGHTFIELD_NUCLEI_SEGMENTATION.groovy` | Runnable Groovy wrapper around the validated `DeepImageJ Run` call |
| `GROOVY_WORKFLOW_MITOCHONDRIA_SUPER_RESOLUTION.groovy` | Runnable Groovy wrapper around the validated DeepImageJ super-resolution call |
| `SKILL.md` | This quick reference |

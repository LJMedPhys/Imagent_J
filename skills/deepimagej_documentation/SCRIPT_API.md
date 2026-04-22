# DeepImageJ - SCRIPTING API REFERENCE

DeepImageJ scripting in Fiji is centered on the menu command `DeepImageJ Run`.

Use one of these two patterns:

- IJ Macro: `run("DeepImageJ Run", "...")`
- Groovy: `IJ.run("DeepImageJ Run", "...")`

Do not assume the plugin is exposed as a SciJava `command.run(...)` command.
Do not assume older `model_path/input_path/output_folder` examples match the
installed Fiji release.

This file documents the `DeepImageJ Run` surface that was used successfully with
the local `brightfield_nuclei` segmentation bundle and the local
`organized-cricket` super-resolution bundle.

---

## Required and Optional Arguments

| Argument | Required | Example | How to derive it |
|----------|----------|---------|------------------|
| `model` | yes | `brightfield_nuclei` or `[Mitochondria resolution enhancement Wasserstein GAN]` | Model name as shown in the DeepImageJ Run dialog |
| `format` | yes | `pytorch` | From `rdf.yaml` weights section |
| `preprocessing` | yes | `instanseg_preprocess.ijm` or `[no preprocessing]` | From `config.deepimagej.prediction.preprocess[].kwargs`, or the special no-op value |
| `postprocessing` | yes | `instanseg_postprocess.ijm` or `[no postprocessing]` | From `config.deepimagej.prediction.postprocess[].kwargs`, or the special no-op value |
| `axes` | yes | `C,Y,X` | Input tensor axes with batch removed |
| `tile` | yes | `3,256,256` | Input tensor `shape.min` plus `shape.step` rule |
| `logging` | yes | `debug` | Logging level string; `debug` is the validated value |
| `model_dir` | no | `/opt/Fiji.app/models` | Base folder that contains the model directory |

Framework mapping used by this skill:

- Torchscript weights -> `format=pytorch`
- TensorFlow SavedModel bundle -> `format=tensorflow`
- ONNX weights -> `format=onnx`

For single preprocessing or postprocessing macros, pass the filename directly.
If a model uses multiple macros, pass them in model order and keep them tied to
the filenames declared in the model bundle.

If a model has no bundled pre/post macros, use the exact special values:

- `[no preprocessing]`
- `[no postprocessing]`

When `model`, `preprocessing`, or `postprocessing` values contain spaces, wrap
them in brackets inside the `IJ.run()` option string.

---

## Deriving Arguments from rdf.yaml

For the local `brightfield_nuclei` model:

```yaml
name: brightfield_nuclei
inputs:
  - axes: bcyx
    shape:
      min: [1, 3, 128, 128]
      step: [0, 0, 32, 32]
config:
  deepimagej:
    prediction:
      preprocess:
        - kwargs: instanseg_preprocess.ijm
      postprocess:
        - kwargs: instanseg_postprocess.ijm
weights:
  torchscript:
    source: instanseg.pt
```

This maps to:

- `model=brightfield_nuclei`
- `format=pytorch`
- `preprocessing=instanseg_preprocess.ijm`
- `postprocessing=instanseg_postprocess.ijm`
- `axes=C,Y,X`
- `tile=3,128,128` minimum, with larger valid tiles following `3,128+32n,128+32m`

The `b` batch axis is omitted when building the runtime `axes` and `tile`
values for `DeepImageJ Run`.

---

## Second Derived Example - organized-cricket

For the local super-resolution model:

```yaml
name: Mitochondria resolution enhancement Wasserstein GAN
config:
  bioimageio:
    nickname: organized-cricket
  deepimagej:
    prediction:
      preprocess:
        - spec: null
      postprocess:
        - spec: null
inputs:
  - axes: bcxy
    shape: [1, 1, 128, 128]
weights:
  torchscript:
    source: weights.pt
```

This maps to:

- `model=[Mitochondria resolution enhancement Wasserstein GAN]`
- `format=pytorch`
- `preprocessing=[no preprocessing]`
- `postprocessing=[no postprocessing]`
- `axes=C,X,Y`
- `tile=1,128,128`

The output image is upsampled from `128x128` to `512x512`.

---

## Minimal IJ Macro Example

```javascript
open("/opt/Fiji.app/models/brightfield_nuclei/sample_input_0.tif");
run("DeepImageJ Run",
    "model=brightfield_nuclei " +
    "format=pytorch " +
    "preprocessing=instanseg_preprocess.ijm " +
    "postprocessing=instanseg_postprocess.ijm " +
    "axes=C,Y,X " +
    "tile=3,256,256 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models");
selectWindow("brightfield_nuclei_instance_sample_input_0");
saveAs("Tiff", "/path/to/output/sample_input_0_instance.tif");
```

---

## Minimal IJ Macro Example - Super-resolution

```javascript
open("/opt/Fiji.app/models/organized-cricket/sample_input_0.tif");
run("DeepImageJ Run",
    "model=[Mitochondria resolution enhancement Wasserstein GAN] " +
    "format=pytorch " +
    "preprocessing=[no preprocessing] " +
    "postprocessing=[no postprocessing] " +
    "axes=C,X,Y " +
    "tile=1,128,128 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models");
selectWindow("Mitochondria resolution enhancement Wasserstein GAN_output_sample_input_0");
saveAs("Tiff", "/path/to/output/organized_cricket_superres.tif");
```

---

## Minimal Groovy Example

```groovy
import ij.IJ
import ij.WindowManager

def before = (WindowManager.getIDList() ?: new int[0]) as List

IJ.run("DeepImageJ Run",
    "model=brightfield_nuclei " +
    "format=pytorch " +
    "preprocessing=instanseg_preprocess.ijm " +
    "postprocessing=instanseg_postprocess.ijm " +
    "axes=C,Y,X " +
    "tile=3,256,256 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models")

def after = (WindowManager.getIDList() ?: new int[0]) as List
def newIds = after.findAll { !before.contains(it) }
def outputs = newIds.collect { WindowManager.getImage(it) }.findAll { it != null }
def labelImp = outputs.find { it.getTitle().contains("_instance_") } ?: outputs[0]

IJ.saveAsTiff(labelImp, "/path/to/output/sample_input_0_instance.tif")
```

The full runnable version of this pattern is in
`GROOVY_WORKFLOW_BRIGHTFIELD_NUCLEI_SEGMENTATION.groovy`.

---

## Minimal Groovy Example - Super-resolution

```groovy
import ij.IJ
import ij.WindowManager

def before = (WindowManager.getIDList() ?: new int[0]) as List

IJ.run("DeepImageJ Run",
    "model=[Mitochondria resolution enhancement Wasserstein GAN] " +
    "format=pytorch " +
    "preprocessing=[no preprocessing] " +
    "postprocessing=[no postprocessing] " +
    "axes=C,X,Y " +
    "tile=1,128,128 " +
    "logging=debug " +
    "model_dir=/opt/Fiji.app/models")

def after = (WindowManager.getIDList() ?: new int[0]) as List
def newIds = after.findAll { !before.contains(it) }
def outputs = newIds.collect { WindowManager.getImage(it) }.findAll { it != null }
def srImp = outputs.find { it.getTitle().contains("_output_") } ?: outputs[0]

IJ.saveAsTiff(srImp, "/path/to/output/organized_cricket_superres.tif")
```

The full runnable version of this pattern is in
`GROOVY_WORKFLOW_MITOCHONDRIA_SUPER_RESOLUTION.groovy`.

---

## What Is and Is Not Covered Here

Covered:

- running a model against the active image
- deriving runtime arguments from `rdf.yaml`
- saving the output image from Groovy or Macro

Not covered:

- treating internal Java classes as the stable public API
- a generic headless API for `DeepImageJ Install Model`
- a generic headless API for `DeepImageJ Validate`

---

## Common Pitfalls

### Pitfall 1 - Old macro syntax

If you use older examples with keys like `model_path`, DeepImageJ may fail with
errors such as `Missing argument: format`.

### Pitfall 2 - Wrong axis order

Tile order follows the model working axes. For `brightfield_nuclei`, the correct
order is `C,Y,X`, not `Y,X,C`. For `organized-cricket`, the correct order is
`C,X,Y`.

### Pitfall 3 - Invalid tile sizes

Tile sizes must follow the `shape.min` and `shape.step` rule from `rdf.yaml`.
For `brightfield_nuclei`, valid tiles keep channel size `3` and use `128 + 32n`
for Y and X.

### Pitfall 4 - Output window selection

DeepImageJ can open helper images in addition to the main prediction. In the
validated example, a helper window named `Visited` may appear. Save the real
prediction image explicitly.

### Pitfall 5 - Model-specific preprocessing

Do not swap in arbitrary macro names. The preprocessing and postprocessing files
must come from the model bundle you are running.

### Pitfall 6 - Display name versus folder nickname

The value passed to `model=` should match the model name shown in the
DeepImageJ Run dialog. A local folder nickname such as `organized-cricket` is
useful for installation, but the actual run string may need the display name
`[Mitochondria resolution enhancement Wasserstein GAN]`.

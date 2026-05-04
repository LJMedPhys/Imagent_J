# BioVoxxel Toolbox — Groovy API

## Scope of This API File

This file documents only the BioVoxxel commands that were adopted as stable automation paths in this repo:

- `EDM Binary Operations`
- `Watershed Irregular Features`
- the checked-in workflow `GROOVY_WORKFLOW_PREPROCESS_AND_WATERSHED.groovy`

GUI-driven tools such as `Extended Particle Analyzer`, `Binary Feature Extractor`, and `Speckle Inspector` are intentionally excluded from the API section because they were not adopted as headless-safe workflow steps here.

## Standard Preparation Step

Both validated BioVoxxel commands require a binary mask. A typical preparation sequence is:

```groovy
import ij.IJ

IJ.run(imp, "8-bit", "")
IJ.setAutoThreshold(imp, "Otsu dark")
IJ.run(imp, "Convert to Mask", "")
IJ.run(imp, "Fill Holes", "")   // default: solid objects; drop this line if hollow interiors are meaningful
```

The resulting image must contain background `0` and foreground `255`.

## EDM Binary Operations

### Command

```groovy
IJ.run(maskImp, "EDM Binary Operations", "iterations=1 operation=open")
```

### Accepted parameters

| Parameter | Values | Meaning |
|---|---|---|
| `iterations` | integer `>= 1` | Number of EDM morphology iterations |
| `operation` | `open`, `close`, `erode`, `dilate` | Binary morphology mode |

### Input requirements

- active image must be 8-bit binary
- foreground should be white (`255`)
- stacks are accepted by the plugin source

### Output behavior

- modifies the active image in place
- no separate result window is created

### Practical notes

- `open` is a good first pass to remove narrow bridges and isolated specks
- `close` is the opposite choice when small gaps need filling
- increasing `iterations` is more destructive than switching from `open` to `close`

## Watershed Irregular Features

### Command

```groovy
IJ.run(maskImp, "Watershed Irregular Features",
    "erosion=1 convexity_threshold=0 separator_size=0-Infinity")
```

### Accepted parameters

| Parameter | Values | Meaning |
|---|---|---|
| `erosion` | integer `>= 1` | Number of erosion cycles used before separator analysis |
| `convexity_threshold` | `0.0` to `1.0` | Enables convexity-aware stopping when above zero |
| `separator_size` | hyphenated range such as `0-Infinity` or `3-20` | Restricts which separator fragments are kept |
| `exclude` | boolean flag | Interprets the separator range as an exclusion window |

### Input requirements

- active image must be an 8-bit binary mask
- the mask should already be reasonably cleaned, or the watershed will split noise as if it were object structure

### Output behavior

- modifies the active image in place
- separator lines are inserted as black pixels between split objects

### Practical notes

- start with `convexity_threshold=0` and a broad separator range
- if the split is too aggressive, raise the minimum separator size or use `exclude`
- if objects remain fused, improve the mask first or increase `erosion`

## Checked-In Workflow

The repo ships a ready-to-run workflow:

- `GROOVY_WORKFLOW_PREPROCESS_AND_WATERSHED.groovy`

It performs:

1. grayscale-to-binary conversion with standard ImageJ thresholding
2. `EDM Binary Operations`
3. `Watershed Irregular Features`
4. TIFF export of the binary, EDM-cleaned, and watershed masks

### Fiji CLI example

```bash
/opt/Fiji.app/fiji-linux-x64 --headless --run \
  /app/skills/biovoxxel_toolbox_documentation/GROOVY_WORKFLOW_PREPROCESS_AND_WATERSHED.groovy \
  'inputFile="/data/example_1.tif",outputDir="/data/biovoxxel_validation/run_cli",quitWhenDone=true'
```

### Workflow parameters

| Parameter | Meaning |
|---|---|
| `inputFile` | source image on disk |
| `outputDir` | directory for exported TIFF files |
| `thresholdBlurSigma` | pre-threshold Gaussian smoothing |
| `thresholdMethod` | ImageJ auto-threshold algorithm name (e.g. `Otsu`, `Default`, `Li`); applied with `dark` background |
| `fillHoles` | run `Fill Holes` after thresholding (default `true`) |
| `edmOperation` | BioVoxxel EDM mode: `open`, `close`, `erode`, `dilate` |
| `edmIterations` | number of EDM morphology iterations |
| `quitWhenDone` | exits Fiji after workflow completion |

## Explicit Exclusions

This API file does not claim validated batch syntax for:

- `Extended Particle Analyzer`
- `Binary Feature Extractor`
- `Speckle Inspector`
- `Recursive Filters`
- `Pseudo flat field correction`

Use the Fiji macro recorder or manual GUI workflow before scripting those tools for a new automation path.

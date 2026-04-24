---
name: biovoxxel_toolbox_documentation
description: BioVoxxel Toolbox is a Fiji/ImageJ plugin suite for binary-mask cleanup, watershed splitting of irregular objects, particle screening, and filter exploration. Read the files listed at the end of this SKILL for verified commands, GUI walkthroughs, scripting examples, and common pitfalls.
---

Install from Fiji via `Help > Update... > Manage Update Sites` and enable the `BioVoxxel` update site, then restart Fiji.

## Primary Use Case in This Skill Set
Use BioVoxxel Toolbox when you need to clean a binary mask and split touching objects before downstream measurement, or when you need GUI tools for richer particle screening such as `Extended Particle Analyzer`, `Binary Feature Extractor`, or `Speckle Inspector`.

## Minimal Runnable Snippet

```groovy
import ij.IJ

def imp = IJ.openImage("/data/example_1.tif")
if (imp == null) throw new IllegalStateException("Could not open image")

IJ.run(imp, "8-bit", "")
IJ.setAutoThreshold(imp, "Otsu dark")
IJ.run(imp, "Convert to Mask", "")
IJ.run(imp, "Fill Holes", "")   // default: solid objects; drop this line if hollow interiors are meaningful

IJ.run(imp, "EDM Binary Operations", "iterations=1 operation=open")
IJ.run(imp, "Watershed Irregular Features",
    "erosion=1 convexity_threshold=0 separator_size=0-Infinity")
```

## Validated Command Quick Reference

| Mode | IJ.run() call | Key output |
|---|---|---|
| EDM cleanup | `IJ.run(maskImp, "EDM Binary Operations", "iterations=1 operation=open")` | In-place binary cleanup on the active 8-bit mask |
| Irregular-object splitting | `IJ.run(maskImp, "Watershed Irregular Features", "erosion=1 convexity_threshold=0 separator_size=0-Infinity")` | In-place binary split with separator lines inserted between touching objects |

## Critical Pitfalls

| Failure mode | Why it happens | Fix |
|---|---|---|
| `EDM Binary Operations` or `Watershed Irregular Features` aborts immediately | Both commands require an **8-bit binary** image, not grayscale or label images | Convert to 8-bit, threshold, then `Convert to Mask` before calling BioVoxxel |
| Watershed dialog rejects `separator_size` | The separator range must be a hyphenated range such as `0-Infinity` or `3-20` | Pass both ends of the range; do not omit the hyphen |
| Objects disappear instead of separating | `EDM Binary Operations` or watershed erosions are too aggressive for the object size | Reduce `iterations`, keep `operation=open`, or lower watershed `erosion` cycles |
| Headless batch calls hang or fail for some BioVoxxel commands | Several analysis tools allocate AWT or `RoiManager` windows internally | Use the validated EDM + watershed batch path; use Fiji GUI for `Extended Particle Analyzer`, `Binary Feature Extractor`, and `Speckle Inspector` |
| Batch output is unstable when using other toolbox filters directly | `Recursive Filters` and `Pseudo flat field correction` were not adopted as checked-in workflow commands in this repo | Record fresh macro strings in Fiji before scripting those commands for a new workflow |

## Parameter Tuning Quick Guide

| Observation | Adjust |
|---|---|
| Tiny burrs or narrow bridges remain in the mask | Increase `EDM Binary Operations` `iterations` from `1` to `2` while keeping `operation=open` |
| Valid thin structures are being cut away | Reduce EDM `iterations` or skip EDM cleanup and go straight to watershed |
| Touching objects stay merged after watershed | Increase watershed `erosion` from `1` to `2`, or start from a cleaner binary mask |
| Watershed inserts too many separators | Raise the minimum `separator_size`, or use `exclude` to suppress very small separator ranges |

## File Index

| File | Contents |
|---|---|
| `OVERVIEW.md` | Toolbox scope, workflow families, inputs, outputs, installation, and known limits |
| `UI_GUIDE.md` | Menu surface and control guide for the major BioVoxxel tool families |
| `UI_WORKFLOW_BINARY_MASK_CLEANUP_AND_SPLITTING.md` | Manual workflow for binary cleanup with EDM and object splitting with watershed |
| `GROOVY_API.md` | Validated `IJ.run(...)` calls and CLI invocation for the checked-in workflow |
| `GROOVY_WORKFLOW_PREPROCESS_AND_WATERSHED.groovy` | Ready-to-run batch workflow for thresholding, EDM cleanup, and watershed splitting |
| `SKILL.md` | This quick-reference card |

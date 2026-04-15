# Labkit — Groovy API Guide

This file contains only the Groovy path used by this skill.

## Plugin Call

```groovy
#@ CommandService command

import ij.ImagePlus
import java.io.File
import sc.fiji.labkit.ui.plugin.SegmentImageWithLabkitIJ1Plugin

def module = command.run(SegmentImageWithLabkitIJ1Plugin, true,
    "input",          imp,
    "segmenter_file", new File(CLASSIFIER_FILE),
    "use_gpu",        false
).get()

ImagePlus resultImp = module.getOutput("output")
```

## Preconditions

- The classifier must already exist and must have been saved from the Labkit GUI.
- The target images should be similar to the representative image used for training.
- Brightness and contrast should be normalized across the batch.
- Use a classifier path without spaces in this skill's sample workflow.

## Minimal Pattern

```groovy
#@ CommandService command

import ij.IJ
import ij.ImagePlus
import java.io.File
import sc.fiji.labkit.ui.plugin.SegmentImageWithLabkitIJ1Plugin

ImagePlus imp = IJ.openImage(INPUT_IMAGE)
imp.show()

def module = command.run(SegmentImageWithLabkitIJ1Plugin, true,
    "input",          imp,
    "segmenter_file", new File(CLASSIFIER_FILE),
    "use_gpu",        false
).get()

ImagePlus resultImp = module.getOutput("output")
IJ.saveAs(resultImp, "Tiff", OUTPUT_TIFF)
```

## Standard ImageJ Helpers

These are standard Fiji/ImageJ calls. They are not Labkit-specific.

| Purpose | Groovy call |
|---------|-------------|
| Open an image from disk | `IJ.openImage(path)` |
| Show an image window | `imp.show()` |
| Run the Labkit IJ1 plugin | `command.run(SegmentImageWithLabkitIJ1Plugin, true, ...)` |
| Read the plugin output | `module.getOutput("output")` |
| Save a TIFF result | `IJ.saveAs(resultImp, "Tiff", path)` |
| Close a window without save prompts | `imp.changes = false; imp.close()` |

## What This Guide Does Not Claim

- No scripted training API for creating a classifier.
- No Labkit parameter keys beyond `input`, `segmenter_file`, `use_gpu`, and `output` for this plugin call.
- No macro syntax for saving labelings, saving classifiers, or opening the full Labkit UI from Groovy.

Use `UI_GUIDE.md` and `UI_WORKFLOW_PIXEL_CLASSIFICATION.md` for those steps.

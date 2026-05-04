---
name: labkit_documentation
description: Labkit is a Fiji/ImageJ plugin for interactive pixel classification and manual labeling. It segments 2D/3D, multi-channel, and time-lapse images in Fiji. This skill covers the saved-classifier batch command and the Groovy execution path used in this repo, which calls `SegmentImageWithLabkitIJ1Plugin` through `CommandService`. Read the files listed at the end of this SKILL for commands, GUI walkthroughs, sample workflows, and scope limits.
---

Labkit is bundled with Fiji and opens from `Plugins > Labkit > Open Current Image With Labkit`.
Use it when you need to label representative foreground/background pixels, train a pixel classifier in the GUI, then apply the saved classifier to similar images.

## Automation Boundary

- Documented Labkit macro command: `run("Segment Image With Labkit", "segmenter_file=/abs/path/to/model.classifier use_gpu=false")`
- The Groovy workflow in this repo uses `CommandService` + `SegmentImageWithLabkitIJ1Plugin` with fields `input`, `segmenter_file`, `use_gpu`, and `output`
- This skill documents classifier training as a GUI workflow, not as a Groovy API.
- Do not invent other `IJ.run()` command names or parameter keys. Use the Macro Recorder or plugin source before extending this skill.

## File Index

| File | When to read it |
|------|-----------------|
| `GROOVY_API.md` | Read for the Labkit command used by this skill, its preconditions, and the standard ImageJ helper calls used around it. |
| `GROOVY_WORKFLOW_BATCH_SEGMENTATION.groovy` | Read or run when you need a minimal saved-classifier batch segmentation example. |
| `UI_GUIDE.md` | Read for documented menu paths, labeling tools, shortcuts, and import/export actions in the Labkit UI. |
| `UI_WORKFLOW_PIXEL_CLASSIFICATION.md` | Read for the end-to-end manual workflow: label foreground/background, train, export, and save a classifier. |
| `SKILL.md` | Read this file first for the scope and the automation boundary. |

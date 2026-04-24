---
name: bunwarpj_documentation
description: bUnwarpJ is a Fiji/ImageJ plugin for 2D elastic pairwise image registration with B-spline deformations. It supports bidirectional `Fast` and `Accurate` registration, unidirectional `Mono` registration, optional landmarks and masks, and saving elastic transformation files for reuse. In this repo, the reliable automation path is the direct Groovy API in `bunwarpj.bUnwarpJ_` rather than `IJ.run("bUnwarpJ", ...)` in headless scripts. Read the files listed at the end of this SKILL for validated Groovy workflows, GUI steps, and caveats.
---

## Automation via Groovy?

YES - via `bunwarpj.Param`, `bunwarpj.bUnwarpJ_.computeTransformationBatch(...)`,
`bunwarpj.Transformation`, and `bunwarpj.bUnwarpJ_.applyTransformToSource(...)`.

The official plugin page also documents `IJ.run("bUnwarpJ", "...")` and title-based
macro `call(...)` methods. In this repo's headless Groovy execution, the `IJ.run(...)`
path constructs `MainDialog` and is not the recommended automation entry point.

## Scope

- Container-validated:
  - direct pairwise registration with `computeTransformationBatch(...)`
  - direct result export with `getDirectResults()`
  - direct elastic transform export with `saveDirectTransformation(...)`
  - inverse result and inverse transform export in bidirectional modes
  - reapplying a saved direct elastic transform with `applyTransformToSource(...)`
- Official-doc:
  - GUI workflow under `Plugins > Registration > bUnwarpJ`
  - landmarks, masks, and toolbar I/O options
  - macro syntax via `IJ.run("bUnwarpJ", "...")`
  - title-based macro calls such as `loadElasticTransform(...)`
- Excluded from the checked-in workflow:
  - 3D registration
  - stack-mask input handling in the scripted workflow
  - headless `IJ.run("bUnwarpJ", "...")`

## File Index

| File | Contents |
| --- | --- |
| `GROOVY_API.md` | Validated direct Groovy API, official macro syntax, and headless caveats |
| `GROOVY_WORKFLOW_PAIRWISE_REGISTRATION.groovy` | Runnable 2D pairwise registration workflow with transform export and optional inverse outputs |
| `UI_GUIDE.md` | Main dialog, toolbar, masks, landmarks, and result behavior |
| `UI_WORKFLOW_PAIRWISE_REGISTRATION.md` | Step-by-step manual pairwise registration workflow |

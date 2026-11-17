---
name: bonej_documentation
description: >-
  BoneJ is a Fiji plugin suite for trabecular bone and porous-structure analysis of binary 2D/3D images - thickness/separation (Tb.Th, Tb.Sp), BV/TV, connectivity/Euler, surface area, surface fraction, fractal dimension, anisotropy (DA), skeleton analysis and purify. Use it when a task asks for morphometry of a 3D binary network (bone, scaffolds, foams, vasculature, porous material). This skill holds the container-verified Groovy API (SciJava CommandService, every wrapper takes `inputDataset`), the µm-unit and dialog pitfalls, and two runnable workflow scripts.
---

## When to use

- 3D binary structure, and the question is about thickness, spacing, volume fraction, connectivity, surface, complexity, or orientation.
- Not for counting or segmenting cells/nuclei. Use a segmentation skill first, and use MorphoLibJ or 3D ImageJ Suite for per-object measurements.

## Pipeline in this skill

```
3D stack -> (threshold to 8-bit 0/255) -> Clear BoneJ table
  -> Thickness (Tb.Th/Tb.Sp + maps) -> Area/Volume fraction (BV/TV)
  -> optional Purify -> Connectivity
  -> CSV + thickness maps                     (GROOVY_WORKFLOW_THICKNESS_AND_FRACTION.groovy)

3D binary -> Surface fraction, Surface area, Fractal dimension, Anisotropy
  -> one-row CSV                              (GROOVY_WORKFLOW_STRUCTURE_METRICS.groovy)
```

## Rules that make BoneJ scripts work (verified in the container)

1. Call commands with `command.run(Class, true, ...).get()`, never `IJ.run(...)`.
2. **The image input of every wrapper is `"inputDataset"` (a `net.imagej.Dataset`).** Passing `"inputImage"` fails with `No such input: inputImage`. Convert with `convertService.convert(imp, Dataset.class)`.
3. **Rewrite `µm` to `um` on the Dataset axes before calling BoneJ** (`toBoneJDataset()` in `SCRIPT_API.md`). Otherwise Thickness and Anisotropy throw `...#validateImage` (`Cannot parse unit: µm`), and ImageJ turns `um` into `µm` on every calibrated image.
4. Connectivity is `org.bonej.plugins.Connectivity`. **`ConnectivityWrapper` does not exist**, and importing it is a compile error.
5. Image outputs are `Dataset`s. Convert them back with `convertService.convert(ds, ImagePlus.class)` before `IJ.saveAsTiff`.
6. Check `module.isCanceled()` after every call. BoneJ cancels (with `Need a 3D (X, Y, Z) image` or `Need a binary image`) instead of throwing, and all outputs are then `null`.
7. Give `SurfaceAreaWrapper` a `stlDirectory` even with `exportSTL=false`. Without it a modal directory chooser opens and blocks the script.
8. Run `SharedTableCleaner` before each image. The returned `resultsTable` is the whole shared table, with **rows keyed by image name**.

## Pitfalls

- 3D only for Thickness, Connectivity, Anisotropy, Surface area/fraction. Never copy one 2D slice into a fake stack to get a number.
- Thresholding dominates the result. Noise specks in a `Default`-thresholded mask shifted BV/TV from 0.138 to 0.158 and Tb.Sp from 8.0 to 3.3 µm on a test lattice. Inspect or clean the mask first.
- Check the voxel size. A TIFF that carries only a 72-dpi tag opens in `inch`, and BoneJ will happily report inches.
- Thickness values are local-thickness **diameters**. Header units differ between commands (`µm` vs `um`), so match columns by prefix.
- STL export joins directory and file name without a separator. Pass `new File(outDir, "mesh_")` as `stlDirectory`.
- Analyse Skeleton on a raw mask leaves a `Skeleton of <name>` window open. Close it.
- Fiji volumes built before the image update may still hold BoneJ **7.2.0**. The API is the same except for Analyse Skeleton's image outputs, which `SCRIPT_API.md` marks.

## File Index

| File | Contents |
|------|----------|
| `SCRIPT_API.md` | Every verified call: parameters, outputs, column names, cancel reasons, helpers (`toBoneJDataset`, `runBoneJ`) |
| `GROOVY_WORKFLOW_THICKNESS_AND_FRACTION.groovy` | Runnable: threshold -> Thickness -> BV/TV -> optional Purify + Connectivity -> maps + CSV |
| `GROOVY_WORKFLOW_STRUCTURE_METRICS.groovy` | Runnable: Surface fraction, Surface area, Fractal dimension, Anisotropy -> one-row CSV |
| `UI_GUIDE.md` | Menu paths, dialog labels, input rules |
| `UI_WORKFLOW_THICKNESS_AND_FRACTION.md` | Manual click-through of the thickness/fraction/connectivity workflow |

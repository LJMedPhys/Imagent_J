# BoneJ — Script API

Ground truth for this file: the BoneJ jars installed in the container Fiji
(`bonej-plugins-7.2.2`, image `agenticj:gpu-local`), introspected through
`CommandService.getCommands()` and run live through the agent's
`ij.py.run_script("Groovy", ...)` path on a calibrated synthetic 3D lattice.
Older Fiji volumes may still hold BoneJ 7.2.0; differences are marked **7.2.0**.

## General Rules

1. BoneJ's modern commands are SciJava commands. Call them with `command.run(Class, true, ...).get()`, never with a guessed `IJ.run(...)` string.
2. **Every wrapper's image input is named `inputDataset` and has type `net.imagej.Dataset`.** There is no `inputImage` parameter. Passing `"inputImage"` fails with `IllegalArgumentException: No such input: inputImage`.
3. Convert an `ImagePlus` with `convertService.convert(imp, Dataset.class)`, then run `fixBoneJUnits(ds)` (below). Image outputs (thickness maps, skeletons, purified stacks) also come back as `Dataset`. Convert them back with `convertService.convert(outDs, ImagePlus.class)` before `IJ.saveAsTiff`.
4. **A `µm` calibration breaks Thickness and Anisotropy.** ImageJ stores the unit `um` as `µm`. BoneJ's unit parser rejects the `µ` character, so the command throws `RuntimeException: Error executing method: ...#validateImage` (the log shows `Cannot parse unit: µm`). Replace `µ`/`μ` with `u` on the Dataset axes before running any BoneJ command. The voxel size is unchanged.
5. Connectivity is **not** a wrapper class. Use `org.bonej.plugins.Connectivity`. `org.bonej.wrapperPlugins.ConnectivityWrapper` does not exist, and importing it is a Groovy compile error.
6. Measurement commands append columns to one shared BoneJ results table. Run `SharedTableCleaner` before each new image. The returned `resultsTable` is the whole shared table, not just the new columns.
7. Always check `module.isCanceled()` and `module.getCancelReason()` after `.get()`. A BoneJ command that rejects its input usually cancels instead of throwing, and then every output is `null`. Reasons seen: `Need a 3D (X, Y, Z) image`, `Need a binary image`. In the interactive GUI each cancel also opens an "ImageJ2" message dialog on the user's screen (non-blocking for the script), so validate dimensions and binariness *before* calling BoneJ.
8. Never leave a `File` input unset. `SurfaceAreaWrapper` opens a modal **"Choose a directory"** dialog for `stlDirectory` even when `exportSTL=false`, then cancels with an empty reason. Always pass `"stlDirectory", someDir`.
9. Binary convention: 8-bit, foreground `255`, background `0`. BoneJ cancels on non-binary input.
10. Groovy literals: pass `2.0d` and `1.2d` for `Double`/`double` parameters and `48L` for `long` parameters (a bare `2.0` is a `BigDecimal`).

## Standard Setup

```groovy
#@ CommandService command
#@ ConvertService convertService

import ij.IJ
import ij.ImagePlus
import net.imagej.Dataset
import net.imagej.axis.CalibratedAxis
import org.bonej.plugins.Connectivity
import org.bonej.plugins.Purify
import org.bonej.wrapperPlugins.AnalyseSkeletonWrapper
import org.bonej.wrapperPlugins.AnisotropyWrapper
import org.bonej.wrapperPlugins.ElementFractionWrapper
import org.bonej.wrapperPlugins.FractalDimensionWrapper
import org.bonej.wrapperPlugins.SkeletoniseWrapper
import org.bonej.wrapperPlugins.SurfaceAreaWrapper
import org.bonej.wrapperPlugins.SurfaceFractionWrapper
import org.bonej.wrapperPlugins.ThicknessWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner

// ImagePlus -> Dataset that BoneJ accepts (rule 3 + rule 4)
Dataset toBoneJDataset(ImagePlus imp) {
    Dataset ds = convertService.convert(imp, Dataset.class)
    if (ds == null) throw new IllegalStateException("Could not convert ImagePlus to Dataset")
    for (int d = 0; d < ds.numDimensions(); d++) {
        def axis = (CalibratedAxis) ds.axis(d)
        def unit = axis.unit()
        if (unit != null) axis.setUnit(unit.replace('µ', 'u').replace('μ', 'u'))
    }
    return ds
}

// Fail loudly instead of silently getting null outputs (rule 7)
def runBoneJ(Class cls, String label, Object... args) {
    def module = command.run(cls, true, args).get()
    if (module.isCanceled()) {
        throw new IllegalStateException(label + " canceled: " + module.getCancelReason())
    }
    return module
}
```

Because `toBoneJDataset` and `runBoneJ` call the injected services, they must be
script-level methods in the same script (Groovy script methods can see `#@`
fields). The checked-in workflows define them exactly like this.

Read a table into plain values:

```groovy
def t = module.getOutput("resultsTable")          // org.scijava.table.Table
for (int c = 0; c < t.getColumnCount(); c++) {
    println t.getColumnHeader(c) + " = " + t.get(c, 0)
}
```

## Commands

All of these were run in the container on a calibrated 96×96×64 binary lattice
(0.5 µm voxels) and returned results without dialogs. The numbers in the examples come
from that run.

### 1. Clear the shared BoneJ table

Menu: `Plugins > BoneJ > Table > Clear BoneJ results`

```groovy
command.run(SharedTableCleaner, true).get()
```

### 2. Thickness

Menu: `Plugins > BoneJ > Thickness`. Input: 3D, 8-bit binary, no hyperstack.

```groovy
Dataset ds = toBoneJDataset(binaryImp)
def thickness = runBoneJ(ThicknessWrapper, "Thickness",
    "inputDataset",  ds,
    "mapChoice",     "Both",        // "Trabecular thickness" | "Trabecular separation" | "Both"
    "showMaps",      true,          // false -> map outputs are null
    "maskArtefacts", true
)
ImagePlus tbThMap = convertService.convert(thickness.getOutput("trabecularMap"), ImagePlus.class)
ImagePlus tbSpMap = convertService.convert(thickness.getOutput("separationMap"), ImagePlus.class)
```

- Table columns: `Tb.Th Mean (µm)`, `Tb.Th Std Dev (µm)`, `Tb.Th Max (µm)` and the matching `Tb.Sp ...` columns. Thickness labels its headers from the ImagePlus calibration, so they show `µm`, while Dataset-based commands show `um` (`BV (um³)`). Uncalibrated images report `pixel`. Match columns by prefix, not by the full header string.
- The maps are 32-bit, keep the calibration, and are titled `<name>_Tb.Th` / `<name>_Tb.Sp`. Background is `NaN` when `maskArtefacts=true`.
- Mean/max are **diameters** (local thickness), not radii.

### 3. Area/Volume fraction

Menu: `Plugins > BoneJ > Fraction > Area/Volume fraction`. Input: 2D or 3D binary. Voxel counting.

```groovy
def fraction = runBoneJ(ElementFractionWrapper, "Area/Volume fraction", "inputDataset", ds)
```

Columns: `BV (um³)`, `TV (um³)`, `BV/TV` (3D) or `BA`, `TA`, `BA/TA` (2D). TV is the whole image volume.

### 4. Connectivity

Menu: `Plugins > BoneJ > Connectivity`. Class: **`org.bonej.plugins.Connectivity`**. Input: 3D binary.

```groovy
def connectivity = runBoneJ(Connectivity, "Connectivity", "inputDataset", ds)
```

Columns: `Euler ch.`, `Δ(χ)`, `Connectivity`, `Conn.D (um^-3)`.

- BoneJ assumes a **single** foreground particle. Run Purify first when the stack contains more than one.
- The shared table keys rows **by image name**. Purify's output is named `<name>_purified`, so Connectivity on it adds a *second row* rather than extending the first.
- **7.2.2** also accepts `"inputImagePlus", imp` in place of `inputDataset`. **7.2.0** accepts only `inputDataset`, so use `inputDataset` everywhere.

### 5. Purify

Menu: `Plugins > BoneJ > Purify`. Keeps the largest foreground particle and fills background cavities.

```groovy
def purify = runBoneJ(Purify, "Purify", "inputDataset", ds, "showPerformance", false, "makeCopy", true)
Dataset purified = purify.getOutput("outputDataset")   // named "<name>_purified"; resultsTable stays null
```

### 6. Surface fraction

Menu: `Plugins > BoneJ > Fraction > Surface fraction`. Input: 3D binary. Uses mesh volumes, so values differ from Area/Volume fraction. The lattice gave BV/TV 0.097 here versus 0.138 from voxel counting.

```groovy
def surfaceFraction = runBoneJ(SurfaceFractionWrapper, "Surface fraction", "inputDataset", ds)
```

Columns: `BV (um³)`, `TV (um³)`, `BV/TV`.

### 7. Surface area

Menu: `Plugins > BoneJ > Surface area`. Input: 3D binary.

```groovy
def surfaceArea = runBoneJ(SurfaceAreaWrapper, "Surface area",
    "inputDataset", ds,
    "exportSTL",    false,
    "stlDirectory", outputDir          // REQUIRED even when exportSTL=false (rule 8)
)
```

Column: `Surface area (um²)`.

STL export (`exportSTL=true`) has a path bug. BoneJ joins `stlDirectory` and the file name **without a separator**, so `stlDirectory=/out/meshes` writes `/out/meshesmyImage_.stl` *next to* the folder. Treat the parameter as a path prefix:

```groovy
"exportSTL", true,
"stlDirectory", new File(outputDir, "mesh_")   // -> <outputDir>/mesh_<imageName>_.stl
```

### 8. Fractal dimension

Menu: `Plugins > BoneJ > Fractal dimension`. Input: 2D or 3D binary.

```groovy
def fractal = runBoneJ(FractalDimensionWrapper, "Fractal dimension",
    "inputDataset",    ds,
    "autoParam",       true,     // true: BoneJ picks box sizes from the image size
    "showPoints",      false,
    "translations",    0L,
    "startBoxSize",    48L,
    "smallestBoxSize", 6L,
    "scaleFactor",     1.2d
)
```

Columns: `Fractal dimension`, `R²`.

### 9. Anisotropy

Menu: `Plugins > BoneJ > Anisotropy`. Input: 3D binary. Requires the unit fix (rule 4).

```groovy
def anisotropy = runBoneJ(AnisotropyWrapper, "Anisotropy",
    "inputDataset",           ds,
    "directions",             2000,    // Integer, min 9  (UI default 2000)
    "lines",                  10000,   // Integer, min 1  (UI default 10000)
    "samplingIncrement",      2.0d,    // Double; no default, must be passed
    "recommendedMin",         false,   // true overrides directions/lines with BoneJ's minimums
    "printRadii",             true,
    "printEigens",            false,
    "displayMILVectors",      false,
    "printMILVectorsToTable", false
)
```

Columns: `DA`, plus `Radius a/b/c` when `printRadii`. DA is 0 for isotropic structure and 1 for fully anisotropic structure.

- On a 96×96×64 stack the defaults (2000 / 10000) took about 10 s. `directions=200, lines=400` runs in about a second and is enough for a smoke test. Use the defaults or `recommendedMin=true` for reported numbers.
- Ellipsoid fitting fails on degenerate volumes, such as a 2D slice copied into a stack. The command then cancels with `Anisotropy could not be calculated - ellipsoid fitting failed`.

### 10. Skeletonise

Menu: `Plugins > BoneJ > Skeletonise`. Input: 2D or 3D, 8-bit binary.

```groovy
def skel = runBoneJ(SkeletoniseWrapper, "Skeletonise", "inputDataset", ds)
ImagePlus skeleton = convertService.convert(skel.getOutput("skeletonDataset"), ImagePlus.class)
```

The output is an 8-bit 0/255 skeleton titled `skeleton_<name>`. `resultsTable` is `null`. Check it with `new ij.process.StackStatistics(skeleton)`, because `getStatistics()` reads the current slice only.

### 11. Analyse Skeleton

Menu: `Plugins > BoneJ > Analyse Skeleton`. Input: a binary image. A non-skeleton input is skeletonised internally.

```groovy
def analysed = runBoneJ(AnalyseSkeletonWrapper, "Analyse Skeleton",
    "inputDataset",           ds,
    "pruneCycleMethod",       "None",  // "None" | "Shortest branch" | "Lowest intensity voxel" | "Lowest intensity branch"
    "pruneEnds",              false,
    "calculateShortestPaths", false,
    "verbose",                false,   // true -> verboseTable (per-branch)
    "displaySkeletons",       false
)
def skeletonTable = analysed.getOutput("resultsTable")   // ONE ROW PER SKELETON (connected component)
```

Columns: `# Skeleton`, `# Branches`, `# Junctions`, `# End-point voxels`, `# Junction voxels`, `# Slab voxels`, `Average Branch Length`, `# Triple points`, `# Quadruple points`, `Maximum Branch Length`.

Image outputs when `displaySkeletons=true`: **7.2.2** returns `taggedImage` and `treeLabeledImage`. **7.2.0** returns `labelledSkeleton`. `shortestPaths` appears when `calculateShortestPaths=true`, and `verboseTable` (one row per branch) appears when `verbose=true`.

- Pass the **binary mask**. Given a raw mask, Analyse Skeleton skeletonises it internally and leaves an ImageJ window titled `Skeleton of <name>` open. Close it with `WindowManager.getImage("Skeleton of " + imp.getTitle())?.with { changes = false; close() }`.
- Feeding it the `SkeletoniseWrapper` output instead gave a different count on the test lattice: 32 skeletons instead of 16. Use one path consistently across a dataset.

## Standard Fiji Helpers Used Around BoneJ

Threshold a grayscale stack into an 8-bit 0/255 mask. `stack` in `setAutoThreshold` uses the histogram of the whole stack, not the current slice:

```groovy
if (imp.getBitDepth() != 8) IJ.run(imp, "8-bit", "")
IJ.setAutoThreshold(imp, "Default dark stack")
IJ.run(imp, "Convert to Mask", "method=Default background=Dark black" + (imp.getNSlices() > 1 ? " stack" : ""))
```

Check binariness across the whole stack:

```groovy
boolean isBinary8Bit(ImagePlus imp) {
    if (imp.getBitDepth() != 8) return false
    def h = new ij.process.StackStatistics(imp).histogram
    return (1..254).every { h[it] == 0 }
}
```

Thresholding is outside BoneJ's measurement model, and it moves the numbers a lot. On the noisy grayscale version of the test lattice, `Default` gave BV/TV 0.158 instead of 0.138 and Tb.Sp 3.3 µm instead of 8.0 µm, because noise specks became foreground. Inspect the mask, or clean it up (e.g. remove small particles), before trusting the metrics.

Check calibration before reporting real units. A TIFF that carries only the default
72-dpi resolution tag opens with unit `inch`. BoneJ accepts that and reports in inches,
which is plausible-looking but wrong for microscopy. Set the correct voxel size with
`imp.getCalibration()` before converting.

## Not Covered As Script API

- `Plugins > BoneJ > Slice Geometry`, `Moments of Inertia`, `Particle Analyser`, `Fit Sphere`, `Ellipsoid Factor`, `Inter-trabecular angles`: present in the jar (all take `inputDataset`) but not run in this skill's validation.
- `Plugins > BoneJ > Plus > ...` (BoneJ+): needs a working OpenCL device. See `UI_GUIDE.md`.

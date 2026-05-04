# BoneJ — Script API

This file separates BoneJ's scripting surface into:

- container-validated `CommandService` calls
- standard Fiji helpers needed to prepare binary inputs
- runtime caveats where the local Fiji path differs from the official BoneJ page

## General Rules

1. The modern BoneJ commands documented here are SciJava commands. Use `command.run(...)`, not a guessed `IJ.run(...)` string.
2. `ThicknessWrapper`, `SkeletoniseWrapper`, and `AnalyseSkeletonWrapper` take `ij.ImagePlus`.
3. `ElementFractionWrapper`, `ConnectivityWrapper`, `SurfaceFractionWrapper`, `FractalDimensionWrapper`, and `AnisotropyWrapper` take `net.imagej.ImgPlus`. Convert with `convertService.convert(binaryImp, ImgPlus.class)`.
4. BoneJ measurement wrappers append columns to a shared BoneJ results table. Clear it before starting a new measurement chain with `SharedTableCleaner`.
5. The validated workflow in this skill assumes binary voxels follow ImageJ's 8-bit convention: foreground `255`, background `0`.
6. In this Fiji runtime, the documented `SurfaceAreaWrapper` canceled on 8-bit binary `ImgPlus` inputs. The validated scripting path for surface area converts the binary image to `BitType` and calls BoneJ's underlying marching-cubes and boundary-size ops directly.

## Standard Setup

Inject these services at the top of a Groovy script:

```groovy
#@ CommandService command
#@ ConvertService convertService

import ij.IJ
import ij.ImagePlus
import net.imagej.ImgPlus
import org.bonej.wrapperPlugins.AnalyseSkeletonWrapper
import org.bonej.wrapperPlugins.AnisotropyWrapper
import org.bonej.wrapperPlugins.ConnectivityWrapper
import org.bonej.wrapperPlugins.ElementFractionWrapper
import org.bonej.wrapperPlugins.FractalDimensionWrapper
import org.bonej.wrapperPlugins.SkeletoniseWrapper
import org.bonej.wrapperPlugins.SurfaceFractionWrapper
import org.bonej.wrapperPlugins.ThicknessWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner
```

Convert an `ImagePlus` when a BoneJ wrapper expects `ImgPlus`:

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)
if (binaryImgPlus == null) {
    throw new IllegalStateException("Could not convert ImagePlus to ImgPlus for BoneJ")
}
```

## Container-Validated Automation

### 1. Clear the shared BoneJ table

Use this before a new measurement chain:

```groovy
command.run(SharedTableCleaner, true).get()
```

If you do not clear it, later BoneJ measurements may append columns onto the same row from previous BoneJ commands.

### 2. Thickness

Official menu path: `Plugins > BoneJ > Thickness`

Suitable input from the official docs: 3D, 8-bit, binary, no hyperstack.

```groovy
def thicknessModule = command.run(ThicknessWrapper, true,
    "inputImage",    binaryImp,
    "mapChoice",     "Both",
    "showMaps",      true,
    "maskArtefacts", true
).get()

def thicknessTable = thicknessModule.getOutput("resultsTable")
ImagePlus trabecularMap = thicknessModule.getOutput("trabecularMap")
ImagePlus separationMap = thicknessModule.getOutput("separationMap")
```

Validated parameter values:

| Parameter | Accepted values in this repo pass |
|-----------|-----------------------------------|
| `mapChoice` | `Trabecular thickness`, `Trabecular separation`, `Both` |
| `showMaps` | `true` or `false` |
| `maskArtefacts` | `true` or `false` |

Validated outputs:

- `resultsTable` with `Tb.Th` and/or `Tb.Sp` summary columns
- `trabecularMap` when thickness was requested and `showMaps=true`
- `separationMap` when separation was requested and `showMaps=true`

Saved thickness maps remained 32-bit float TIFFs in the container validation run. Background pixels can come back as `NaN` when the saved TIFF is read outside Fiji.

### 3. Area/Volume fraction

Official menu path: `Plugins > BoneJ > Fraction > Area/Volume fraction`

Suitable input from the official docs: 2D or 3D 8-bit binary image.

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)

def fractionModule = command.run(ElementFractionWrapper, true,
    "inputImage", binaryImgPlus
).get()

def sharedTable = fractionModule.getOutput("resultsTable")
```

Validated outputs appended to the shared BoneJ table:

- `BV` or `BA`
- `TV` or `TA`
- `BV/TV` or `BA/TA`

When this command is run after `ThicknessWrapper` without clearing the BoneJ table, the returned table contains both the thickness columns and the fraction columns in a single row.

### 4. Connectivity (Modern)

Official menu path: `Plugins > BoneJ > Connectivity > Connectivity (Modern)`

Suitable input from the official docs: 3D binary image. BoneJ recommends a single foreground particle; use `Purify` first when you need that assumption.

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)

def connectivityModule = command.run(ConnectivityWrapper, true,
    "inputImage", binaryImgPlus
).get()

def sharedTable = connectivityModule.getOutput("resultsTable")
```

Validated outputs appended to the shared BoneJ table:

- `Euler char. (χ)`
- `Corr. Euler (χ + Δχ)`
- `Connectivity`
- `Conn.D`

### 5. Surface fraction

Official menu path: `Plugins > BoneJ > Fraction > Surface fraction`

Suitable input from the official docs: 3D binary image.

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)

def surfaceFractionModule = command.run(SurfaceFractionWrapper, true,
    "inputImage", binaryImgPlus
).get()

def surfaceFractionTable = surfaceFractionModule.getOutput("resultsTable")
```

Validated outputs:

- `BV`
- `TV`
- `BV/TV`

This wrapper executed successfully on a volumetric synthetic sphere stack in the container.

### 6. Fractal dimension

Official menu path: `Plugins > BoneJ > Fractal dimension`

Suitable input from the official docs: 2D or 3D binary image.

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)

def fractalModule = command.run(FractalDimensionWrapper, true,
    "inputImage",      binaryImgPlus,
    "autoParam",       true,
    "showPoints",      false,
    "translations",    0L,
    "startBoxSize",    48L,
    "smallestBoxSize", 6L,
    "scaleFactor",     1.2d
).get()

def fractalTable = fractalModule.getOutput("resultsTable")
```

Validated outputs:

- `Fractal dimension`
- `R²`

Validated note:

- `autoParam=true` worked on the volumetric synthetic sphere used in the local container pass.

### 7. Anisotropy

Official menu path: `Plugins > BoneJ > Anisotropy`

Suitable input from the official docs: 3D binary image.

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)

def anisotropyModule = command.run(AnisotropyWrapper, true,
    "inputImage",             binaryImgPlus,
    "directions",             200,
    "lines",                  400,
    "samplingIncrement",      2.0d,
    "recommendedMin",         false,
    "printRadii",             true,
    "printEigens",            false,
    "displayMILVectors",      false,
    "printMILVectorsToTable", false
).get()

def anisotropyTable = anisotropyModule.getOutput("resultsTable")
```

Validated outputs from the local successful run:

- `DA`
- `Radius a`
- `Radius b`
- `Radius c`

Runtime caveat:

- This wrapper is sensitive to sample geometry. It canceled on a duplicated single-slice validation stack with `Anisotropy could not be calculated - ellipsoid fitting failed`.
- It succeeded on a genuine 3D directional rod lattice.

### 8. Surface area through the validated lower-level path

Official menu path: `Plugins > BoneJ > Surface area`

Official docs describe the wrapper input as a 3D binary image. In this repo's container, the documented `SurfaceAreaWrapper` canceled without a result table. The underlying BoneJ/ImageJ ops did work after converting the binary `ImgPlus` to `BitType`.

Add these imports when using the lower-level path:

```groovy
#@ OpService opService

import net.imagej.mesh.Mesh
import net.imagej.mesh.naive.NaiveFloatMesh
import net.imagej.ops.Ops.Geometric.BoundarySize
import net.imagej.ops.Ops.Geometric.MarchingCubes
import net.imagej.ops.special.function.Functions
import net.imglib2.type.numeric.real.DoubleType
```

Validated surface-area path:

```groovy
ImgPlus binaryImgPlus = convertService.convert(binaryImp, ImgPlus.class)
def bitImg = opService.convert().bit(binaryImgPlus)
ImgPlus bitImgPlus = new ImgPlus(bitImg, binaryImgPlus)

def marchingCubesOp = Functions.unary(opService, MarchingCubes.class, Mesh.class, bitImgPlus)
Mesh mesh = marchingCubesOp.calculate(bitImgPlus)

def areaOp = Functions.unary(opService, BoundarySize.class, DoubleType.class, new NaiveFloatMesh())
double surfaceArea = areaOp.calculate(mesh).get()
```

Validated output:

- scalar surface area value from the mesh boundary-size op

Runtime divergence from official docs:

- The BoneJ page documents `Surface area` as a standard 3D binary-image tool.
- In the local Fiji runtime the wrapper itself canceled on an 8-bit binary `ImgPlus`.
- The lower-level marching-cubes path succeeded once the input was converted to `BitType`.

### 9. Skeletonise

Official menu path: `Plugins > BoneJ > Skeletonise`

Suitable input from the official docs: 2D or 3D, 8-bit, binary, no hyperstack.

```groovy
def skeletoniseModule = command.run(SkeletoniseWrapper, true,
    "inputImage", binaryImp
).get()

ImagePlus skeleton = skeletoniseModule.getOutput("skeleton")
```

Validated output:

- `skeleton` as an 8-bit ImagePlus

The `resultsTable` output stayed `null` in the container validation run, so consume the skeleton image rather than relying on table output from this wrapper.

### 10. Analyse Skeleton

Official menu path: `Plugins > BoneJ > Analyse Skeleton`

Suitable input from the official docs: 2D or 3D, 8-bit, binary, no hyperstack.

```groovy
def analyseModule = command.run(AnalyseSkeletonWrapper, true,
    "inputImage",              binaryImp,
    "pruneCycleMethod",        "None",
    "pruneEnds",               false,
    "calculateShortestPaths",  false,
    "verbose",                 false,
    "displaySkeletons",        false
).get()

def skeletonResults = analyseModule.getOutput("resultsTable")
```

Validated `pruneCycleMethod` choices:

- `None`
- `Shortest branch`
- `Lowest intensity voxel`
- `Lowest intensity branch`

Validated outputs:

- `resultsTable`
- `labelledSkeleton` when skeleton display outputs are enabled
- `shortestPaths` when shortest-path output is enabled

## Standard Fiji Helpers Used Around BoneJ

These are standard Fiji calls, not BoneJ wrappers.

Convert a grayscale image to an 8-bit binary mask:

```groovy
if (imp.getBitDepth() != 8) {
    IJ.run(imp, "8-bit", "")
}
IJ.setAutoThreshold(imp, "Default dark")
IJ.run(imp, "Convert to Mask", "method=Default background=Dark black stack")
```

Duplicate a single 2D slice into a small stack when you only have a slice-level sample image and need to exercise a 3D BoneJ command:

```groovy
import ij.ImageStack
import ij.ImagePlus

ImageStack stack = new ImageStack(imp.getWidth(), imp.getHeight())
for (int i = 0; i < 6; i++) {
    stack.addSlice(imp.getProcessor().duplicate())
}
ImagePlus stackedImp = new ImagePlus("stacked", stack)
stackedImp.setCalibration(imp.getCalibration())
```

## UI-Only Or Legacy Surface

### Legacy UI tools

Legacy menu-driven tools such as `Slice Geometry` are intentionally left as UI-only in this skill. They are not presented here as validated Groovy API.

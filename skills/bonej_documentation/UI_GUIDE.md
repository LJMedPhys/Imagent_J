# BoneJ — UI Guide

Menu paths and dialog labels below were read from the installed BoneJ 7.2.2 commands (`CommandService`) in the container Fiji.

## Installation

Enable BoneJ from Fiji's updater:

1. Open `Help > Update...`
2. Click `Manage update sites`
3. Check `BoneJ`
4. Close the update-site dialog
5. Click `Apply changes`
6. Restart Fiji after the downloads finish

## Results Table

Menu path: `Plugins > BoneJ > Table > Clear BoneJ results`

BoneJ measurement wrappers share one BoneJ results table, with one row per image name. Clear it before starting a new measurement chain if you want a fresh row or a fresh set of columns.

## Thickness

Menu path: `Plugins > BoneJ > Thickness`

Official input rules:

- 3D
- 8-bit
- binary
- no hyperstack

Documented controls:

- `Calculate`: `Trabecular thickness`, `Trabecular separation`, or `Both`
- `Show thickness maps`
- `Mask thickness maps`

Expected outputs:

- summary values for `Tb.Th` and/or `Tb.Sp`
- one or two 32-bit thickness map windows (`<name>_Tb.Th`, `<name>_Tb.Sp`) when map display is enabled
- values are local-thickness diameters in the image's calibrated unit

If the image is calibrated in `µm`, the menu command may fail with `Cannot parse unit: µm`. In that case set `Image > Properties > Unit of length` to `micron` and run it again.

## Area/Volume Fraction

Menu path: `Plugins > BoneJ > Fraction > Area/Volume fraction`

Official input rules:

- 2D or 3D
- 8-bit binary
- ROI Manager selections are respected

Expected outputs:

- `BV` or `BA`
- `TV` or `TA`
- `BV/TV` or `BA/TA`

When this command is run after another BoneJ measurement without clearing the BoneJ table first, the same BoneJ results row can gain additional columns.

## Connectivity

Menu path: `Plugins > BoneJ > Connectivity`

Official input rules:

- 3D
- binary

Official caveat:

- BoneJ assumes the foreground is a single particle. If the image contains multiple foreground objects, the docs recommend `Plugins > BoneJ > Purify` first.

Expected outputs:

- `Euler ch.`
- `Δ(χ)`
- `Connectivity`
- `Conn.D (unit^-3)`

## Purify

Menu path: `Plugins > BoneJ > Purify`

Keeps the largest foreground particle and the largest background particle, which fills cavities. Controls: `Performance Log` and `Make copy`. The copy is named `<name>_purified`, and BoneJ results for it go into a separate table row.

## Surface Fraction

Menu path: `Plugins > BoneJ > Fraction > Surface fraction`

Official input rules:

- 3D
- binary

Expected outputs:

- `BV`
- `TV`
- `BV/TV`

## Fractal Dimension

Menu path: `Plugins > BoneJ > Fractal dimension`

Official input rules:

- 2D or 3D
- binary

Documented controls:

- `Starting box size (px)`
- `Smallest box size (px)`
- `Box scaling factor`
- `Grid translations`
- `Automatic parameters`
- `Show points`

Expected outputs:

- `Fractal dimension`
- `R²`

## Anisotropy

Menu path: `Plugins > BoneJ > Anisotropy`

Official input rules:

- 3D
- binary

Documented controls:

- `Directions`
- `Lines per direction`
- `Sampling increment`
- `Recommended minimums`
- `Show radii`
- `Show Eigens`
- `Display MIL vectors`
- `Print MIL vectors`

Defaults: 2000 directions × 10000 lines. The `Sampling increment` must be filled in.

Practical note from the validated container pass:

- This tool needs a representative 3D structure. Degenerate validation stacks can fail the ellipsoid fit even when the command path itself is correct.

## Surface Area

Menu path: `Plugins > BoneJ > Surface area`

Official input rules:

- 3D
- binary

Documented controls:

- `Export STL`
- `STL directory`

Expected outputs in the UI docs:

- `Surface area`
- optional STL export

Practical notes from the validated container pass:

- The `STL directory` field is required even when `Export STL` is unchecked. Leaving it empty opens a directory chooser.
- BoneJ appends the file name to the chosen path without a `/`. Choosing `/data/meshes` writes `/data/meshesimage_.stl`, next to the folder rather than inside it.

## Skeletonise

Menu path: `Plugins > BoneJ > Skeletonise`

Official input rules:

- 2D or 3D
- 8-bit
- binary
- no hyperstack

Expected output:

- an 8-bit skeleton image

## Analyse Skeleton

Menu path: `Plugins > BoneJ > Analyse Skeleton`

Official input rules:

- 2D or 3D
- 8-bit
- binary
- no hyperstack

Documented controls:

- `Cycle pruning method` (`None`, `Shortest branch`, `Lowest intensity voxel`, `Lowest intensity branch`)
- `Prune ends`
- `Calculate largest shortest paths`
- `Show detailed info`
- `Display skeleton images`

Expected outputs:

- a skeleton statistics table, one row per skeleton (connected component)
- optional tagged/labelled skeleton and shortest-path images when those outputs are requested
- a `Skeleton of <name>` window when the input was a mask and not already a skeleton

## Other BoneJ Menus In Scope As Documentation Only

These menus exist in the installed BoneJ but are not part of this skill's validated workflows:

- `Plugins > BoneJ > Slice Geometry`
- `Plugins > BoneJ > Moments of Inertia`
- `Plugins > BoneJ > Particle Analyser`
- `Plugins > BoneJ > Fit Sphere`, `Fit ellipsoid`
- `Plugins > BoneJ > Ellipsoid Factor`
- `Plugins > BoneJ > Inter-trabecular angles`
- `Plugins > BoneJ > Analyze > Calibrate SCANCO`, `Orientation`
- `Image > Stacks > Check Voxel Depth`, `Delete Slice Range`

## BoneJ Plus Menu

The `Plugins > BoneJ > Plus` submenu exists separately from the standard BoneJ wrapper commands documented in this skill.

Official docs note:

- `Plugins > BoneJ > Plus > Check GPUs` should be run after install or hardware changes
- BoneJ+ commands depend on a working OpenCL environment

This skill does not provide a checked-in workflow for the `Plus` submenu.

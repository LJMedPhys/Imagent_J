# BoneJ — UI Guide

This guide keeps to the BoneJ menu surface that is either container-validated in this repo or directly documented on the official BoneJ page.

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

BoneJ measurement wrappers share one BoneJ results table. Clear it before starting a new measurement chain if you want a fresh row or a fresh set of columns.

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
- one or two 32-bit thickness map windows when map display is enabled

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

## Connectivity (Modern)

Menu path: `Plugins > BoneJ > Connectivity > Connectivity (Modern)`

Official input rules:

- 3D
- binary

Official caveat:

- BoneJ assumes the foreground is a single particle. If the image contains multiple foreground objects, the docs recommend `Plugins > BoneJ > Purify` first.

Expected outputs:

- `Euler char. (χ)`
- `Corr. Euler (χ + Δχ)`
- `Connectivity`
- `Conn.D`

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
- `Recommended minimum`
- `Show radii`
- `Show Eigens`
- `Display MIL vectors`
- `Print MIL vectors`

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

Practical note from the validated container pass:

- The menu item is part of BoneJ's official UI surface, but the checked-in scripting path in this repo uses lower-level marching-cubes and boundary-size ops because `SurfaceAreaWrapper` canceled silently in the local Fiji runtime.

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

- `Prune cycle method`
- `Prune ends`
- `Calculate shortest paths`
- `Verbose`
- `Display skeletons`

Expected outputs:

- a skeleton statistics table
- optional labelled skeleton and shortest-path images when those outputs are requested

## Other BoneJ Menus In Scope As Documentation Only

These menus are part of BoneJ's official UI surface, but they are not the checked-in automation path in this skill:

- `Plugins > BoneJ > Slice Geometry`

## BoneJ Plus Menu

The `Plugins > BoneJ > Plus` submenu exists separately from the standard BoneJ wrapper commands documented in this skill.

Official docs note:

- `Plugins > BoneJ > Plus > Check GPUs` should be run after install or hardware changes
- BoneJ+ commands depend on a working OpenCL environment

This skill does not provide a checked-in workflow for the `Plus` submenu.

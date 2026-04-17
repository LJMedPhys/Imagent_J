# BoneJ — UI Workflow For Thickness And Fraction

Use this workflow when you already have an 8-bit binary 3D stack and want BoneJ thickness maps plus a compact volume-fraction summary.

## Preconditions

- BoneJ is installed and Fiji has been restarted
- The input image is open
- The input image is 3D, 8-bit, and binary

## Workflow

1. Clear BoneJ's shared table with `Plugins > BoneJ > Table > Clear BoneJ results`.
2. Run `Plugins > BoneJ > Thickness`.
3. In the Thickness dialog:
   - Set `Calculate` to `Both`.
   - Keep `Show thickness maps` enabled.
   - Keep `Mask thickness maps` enabled.
4. Click `OK`.
5. Inspect the two new map windows for trabecular thickness and trabecular separation.
6. Run `Plugins > BoneJ > Fraction > Area/Volume fraction`.
7. Read the BoneJ results table. It should now contain:
   - `Tb.Th` summary columns
   - `Tb.Sp` summary columns
   - `BV`
   - `TV`
   - `BV/TV`

## Optional Connectivity Step

Run this only when the foreground is a single connected particle or after purifying the stack.

1. If needed, run `Plugins > BoneJ > Purify` first.
2. Run `Plugins > BoneJ > Connectivity > Connectivity (Modern)`.
3. Read the additional BoneJ table columns:
   - `Euler char. (χ)`
   - `Corr. Euler (χ + Δχ)`
   - `Connectivity`
   - `Conn.D`

## Save Outputs

1. Activate each thickness map window and save it as TIFF.
2. Activate the BoneJ results table window and save it as CSV.

## Notes

- BoneJ appends new measurement columns to its shared results table. Clearing the table at the beginning keeps this workflow's outputs together.
- `Connectivity (Modern)` is intended for a single foreground structure. Multiple disconnected objects can produce misleading values.

# BioVoxxel Toolbox — UI Workflow: Binary Mask Cleanup and Splitting

This walkthrough uses the BioVoxxel commands that map directly onto the checked-in batch workflow:

1. create a binary mask
2. clean it with `EDM Binary Operations`
3. split touching objects with `Watershed Irregular Features`

## Preconditions

- Fiji has the `BioVoxxel` update site enabled and restarted
- Your image contains bright objects on a darker background
- The image can be converted to a sensible 8-bit binary mask

## Step 1 — Prepare a Binary Mask

1. Open your image with `File > Open`.
2. Convert to 8-bit if needed with `Image > Type > 8-bit`.
3. Use `Image > Adjust > Threshold...`.
4. Choose a threshold method that captures the full object interiors.
5. Click `Apply` or use `Process > Binary > Convert to Mask`.
6. Run `Process > Binary > Fill Holes`. This is the default here because downstream watershed works best on solid objects; skip it only if hollow interiors are meaningful in your data.

Expected result:

- foreground objects are white
- background is black
- the mask contains only `0` and `255`

## Step 2 — Clean the Mask with EDM Binary Operations

1. Open `Plugins > BioVoxxel > EDM Binary Operations`.
2. Set `iterations` to `1`.
3. Choose `operation = open`.
4. Preview the result, then click `OK`.

What to look for:

- isolated one-pixel specks should disappear
- very thin white bridges between nearby objects should shrink or vanish
- large object interiors should remain intact

If valid thin structures are lost, undo and retry with fewer iterations or skip this step.

## Step 3 — Split Touching Objects with Watershed Irregular Features

1. Open `Plugins > BioVoxxel > Watershed Irregular Features`.
2. Start with:
   - `erosion cycle number = 1`
   - `convexity_threshold = 0`
   - `separator_size = 0-Infinity`
   - leave `exclude` unchecked
3. Use the preview if needed, then click `OK`.

What to look for:

- black separator lines appear where merged white objects were previously fused
- each object remains mostly intact after splitting
- over-splitting shows up as many short black cuts inside single objects

## Step 4 — Save the Result

Use `File > Save As > Tiff...` and write the cleaned / split binary mask to a new path.

## Interpretation

| Output stage | How to read it |
|---|---|
| Binary mask | White pixels are accepted foreground; black pixels are rejected background |
| After EDM open | A good result removes tiny artifacts and weak bridges without shrinking large objects excessively |
| After watershed | Black separator lines define object boundaries; successful splitting turns fused clumps into separate white objects |

Good output:

- objects are separated where they visibly touch
- no obvious object is broken into many fragments
- the number of particles is plausible for the scene

Bad output:

- large white regions disappear after EDM cleanup
- watershed inserts many short separators inside single objects
- touching objects remain as a single merged component

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Small specks remain after cleanup | EDM pass too weak | Increase `iterations` from `1` to `2` |
| Thin real structures disappear | EDM cleanup too strong | Reduce `iterations` or skip EDM cleanup |
| Watershed splits one object into many fragments | Separator search is too permissive | Increase the minimum `separator_size` or use `exclude` to reject tiny separators |
| Watershed does not separate touching objects | Binary mask still contains thick bridges | Improve thresholding first, then retry watershed; if needed raise `erosion cycle number` |
| Plugin refuses the image | Image is not 8-bit binary | Convert to 8-bit and re-apply `Convert to Mask` |

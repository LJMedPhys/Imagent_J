---
name: bigstitcher_documentation
description: A Fiji plugin for stitching and fusing multi-tile, multi-angle, multi-TB microscopy datasets.Stores all state in an XML project file; uses BigDataViewer for interactive display. Primary use cases are cleared-tissue lightsheet stitching, tiled confocal reconstruction, multi-view lightsheet registration. Read the files listed at the end of this SKILL for verified commands, GUI walkthroughs, scripting examples, and common pitfalls. 
---


# BigStitcher — Skill Quick Reference

---

## Can BigStitcher Be Automated via Groovy?

**YES — fully.** All BigStitcher processing steps are exposed as
macro-recordable commands under `Plugins › BigStitcher › Batch Processing`.
These are callable from Groovy (and any other Fiji scripting language) via
`IJ.run()`. The complete pipeline — dataset definition, phase correlation,
global optimization, fusion — can be run from the Fiji Script Editor:

```groovy
IJ.run("Calculate pairwise shifts ...", "select=/path/to/dataset.xml ...")
IJ.run("Optimize globally and apply shifts ...", "select=/path/to/dataset.xml ...")
// NOTE: In many BigStitcher versions the fusion command is recorded as "Image Fusion" (not "Fuse dataset ...").
// Always confirm the exact command name via Plugins › Macros › Record…
IJ.run("Image Fusion", "select=/path/to/dataset.xml ...")
```

Use the **Macro Recorder** (`Plugins › Macros › Record…`) to capture exact
parameter strings while working interactively — then paste them into your
Groovy script.

---

## Processing Pipeline (Stitching Mode)

```
Step 1 — Define dataset         →  IJ.run("Define Multi-View Dataset") *(or similar; command name is version-dependent — use Macro Recorder)*
Step 2 — Calculate pairwise shifts  →  IJ.run("Calculate pairwise shifts ...")
Step 3 — Filter links               →  IJ.run("Filter pairwise shifts ...")
Step 4 — Global optimization        →  IJ.run("Optimize globally and apply shifts ...")
Step 5 — ICP refinement (optional)  →  IJ.run("ICP Refinement ...")
Step 6 — Fuse / Image Fusion         →  IJ.run("Image Fusion")  *(command name depends on BigStitcher version; use Macro Recorder)*
```

All steps are fully automatable via `IJ.run()`. Each call is synchronous and
operates on the shared XML project file.

---

## Key Parameters (All Steps)

| Parameter | Typical value | Notes |
|---|---|---|
| `GRID_TYPE` | `[Snake: Right & Down      ]` | **6 trailing spaces required** — use Macro Recorder if changing this |
| `tiles_x`, `tiles_y` | dataset-specific | From acquisition settings |
| `overlap_x_(%)` | `10` | Match your acquisition overlap |
| `downsample_in_x/y/z` | `2` | Use `4` for faster/coarser result |
| `min_r` | `0.7` | Cross-correlation threshold for link filtering |
| `global_optimization_strategy` | `Two-Round using metadata to align unconnected Tiles` *(exact capitalization varies by BigStitcher version)* | Always copy exactly from the Macro Recorder dropdown (**case/spacing sensitive**). In Fiji 2.16.0/1.54p (Java 21) we observed 5 valid strings: `One-Round`; `One-Round with iterative dropping of bad links`; `Two-Round using metadata to align unconnected Tiles`; `Two-Round using Metadata to align unconnected Tiles and iterative dropping of bad links`; `NO global optimization, just store the corresponding interest points`. |
| `fix_group_0-0,` | always | Trailing comma required |
| `pixel_type` in Fuse | `16-bit unsigned integer` | For fluorescence data |

---

## Critical Pitfalls

1. **`grid_type` trailing spaces cause "unrecognized command"** — this is the
   most common failure with Define Dataset. The value `[Snake: Right & Down      ]`
   has exactly 6 trailing spaces. Missing even one produces a silent mismatch.
   Use the Macro Recorder once to capture the exact value for your scan direction.
2. **Trailing comma in `fix_group_0-0,`** — required; missing it breaks the
   global optimization reference frame.
3. **Re-save to a different path than input** — writing HDF5 into the same
   folder as raw files is allowed but can cause confusion; use a subdirectory.
4. **Fusion before optimization** — fusing with unregistered positions produces
   a broken output. Always run optimize → (ICP) → fuse in order.
5. **ICP requires sufficient shared signal** — if tiles share little overlap
   content, affine ICP will diverge. Use translation model as fallback.
6. **`org.janelia.saalfeldlab.n5.N5Exception: Can't make a dataset on existing dataset`
   — a leftover output from a PREVIOUS attempt, not a bug in your parameters.**
   BigStitcher's re-save writes N5/Zarr/HDF5, and those are **directories**, not
   files. A retry that only cleans files leaves them behind, and the next run finds
   an existing dataset where it expected clean ground. This bites hardest when the
   stale output sits in the *input* folder that Define Dataset scans.

   The naive cleanup is wrong — `isFile()` skips exactly the thing you need gone:
   ```groovy
   dir.listFiles()?.each { if (it.isFile()) it.delete() }          // WRONG: skips dataset.ome.zarr/
   dir.listFiles()?.each { it.isDirectory() ? it.deleteDir() : it.delete() }   // RIGHT
   ```
   Observed for real: a run left a 681 MB `dataset.ome.zarr/` (30,210 files) in the
   tile input folder; every retry rewrote the 64 tiles beside it and failed again
   with the same N5Exception. If you hit this, delete the stale `*.zarr` / `*.n5` /
   `*.h5` **directory** before re-running — re-running unchanged cannot succeed.
   Keep the re-save target OUT of the input folder as well (see pitfall 3).
7. **"Missing stage coordinates" on a Zeiss LSM mosaic — the positions ARE there,
   you are reading the wrong place.** Bio-Formats leaves OME `StageLabel` null for
   LSM, so `Image.getStageLabel()` returns null for every series and a script that
   trusts it concludes the file has no tile positions. A real run then reported
   `Missing stage coordinates for series 0` → `Positioned series count=0 (< 64)`,
   fell back to inferring the lattice, and produced `Expected 8 axis groups, got 9`
   — all for a file whose grid was perfectly regular.

   The positions live in the vendor block. Get them from the metadata tool
   (`extract_image_metadata` reports `dimensions.mosaic_grid`) or directly:
   ```python
   import tifffile, numpy as np
   md = tifffile.TiffFile(path).lsm_metadata
   tp = np.asarray(md['TilePositions'])          # (n_tiles, 3), METRES
   ux, uy = np.unique(tp[:,0].round(9)), np.unique(tp[:,1].round(9))   # grid_x, grid_y
   ```
   **Round before uniquing** — float noise is what turns 8 rows into "9 axis groups".
   For the reference dataset this yields 64 tiles, an exact 8x8 grid, 382.59 um step
   against a 425.1 um tile = **10.0% overlap**, which you can hand straight to
   `Move Tile to Grid` instead of asking BigStitcher to discover it.

---

## Automation Pathways Summary

| Pathway | Best for |
|---|---|
| BigStitcher GUI | Interactive exploration, visual QC, manual link curation |
| `IJ.run()` in Groovy | Scripted pipeline automation from the Fiji Script Editor |

---

## File Inventory

| File | Contents |
|---|---|
| `OVERVIEW.md` | Plugin description, pipeline, formats, automation pathways, installation |
| `UI_GUIDE.md` | Every dialog parameter with values and notes |
| `UI_WORKFLOW_STITCHING.md` | Step-by-step GUI walkthrough for tile stitching |
| `GROOVY_SCRIPT_API.md` | Full IJ.run() API reference with all pipeline commands |
| `WORKFLOW_TILE_STITCHING.groovy` | Ready-to-run Groovy pipeline script (Fiji Script Editor) |
| `SKILL.md` | This quick-reference card |
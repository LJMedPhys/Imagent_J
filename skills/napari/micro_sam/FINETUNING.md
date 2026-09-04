# Fine-tuning micro_sam on a user's own annotations

The playbook for "teach the model what I mean" — the user corrects a handful of small image
tiles, micro_sam trains on them, and the result is measured before anything else uses it.

Four scripts, run in order, all via **`python_data_analyst`** with `# imagentj-env: napari-mcp`.
Never via `mcp__napari_mcp__execute_code`: that runs on napari's Qt thread under a 90 s timeout,
and a guard blocks the heavy calls anyway.

| | script | who does the work | how long |
|---|---|---|---|
| 1 | `WORKFLOW_FINETUNE_1_PREPARE.py` | **the user picks the tiles**, in napari; then the agent | 2-3 min + 1-3 min |
| 2 | `WORKFLOW_FINETUNE_2_ANNOTATE.py` | **the user**, in napari | 2-4 min per tile |
| 3 | `WORKFLOW_FINETUNE_3_TRAIN.py` | agent (GPU) | 10-20 min |
| 4 | `WORKFLOW_FINETUNE_4_APPLY.py` | agent | ~1 s per image on GPU |

Each script has a CONFIG block at the top; `copy_file` the template, edit CONFIG, run.
They talk to each other through `<TASK_DIR>/manifest.json` and `<TASK_DIR>/evaluation.json`,
so after stage 1 the only thing to set is `TASK_DIR`.

---

## The idea: the user never annotates a whole image

micro_sam's automatic instance segmentation (AIS) decoder — the thing that lets you segment a
folder hands-off — can only be trained on **densely** annotated data. Every object inside the
annotated field must be labelled, because anything left unlabelled teaches the decoder
"background". micro_sam's own docs put the alternative bluntly: *"It's okay to use sparse
segmentations (i.e. few objects per image are annotated) for just finetuning Segment Anything
**without the additional decoder**."* Sparse annotation is allowed — it just costs you AIS, so
the fine-tuned model could only be used by clicking, one object at a time, forever.

The way out is not sparser annotation, it is a **smaller field**: cut 512x512 tiles out of the
images and annotate those completely. A tile is dense by construction, so the decoder trains
normally, and 8 tiles is ~20 minutes instead of a day. The user annotates every object in a few
small squares, never every object in an image. That is the whole design.

Stage 1 also pre-segments each tile with the stock model and loads that into the annotator, so
the user is **correcting a first guess, not drawing from scratch** — usually a handful of fixes
per tile.

---

## Before you start — is fine-tuning even needed?

Fine-tuning costs the user 20 minutes of their attention. Spend it only when it buys something.

1. **Try the stock model first.** Run `WORKFLOW_AUTOMATIC_SEGMENTATION.py` (or stage 1, which
   pre-segments as a side effect) and look at `previews/*.png` with `vlm_judge` or show them to
   the user. If the stock `vit_b_lm` is already right, say so and stop.
2. **Check the hardware.** `torch.cuda.is_available()`. On CPU stage 3 takes **hours**, not
   minutes. Tell the user the number before they annotate — not after.
3. **Check there is enough data.** Fewer than ~4 usable tiles and stage 3 refuses; 6-10 is the
   reliable range.
4. **Check the data is not already in the stock model's training set.** The `*_lm` generalists
   were trained on LIVECell, DeepBacs, TissueNet, NeurIPS CellSeg, PlantSeg (root), Nucleus DSB
   and eight Cell Tracking Challenge datasets (*Segment Anything for Microscopy*, Nat Methods
   2024, s41592-024-02580-4). If the user's data looks like one of those — standard
   fluorescence nuclei, phase-contrast cell lines, bacteria — the stock model has already seen
   thousands of such images and 8 tiles will not beat it. Fine-tuning pays off on data those
   sets do not cover: organoids, unusual stains, unusual optics, non-standard organisms.
5. **Fine-tuning teaches SHAPE and APPEARANCE, not categories.** "Only count the infected
   cells" is a classification job → Pattern 3 in `SKILL.md` (the object classifier, a random
   forest trained in seconds). Fine-tuning is for "it keeps missing my cells / splitting them /
   outlining debris".

---

## Stage 1 — the user picks the tiles, then the agent prepares them

Set `INPUT_DIR`, `TASK_DIR`, **`GROUP_REGEX`**, and for 3D input `CHANNEL`. Defaults:
`PICK_MODE="interactive"`, `TILE_SIZE=None` (measured, see below), `N_TILES=None` (one tile per
group, at least 6), model auto-picked (`vit_b_lm` on GPU, `vit_t_lm` on CPU).

**The tile size is measured, not chosen.** The script segments one field per group with the
stock model, works out the object density, and sets the tile so it holds about
`TARGET_OBJECTS_PER_TILE` (25) — clamped to [256, 1024] and to the smallest image, rounded to a
multiple of 64. It prints its reasoning (`tile_size_chosen_by` in the manifest). This matters:
512 px is right for a confluent monolayer and far too small for a sparse blood smear, where it
lands 5 objects on a tile and gives training almost nothing. Set `TILE_SIZE` to a number only to
override a measurement you disagree with.

**The picker shows what the model does today.** With a GPU (`SHOW_PRESEG="auto"`), every field
is displayed with the stock model's segmentation on it, computed in the background so the window
stays responsive. Tell the user to click **where it is wrong** — cells it missed, two cells
merged into one blob, debris it outlined — plus one or two places where it is right. A tile
where the model is already correct teaches it nothing, which is the single most common reason a
fine-tuning run comes back "did NOT help". On CPU this is off (minutes per field) and the picker
falls back to showing the plain image.

**`GROUP_REGEX` is the setting that decides whether the tile set represents the experiment.**
It splits the folder into the units the picker walks through, one field at a time:

| the data | set |
|---|---|
| `V1-neg_0002_Bottom Slide....TIF`, comparing pos vs neg | `GROUP_REGEX = r"(V\d+)[-_](pos\|neg)"` |
| wells only, no condition to balance | `GROUP_REGEX = r"(V\d+)"` |
| one sub-folder per condition or per plate | `GROUP_REGEX = None` (groups by sub-folder) |
| a flat folder with nothing to group by | `GROUP_REGEX = None`, and set `N_TILES` |

**Capture every axis the study compares, not just the replicate.** All capture groups are
joined into the group name, so `r"(V\d+)[-_](pos\|neg)"` walks V1 pos, V1 neg, V2 pos, ... A
regex that captures only the well walks wells, and a user who clicks the first field of each
one can put the entire training set on a single condition — that happened on a real pos-vs-neg
run here, and it biases the model towards the arm it saw.

Read the filenames with `inspect_folder_tree` first and derive the token; the script prints the
groups it found and how many images each has **before** the window opens, so a wrong regex is
obvious immediately. Without a regex a flat folder is one group and the picker just steps
through images — the user still chooses, but nothing guarantees every well is represented.

**Say this to the user before you run it** (`execute_script` returns nothing until the window
closes, so anything you say afterwards arrives too late):

> A napari window is opening with one image from each of your 10 wells, with the computer's
> current segmentation painted on top. Click where it gets it **wrong** — cells it missed, two
> cells merged into one blob, debris it outlined — and take one or two spots where it is right
> too. A yellow square shows exactly what you will get, and it jumps to the next well by itself
> (press "Stay on this field" if you want several squares from one image). If a whole field is
> empty or blurry, press "Show me another field". Press the green DONE button when you are done.

The picker: click = place (a drag pans instead), it auto-advances after each group, and it has
"Show me another field", "Back", "Undo last square", "⏸ Stay on this field" and DONE.
**"Stay on this field" is how you take several tiles from one image** — it switches the
auto-advance off for the rest of the session, and "Next group ▶" moves on when you are done. Then the agent converts to 8-bit,
pre-segments every tile with the stock model, and writes `manifest.json` plus a generated
`ANNOTATION_INSTRUCTIONS.md`.

`PICK_MODE = "auto"` restores the old content heuristic for unattended runs. Use it only when
there is no human in the loop, and **look at `previews/` afterwards**: the heuristic counts
blobs, and a blob is a blob whether it is a nucleus or a speck of stain precipitate.

Then **read stage 1's output before moving on**:
- `covering N/M group(s)` — a group with no tile is a well the model never sees.
- the `tile size ... px —` line, which shows the measurement. If it says the objects are
  **sparse** and names an `N_TILES` to raise to, do that: on data like a blood smear a tile
  cannot hold 25 objects without being downscaled past the point SAM can see them, so the
  answer is more tiles, not bigger ones.
- `~N objects per tile` — above ~60, re-run with a smaller `TILE_SIZE`: nobody finishes 100
  objects per tile, and a half-finished tile is worse than no tile. **Below ~5 it warns too**,
  and that one needs a judgement call: open `previews/` and decide whether the tiles really are
  that empty (re-run the picker and tell the user to click denser patches) or whether they are
  full of objects the stock model missed (thin outlines, not thin data — carry on, and warn the
  user they will be ADDING most objects rather than correcting them).
- `previews/*.png` — how good the first guess is tells you how much correcting the user faces.
  **Look at them.** A tile that is all debris or all background is worse than no tile at all.
- `tiled_inference: true` in the manifest means the source images are bigger than the tiles;
  stages 3 and 4 handle that automatically (see Pitfalls).

## Stage 2 — the user annotates

Set `TASK_DIR`. The script opens napari and **blocks until the user closes the window** — that
is intended: the script returning is how you know they finished. It prints a per-tile status
table on exit; relay that.

> **Say the instructions BEFORE you run the script.** `execute_script` returns nothing until the
> script exits, so everything it prints to stdout — including the banner — reaches you only after
> the user has already finished. Paste the block below into the chat first, then run stage 2.
> (The helper panel repeats it all on screen, which is the backstop, not the plan.)

> **Never start this workflow in an unattended run.** Stage 2 waits for a human. In a benchmark
> or auto-pilot session there is nobody to click, so the script sits at `napari.run()` until the
> 7200 s hard timeout kills it. If there is no interactive user, use the stock model.

**What to tell the user** (adapt the numbers from stage 1's output):

> A napari window is opening with 8 small squares from your images. The computer has taken a
> first guess at each one — your job is to fix it, about 2-3 minutes per square.
>
> The rule: inside the square, **every object must be outlined and nothing else may be**. Leave
> the outlines that already look right alone — you are checking its work, not redrawing it. You
> don't need to touch anything outside the squares.
>
> Use the three big buttons in the **ImagentJ — Annotation Helper** panel on the right:
> - **➕ ADD objects** — click the middle of a missed object, press **S**, then press **C**.
> - **✏ DRAW outline** — click round the object, double-click to close. No S, no C.
> - **✖ DELETE objects** — click on anything outlined that shouldn't be.
>
> To fix a bad outline: **delete it, then add it again.** If ADD keeps getting the same object
> wrong, or two objects are touching and come out as one, **draw it by hand instead** — that is
> what the DRAW button is for. That's the whole workflow.
>
> When a square looks right, press **N** (or the blue *TILE DONE* button). **Press N on the last
> square too — N is what saves your work.** You can stop any time; finished squares are kept and
> restarting picks up where you left off.
>
> Full written instructions: `<TASK_DIR>/ANNOTATION_INSTRUCTIONS.md`

**While the annotator is open you are blocked and blind.** `execute_script` does not return
until the window closes, and `capture_ui_window(target="napari")` screenshots the *napari-mcp*
viewer — a different process from the annotator this script launches, so it will not show you
what the user is looking at. There is no way to help mid-session; that is exactly why the
instructions go out first and why the helper panel repeats them on screen. If the user does get
stuck, they close the window: the script returns, you help, and re-running resumes at the first
unfinished tile.

Afterwards you are not blind: stage 2 writes an overlay of every finished tile to
`<TASK_DIR>/annotated_previews/`. Look at those (or hand them to `vlm_judge`) before spending
GPU time — if the outlines are visibly sloppier than the stock model's first guess, training on
them will make the model worse, and stage 3 will correctly refuse to promote the result.

The status table tells you what to do next: **3+ usable tiles** → stage 3. Fewer → re-run stage 2
(it resumes at the first unfinished tile, `skip_segmented=True`).

## Stage 3 — train and measure (agent)

Set `TASK_DIR`. Everything else has a sensible default; `N_EPOCHS=10` is right for 5-10 tiles.

It validates every annotation (shape, dtype, ≥2 objects ≥25 px), holds out ~25 % of the tiles —
**whole source images where possible**, so the score is not inflated by tiles cut from the same
field — trains, exports the checkpoint, then segments the held-out tiles with **both** the stock
and the fine-tuned model and prints the comparison.

**Relay the mSA numbers to the user, both of them.** mSA is the mean segmentation accuracy over
IoU thresholds 0.5-0.95; SA50 is the lenient "did it find the object at all" score. A model that
finds everything but traces boundaries loosely has high SA50 and low mSA — and that is exactly
the gap fine-tuning closes.

If the fine-tuned model **lost**, say so plainly. `recommended_checkpoint` is then `null` and
stage 4 keeps the stock model, so nothing downstream breaks. The script prints the likely causes
in order; the most common by far is that the stock model was already right for this data.

**Report a small win as "no worse", not as "better".** With 1-2 validation tiles the measurement
is noisy: a +5.9 % gain measured here on two held-out organoid tiles did not survive to 12 images
from a different split (+0.5 %). A large gain (tens of percent) does transfer. If the user is
about to run a long batch on the strength of a single-digit improvement, tell them to annotate a
few more tiles first.

## Stage 4 — apply (agent)

Set `TASK_DIR`, optionally `INPUT_DIR` to run on a bigger folder than the tiles came from.
`USE_MODEL="auto"` obeys stage 3's measurement — leave it there. Writes label TIFFs, a counts
CSV and overlay previews; the masks go straight into a `python_data_analyst` measurement step
(`regionprops_table` / `cp_measure`) exactly like a StarDist or Cellpose mask.

---

## Pitfalls (all of these were hit and fixed while building this)

1. **Scale: SAM resizes everything to 1024 px.** A model trained on 512 px tiles has learned
   objects at the size they appear *after* that resize. Hand it a whole 2048 px field and every
   object arrives 4x smaller than anything it saw in training, and the gain vanishes. Stage 4
   therefore runs **tiled inference at the annotation tile size** whenever the target images are
   larger (`is_tiled=True` + `tile_shape=(tile,tile)` + a halo). If you ever write inference by
   hand, match the tile size or the fine-tuning is wasted.
2. **16-bit input silently fails the loader check.** micro_sam's `require_8bit` only rescales
   when `max < 1`, so a uint16 array passes straight through and then trips its own
   "input has to be in range [0, 255]" check. Stage 1 writes 8-bit tiles and stage 3 passes
   `raw_transform=sam_training.identity`; keep both or neither.
3. **`is_seg_dataset=False` is required** in `default_sam_loader`. It forces torch_em's
   `ImageCollectionDataset`, the only one that copes with a folder of separate 2D images.
4. **`export_custom_sam_model(model_type=...)` wants the BACKBONE**, `"vit_b"`, not
   `"vit_b_lm"`. Pass `model_type[:5]`, and `with_segmentation_decoder=True` or the exported
   file has no AIS decoder and stage 4 cannot run automatically.
5. **Pressing C over an object that is already outlined does nothing.** micro_sam commits with
   `preserve_mode="objects"`, so a new object overlapping a committed one by >75 % is discarded
   silently. This is why the instruction is *delete first, then add* — and why the helper panel
   says so on screen.
6. **T (include/exclude) is broken in stock micro_sam 1.8.2 right after a commit.** Committing
   deletes the point prompts but napari keeps their indices in `selected_data`, so the next `T`
   raises `KeyError: None of [RangeIndex(...)] are in the [index]` inside pandas. napari
   swallows it, so the user just sees T not working. `WORKFLOW_FINETUNE_2_ANNOTATE.py` re-binds
   `t` with the stale selection cleared first (last binding wins).
7. **Only `N` saves a tile.** Closing the window loses the current tile. Say it twice; the
   helper panel says it in red. On a tile where nothing is outlined, N first opens a MODAL —
   *"Nothing is segmented yet. Do you wish to continue to the next image?"* — and until it is
   dismissed with OK, nothing else in the window responds. Tell the user it will appear;
   somebody who does not expect it reads a frozen window.
8. **A tile with <2 objects is unusable.** micro_sam's default `MinInstanceSampler(2)` rejects
   the patch, so it just burns sampling attempts. Stage 3 drops those tiles and reports them.
9. **`early_stopping=None` is deliberate** in stage 3. With 1-2 validation tiles the val curve
   is noisy and micro_sam's default (`10`) kills otherwise-good runs.
10. **tqdm floods the transcript.** A 1000-iteration run emits ~100 kB of progress bars, which
    is the entire tool-output budget. The scripts set `TQDM_MININTERVAL=30`; keep it.
11. **Annotations that are not BETTER than the pre-segmentation make the model WORSE.** Measured
    here: a run trained on annotations whose outlines had been jittered by ±1 px on half the
    objects — annotations that scored mSA 0.71 against ground truth, i.e. no better than the
    stock model's own 0.71 output — moved the model monotonically the wrong way: 0.573 stock →
    0.546 after 100 iterations → 0.420 after 1000. The AIS decoder learns distance-to-boundary
    maps, so boundary noise is the one thing it cannot average out. Re-running with annotations
    built the way stage 2 actually produces them (keep the outlines that look right, delete the
    wrong ones, add the missing ones — mSA 0.79 vs the same ground truth) trains normally.
    Practical consequence: **tell the user to ACCEPT an outline that looks right rather than
    redraw it.** "Roughly right is fine" applies to where they click, not to replacing a correct
    outline with a slightly different one.
12. **torch_em's "best" epoch is chosen by validation LOSS, and with 1-2 validation tiles that is
    5 randomly cropped, randomly augmented patches per epoch — noise.** In the run above the loss
    named epoch 0 the best epoch while the actual segmentation quality said neither checkpoint was
    worth keeping. Stage 3 therefore scores `best.pt` and `latest.pt` (and any `epoch-*.pt` kept
    via `SAVE_EVERY_KTH_EPOCH`) by real mSA on the held-out tiles and keeps the winner. Never
    export `best.pt` blindly.
13. **Do not fine-tune from a fine-tuned checkpoint by accident.** Stage 3 always starts from
    the stock `model_type` in the manifest. To iterate — more tiles on top of an existing model
    — pass `checkpoint_path=<exported .pt>` to `train_sam`, and re-measure against the model you
    started from, not against stock.
14. **An automatic content score cannot tell a cell from debris — this is why the user picks.**
    Measured on a real May-Grünwald neutrophil slide: the tile the blob-count heuristic ranked
    *highest* (score 132, 78 pre-segmentation objects) was a field of stain precipitate with
    **zero cells** in it; another was out-of-focus haze with one object. Of ten auto-picked
    tiles, two were actively poisonous and only two were good. Nothing about a 2 um speck and a
    12 um nucleus separates them at the level of "how many connected components are in this
    square" — and pre-segmentation object count does not save you either, because the stock
    model segments the specks too. `PICK_MODE="interactive"` exists for this. If you ever run
    `"auto"`, look at `previews/`.
15. **Otsu picks the wrong side of the histogram on brightfield.** `sm > thr` means "objects are
    bright", which is true for fluorescence and false for every brightfield / histology stain,
    where it scores the *background*. `foreground_mask()` takes whichever side covers less of
    the frame, since objects are the minority class in both modalities. Only affects `"auto"`.
16. **Microscope exports are `.TIF`, and `glob("*.tif")` does not match them.** On a
    case-sensitive filesystem the run dies with "No images matching (...)" pointing at a folder
    that is visibly full of images. Stages 1 and 4 match extensions case-insensitively; keep it
    that way if you write your own loop.
17. **The micro_sam model cache can be unwritable, and the traceback blames pooch.** In a
    container whose `/home` is a named volume older than the image, `~/.cache/micro_sam`
    survives as an empty root-owned directory: `MICROSAM_CACHEDIR` points at it, and every
    model load dies with `PermissionError: .../micro_sam/models`. All four stages call
    `ensure_model_cache()` first, which probes the directory for real and falls back to
    `<TASK_DIR>/.micro_sam_cache`. `docker-entrypoint.sh` does the same at container start.
18. **An interactive stage must keep talking, or the watchdog kills it.** The run watchdog
    ends a script that prints nothing for 180 s, and stages 1 and 2 are silent by nature while
    a person works: a real picker session was killed at 52 minutes — *"PICK_MODE=interactive
    has the script blocked in a napari GUI event loop ... 52.5 min with zero interaction ...
    means that input will never arrive"* — and every tile the user had placed was lost. Both
    stages now print a heartbeat every 45 s saying how far the human has got and that the wait
    is intended. If you write your own interactive script, do the same, and `flush=True`:
    stdout is block-buffered to a pipe, so unflushed prints do not count as output.
19. **All the tiles must come from images of the SAME size.** A fixed tile size cut from a
    512 px field and from a 2048 px field shows the same object 4x apart, and SAM resizes both
    to 1024 regardless — so the training set contains the same structure at four magnifications
    and the model learns none of them. Measured on OrgaSegment, which mixes 512/1024/2048 px
    fields: 8 tiles spanning all three made the model WORSE **even with the dataset's own
    labels as the annotations** (mSA 0.556 -> 0.515). Stage 1 warns loudly when the sources it
    cut from are 2x or more apart (`source_size_spread` in the manifest); point `INPUT_DIR` at
    one size class before anyone annotates. This is the same scale argument as pitfall 1, one
    level up: pitfall 1 is train-vs-inference, this is tile-vs-tile.
20. **You cannot split a tight cluster with the one-click workflow — do not plan a run
    around it.** Measured on packed brightfield organoids: a single positive click inside a
    lobe returns the WHOLE clump (10 011 / 15 199 / 10 507 px against lobes of 1 000-1 900 px,
    IoU 0.09-0.17 with the true lobe), and once that clump is committed every further click
    inside it is silently discarded by the >75 % overlap rule (pitfall 5) — so the user clicks
    seven times and gets one object. Adding negative points over-corrects instead: four of
    them collapsed the mask to 4-362 px (IoU 0.00-0.26). What this workflow reliably teaches
    is *find the objects you missed*, *stop outlining debris*, and *follow this boundary*, on
    objects that are separable to begin with. If the correction the user needs IS "split these
    touching objects", the fix is the **✏ DRAW outline** button, not more clicking: it writes a
    hand-drawn polygon straight into `committed_objects`, so SAM never sees the prompt and the
    >75 % overlap rule never applies. Say so before they annotate, and budget for it — drawing
    a clump by hand is perhaps 20-30 s per object against 2-3 s for a click that works, so a
    tile that is mostly clumps is a slow tile, not an impossible one.
21. **A folder that mixes grayscale and RGB files silently breaks the annotator.** The series
    annotator shows every tile in ONE napari image layer, so the first `(512,512,3)` tile after
    a `(512,512)` one is read as a 512-SLICE STACK: the canvas goes black, the committed masks
    float on nothing, and a dimension slider appears at the bottom. No error is raised. Stage 1
    now writes one colour mode for the whole task (`tile_mode` in the manifest) — RGB if any
    source has colour. Check that field if an annotator session ever looks like this.
22. **A napari window launched from `python_data_analyst` can die on a Qt plugin mismatch.**
    Importing cv2 in the agent's own env sets `QT_QPA_PLATFORM_PLUGIN_PATH` to *its* bundled Qt
    plugins, children inherit it, and the `napari-mcp` interpreter (a different Python and Qt
    build) then aborts with *Could not load the Qt platform plugin "xcb" ... even though it was
    found*. `analyst_tools._child_env()` strips that variable for non-main envs. If you see that
    message from a script you launched yourself, the env is what to look at, not napari.

---

## Verified end-to-end, 2026-09-01

`agenticj:gpu-local-napari`, micro_sam 1.8.2, napari 0.6.6, one A100 per run. In every run the
human was simulated the way stage 2 actually works — start from the pre-segmentation, keep the
outlines that are right, delete the wrong ones, add the missed ones — never by perturbing ground
truth (see pitfall 11). 8 tiles of 512 px out of 10 images of 1024 px = **20 % of the pixel area**;
training was 10 epochs x 100 patches, ~13-28 min.

**Held-out tiles** (from source images the training never saw), stock vs fine-tuned mSA:

| data | in micro_sam's LM training set? | stock | fine-tuned | outcome |
|---|---|---|---|---|
| OrgaSegment organoids, brightfield | no | 0.642 | **0.680** (+5.9 %) | promoted |
| the same bacteria in a false-colour RGB mapping | no (the mapping is not) | 0.308 | **0.345** (+12.1 %) | promoted |
| DeepBacs bacteria, 1024 px | **yes** | **0.875** | 0.830 (-4.5 %) | **refused — stock kept** |
| Nucleus DSB, 256 px | **yes** | **0.749** | 0.728 (-2.1 %) | **refused — stock kept** |

The pattern is the point: it improved the model on both datasets outside micro_sam's own training
set and refused on both datasets inside it — the safety net discriminating on exactly the axis
pitfall 4 describes. In the refused runs `recommended_checkpoint` came back `null` and stage 4 ran
the stock weights, so nothing downstream was affected.

**Fully unseen images** (12 x 1024 px from the dataset's own test split, tiled at 512):

| data | stock | fine-tuned | delta |
|---|---|---|---|
| false-colour RGB bacteria | 0.271 | **0.372** | **+37.6 %** |
| OrgaSegment organoids | 0.509 | 0.512 | +0.5 % — no real gain |

Both directions are worth taking seriously. Where the stock model was genuinely wrong for the data
the gain is large and it transfers. Where it was only slightly off, a +5.9 % gain on two held-out
tiles did **not** survive to a different split — two tiles is a small sample, so read a single-digit
improvement as "no worse", not as "better", and say so to the user.

**Tiling at the training tile size is worth as much as the fine-tuning** (pitfall 1), measured on
the same 12 unseen images with the *stock* model: RGB bacteria mSA 0.189 whole-frame vs **0.271**
tiled; organoids 0.466 vs **0.509**. Stage 4 does this automatically.

**The shipped code was then run once more end to end** on the organoid tiles with
`SAVE_EVERY_KTH_EPOCH=3`, which is what the checkpoint scoring is for. Five candidates were
measured on the held-out tiles — stock 0.642, `best` **0.674**, `latest` 0.615, `epoch-3` 0.650,
`epoch-6` 0.641 — so `latest`, the checkpoint a naive run would have exported, was **worse than
the stock model**, and `best` was kept. 5.0 GB of raw torch_em checkpoints were then removed and
stage 4 segmented the folder with the exported file at 1.8 s per 1024 px image.

**The annotator UI** is covered by 25 assertions against a live napari session — layers, both
helper buttons, S / T / C / D / N, the delete-then-re-add repair flow, fill-with-0 deletion, the
saved TIFF's shape and content, and the mode reset after N — passing on 512 px RGB and 256 px
grayscale tiles. `tests/manual/microsam_finetune_ui_check.py` re-runs it.
Stage 3's guard rails have 15 more (missing / mismatched / empty / single-object / float-labelled
annotations, and the train-val split never sharing a source image), and
`tests/test_microsam_finetune_workflow.py` holds 25 pytest cases that need no GPU.


## Files

| file | what it is |
|---|---|
| `WORKFLOW_FINETUNE_1_PREPARE.py` | tiles + pre-segmentation + `manifest.json` + generated human instructions |
| `WORKFLOW_FINETUNE_2_ANNOTATE.py` | the annotator with the ADD/DELETE helper panel; blocks until the user is done, then reports |
| `WORKFLOW_FINETUNE_3_TRAIN.py` | validate → split → train → export → **stock vs fine-tuned on held-out tiles** → `evaluation.json` |
| `WORKFLOW_FINETUNE_4_APPLY.py` | segment the folder with whichever model won, tiled at the training scale |
| `SKILL.md` | the rest of micro_sam: automatic segmentation, the interactive annotator, the object classifier |
| `UI_GUIDE.md` | the stock annotator UI in full, for anything the helper panel does not cover |
| `SCRIPT_API.md` | verified signatures for every micro_sam entry point used here |

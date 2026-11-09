# Fine-tuning Cellpose on the user's own annotations

The playbook for "teach the model what I mean" — the user corrects a handful of small image
tiles, Cellpose (version 3, starting from `cyto3` by default) trains on them, and the result is
measured before anything else uses it.

Four scripts, run in order, all via **`python_data_analyst`**. Never via
`mcp__napari_mcp__execute_code`: that runs on napari's Qt thread under a 90 s timeout.

| | script | env | who does the work | how long |
|---|---|---|---|---|
| 1 | `WORKFLOW_FINETUNE_CP_1_PREPARE.py` | `napari-mcp` | **the user picks the tiles** in napari; then the agent | 2-3 min + 1-3 min |
| 2 | `WORKFLOW_FINETUNE_CP_2_ANNOTATE.py` | `napari-mcp` | **the user draws** in napari | 2-4 min per tile |
| 3 | `WORKFLOW_FINETUNE_CP_3_TRAIN.py` | `cellpose` | agent (GPU strongly preferred) | 5-20 min on a GPU |
| 4 | `WORKFLOW_FINETUNE_CP_4_APPLY.py` | `cellpose` | agent | ~1 s per image on GPU |

`WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py` is not a stage — it is the subprocess stage 1 uses to
reach Cellpose from the napari env (napari and cellpose live in different envs; the worker stays
resident so the model is loaded once, not once per field).

Each script has a CONFIG block at the top; `copy_file` the template, edit CONFIG, run. They talk
to each other through `<TASK_DIR>/manifest.json` and `<TASK_DIR>/evaluation.json`, so after
stage 1 the only thing to set is `TASK_DIR`.

> **What this image has.** Cellpose 3.1.1.2 only, with `cyto3` pre-installed. The other
> Cellpose 3 zoo models (`nuclei`, `cyto2`, `livecell_cp3`, `tissuenet_cp3`, …) download on
> first use and need network access. Cellpose 4 / Cellpose-SAM (`cpsam`) and micro_sam are NOT
> installed — the scripts refuse `cpsam` with a clear message.

---

## The idea: the user never annotates a whole image

Cellpose trains on **densely** annotated crops: every object inside an annotated field must be
labelled, because anything left unlabelled teaches the network "background". Annotating every
cell in a full field is hours of work. So stage 1 cuts small square tiles (sized so each holds
~25 objects) and the user annotates those completely. A tile is dense by construction, and 8
tiles is ~20 minutes instead of a day. The user annotates every object in a few small squares,
never every object in an image. That is the whole design.

Stage 1 also pre-segments each tile with the stock model and loads that into the annotator, so
the user is **correcting a first guess, not drawing from scratch** — usually a handful of fixes
per tile.

---

## Before you start — is fine-tuning even needed?

Fine-tuning costs the user 20 minutes of their attention. Spend it only when it buys something.

1. **Try the stock model first.** Run `WORKFLOW_BATCH_SEGMENTATION.py` on a few images (or
   stage 1, which pre-segments as a side effect) and look at the overlays with `vlm_judge` or
   show them to the user. If stock `cyto3` (at the right diameter — see `SKILL.md`) is already
   right, say so and stop.
2. **Check the hardware.** `check_environment("cuda")`. On CPU, stage 3 takes far longer and
   the stage-1 picker cannot show the model's segmentation live. Tell the user the cost before
   they annotate — not after.
3. **Check there is enough data.** Fewer than ~4 usable tiles and stage 3 refuses; 6-10 is the
   reliable range.
4. **Rule out the cheap fixes.** A wrong `diameter`, the wrong `channels`, or a bright-field
   image fed without inversion all look like "the model is bad" and are fixed in seconds. Only
   when the stock model is wrong at the right settings is fine-tuning the answer.
5. **Fine-tuning teaches SHAPE and APPEARANCE, not categories.** "Only count the infected
   cells" is a classification job (measure, then classify — `skills/python/scikit_learn`).
   Fine-tuning is for "it keeps missing my cells / splitting them / outlining debris".

---

## Stage 1 — the user picks the tiles, then the agent prepares them

Set `INPUT_DIR`, `TASK_DIR`, **`GROUP_REGEX`**, `CP_MODEL` (default `"cyto3"`), and for 3D
input `CHANNEL`. Defaults: `PICK_MODE="interactive"`, `TILE_SIZE=None` (measured, see below),
`N_TILES=None` (one tile per group, at least 6).

**`CP_MODEL` is set here, once.** Stage 1 segments the picker's fields and the tiles with it, so
the user corrects THAT model's mistakes, and records it in the manifest; stage 3's `CP_MODEL`
defaults to `"auto"`, which reads it back. That keeps "the model the user corrected" and "the
model we train" the same object.

**The tile size is measured, not chosen.** The script segments one field per group with the
stock model, works out the object density, and sets the tile so it holds about
`TARGET_OBJECTS_PER_TILE` (25) — clamped to [256, 1024] and to the smallest image, rounded to a
multiple of 64. It prints its reasoning (`tile_size_chosen_by` in the manifest).

**The picker shows what the model does today.** With a GPU (`SHOW_PRESEG="auto"`), every field
is displayed with the current segmentation on it. Tell the user to click **where it is wrong** —
cells it missed, two cells merged into one blob, debris it outlined — plus one or two places
where it is right. A tile where the model is already correct teaches it nothing, which is the
most common reason a fine-tuning run comes back "did NOT help". On CPU this is off and the
picker shows the plain image.

**`GROUP_REGEX` decides whether the tile set represents the experiment.** It splits the folder
into the units the picker walks through, one field at a time:

| the data | set |
|---|---|
| `V1-neg_0002_Bottom Slide....TIF`, comparing pos vs neg | `GROUP_REGEX = r"(V\d+)[-_](pos\|neg)"` |
| wells only, no condition to balance | `GROUP_REGEX = r"(V\d+)"` |
| one sub-folder per condition or per plate | `GROUP_REGEX = None` (groups by sub-folder) |
| a flat folder with nothing to group by | `GROUP_REGEX = None`, and set `N_TILES` |

**Capture every axis the study compares, not just the replicate** — a regex that captures only
the well can put the entire training set on one condition. Read the filenames with
`inspect_folder_tree` first; the script prints the groups it found **before** the window opens.

**Say this to the user before you run it** (`execute_script` returns nothing until the window
closes, so anything you say afterwards arrives too late):

> A napari window is opening with one image from each of your 10 wells, with the computer's
> current segmentation painted on top. Click where it gets it **wrong** — cells it missed, two
> cells merged into one blob, debris it outlined — and take one or two spots where it is right
> too. A yellow square shows exactly what you will get, and it jumps to the next well by itself
> (press "Stay on this field" if you want several squares from one image). If a whole field is
> empty or blurry, press "Show me another field". Press the green DONE button when you are done.

`PICK_MODE = "auto"` is for unattended runs only; **look at `previews/` afterwards** — the
heuristic counts blobs, and a blob is a blob whether it is a nucleus or stain precipitate.

Then **read stage 1's output before moving on**:
- `covering N/M group(s)` — a group with no tile is a condition the model never sees.
- the `tile size ... px —` line. If it says the objects are **sparse** and names an `N_TILES`
  to raise to, do that.
- `~N objects per tile` — above ~60, re-run with a smaller `TILE_SIZE`: nobody finishes 100
  objects per tile. Below ~5 it warns too; open `previews/` and decide whether the tiles really
  are that empty (re-pick denser patches) or full of objects the model missed (carry on, and
  warn the user they will mostly be DRAWING new objects).
- `previews/*.png` — **look at them.** A tile that is all debris or background is worse than
  no tile at all.

## Stage 2 — the user annotates (by drawing)

Set `TASK_DIR`. The script opens napari and runs until the user closes the window; it prints a
per-tile status table on exit — relay that.

Every object is **drawn by hand**: what the user traces is exactly the outline that is saved
(no model assists the annotation). The panel has two modes and three actions:

- **✏ DRAW objects** — press, drag round the object, release (napari's freehand lasso). Draw
  several, then **S** (shows them as outlines) and **C** (keeps them). C alone also works.
  Pressing DRAW again switches to click-by-click polygon (double-click closes it).
- **✖ DELETE objects** — click an outline to remove it (or hover and press **D**).
- **⌫ CLEAR my drawings** — removes traced shapes not yet kept; kept outlines are untouched.
- **◀ BACK** (**B**) / **✓ TILE DONE → NEXT TILE** (**N**).

A new outline never paints over an existing object — it fills only background — so redrawing a
bad outline is **DELETE, then DRAW**. An empty tile is saved only on a second **N** (a real
debris-only field is a useful negative example; a forgotten tile is not).

> **You are DETACHED for this stage, immediately.** `execute_script` returns
> `SUMMARY: WAITING FOR THE USER (detached)` the moment the window opens, and the status table
> arrives later as a `[DETACHED RUN FINISHED]` message. That first receipt means **nothing has
> been annotated yet**. Until the finished message arrives: do not start stage 3, do not re-run
> stage 2, do not read the annotation files, and do not say how many tiles are done. Expect
> questions while they work — *"is a rough outline good enough?"*, *"can I skip this tile?"* —
> and answer them from this playbook and `ANNOTATION_INSTRUCTIONS.md`.

> **Say the instructions BEFORE you run the script.** Detaching changes when the RECEIPT
> arrives, not when the OUTPUT does: the script's own banner reaches you only after the work is
> done. Paste the block below first, then run stage 2.

> **Never start this workflow in an unattended run.** Stage 2 waits for a human; with nobody
> there it sits until the 7200 s hard timeout. Use the stock model instead.

**What to tell the user** (adapt the numbers from stage 1's output):

> A napari window is opening with 8 small squares from your images. The computer has taken a
> first guess at each one — your job is to fix it, about 2-3 minutes per square.
>
> The rule: inside the square, **every object must be outlined and nothing else may be**. Leave
> the outlines that already look right alone — you are checking its work, not redrawing it.
>
> Use the buttons in the **ImagentJ — Annotation Helper** panel on the right:
> - **✏ DRAW objects** — press, drag round a missing object, release. Draw as many as you like,
>   then press **S** to see them as outlines and **C** to keep them. What you draw is exactly
>   what gets saved, so follow the edge — roughly is fine. (Press DRAW again to click a polygon
>   point by point instead.)
> - **✖ DELETE objects** — click on anything outlined that shouldn't be (or hover + **D**).
> - To fix a bad outline: **delete it, then draw it again** — a new outline never paints over
>   an existing one.
>
> When a square looks right, press **N** (or the blue *TILE DONE* button). **Press N on the last
> square too — N is what saves your work.** You can stop any time; finished squares are kept and
> restarting picks up where you left off. **B** goes back one square with your corrections on it.
>
> Full written instructions: `<TASK_DIR>/ANNOTATION_INSTRUCTIONS.md`

**While the annotator is open you cannot see it.** `capture_ui_window(target="napari")`
screenshots the *napari-mcp* viewer — a different process from this annotator. If the user gets
stuck, they close the window: the script returns, you help, and re-running resumes at the first
unfinished tile.

Afterwards stage 2 writes an overlay of every finished tile to `<TASK_DIR>/annotated_previews/`.
Look at those (or hand them to `vlm_judge`) before spending GPU time — outlines visibly sloppier
than the stock first guess will make the model worse (pitfall 4).

**3+ usable tiles** → stage 3. Fewer → re-run stage 2.

## Stage 3 — train and measure (agent)

Set `TASK_DIR`. Everything else has a sensible default.

> **This stage is DETACHED** (`# imagentj-detach:` on line 2). `execute_script` returns
> `SUMMARY: STILL RUNNING (detached)` within seconds, and the training output arrives later as
> a separate `[DETACHED RUN FINISHED]` message. That receipt is NOT a failure and NOT an empty
> result: do not re-run the stage, do not poll, and do not report a score you have not seen.
> Tell the user training is running and roughly how long it takes, then keep talking to them.

It validates every annotation, holds out ~25 % of the tiles — **whole source images**, so the
score is not inflated by tiles cut from the same field — trains with `cellpose.train.train_seg`,
then segments the held-out tiles with **both** the baseline and the fine-tuned model and prints
the comparison into `evaluation.json`.

**Relay the mSA numbers to the user, both of them.** mSA is the mean segmentation accuracy over
IoU thresholds 0.5-0.95; SA50 is the lenient "did it find the object at all" score.

If the fine-tuned model **lost**, say so plainly. `recommended_checkpoint` is then `null` and
stage 4 keeps the baseline, so nothing downstream breaks. **Report a small win as "no worse",
not as "better"** — with 1-2 validation tiles the measurement is noisy; a large gain transfers.

**The Cellpose 3 recipe** (leave the `None` defaults unless you have a reason):

- **Hyperparameters:** `lr=5e-4`, `weight_decay=1e-5`, `bsize=224`, `batch_size=8`,
  300 epochs. That is **not** Cellpose's library default of `0.005` — that is a from-scratch
  rate, and fine-tuning a model that is already good on the data with it destroys the network.
  Measured on fluorescence nuclei where stock `nuclei` scored 0.717: **lr 0.005 → 0.000**,
  lr 5e-4 → 0.948, lr 1e-4 → 0.942.
- **`CHANNELS`:** `[cytoplasm, nucleus]` (0 = grayscale, 1/2/3 = R/G/B). `[0, 0]` is right for
  brightfield and for a single fluorescence channel.
- **`DIAMETER`:** Cellpose 3 rescales every image by `diameter / diam_mean`, which makes it the
  single biggest accuracy lever. Stage 3 **measures** it from the user's annotations and uses
  the SAME value for both models in the comparison. After training the learned scale is
  recorded and stage 4 pairs it with the fine-tuned model — applying a good fine-tuned model at
  the wrong diameter reads as "fine-tuning failed".

## Stage 4 — apply (agent)

Set `TASK_DIR`, optionally `INPUT_DIR` to run on a bigger folder than the tiles came from.
`USE_MODEL="auto"` obeys stage 3's measurement — leave it there. Writes label TIFFs, a counts
CSV and overlay previews; the masks go straight into a `python_data_analyst` measurement step
(`regionprops_table` / `cp_measure`).

---

## Which Cellpose model to start from

Any Cellpose 3 model: `cyto3` (built in, the generalist), `nuclei`, `cyto2`, `livecell_cp3`,
`tissuenet_cp3`, `deepbacs_cp3`, `bact_phase_cp3`, `yeast_BF_cp3`, … (downloaded on first use).

**Pick by CONTRAST MECHANISM, not by name.** `nuclei` sounds right for any nucleus task, but it
learned *fluorescent* nuclei — bright objects on a dark ground — so on a stained brightfield
slide it can return nothing while the generalist still finds the objects. **Read the target,
too:** nuclei and whole cells on the same images are two different problems, and a number
measured for one says nothing about the other. **So measure, do not guess:** run two or three
candidates stock on a handful of tiles, look at the overlays, and let those numbers decide.
"Which is best stock" and "which fine-tunes best" are different questions — let stage 3's
held-out measurement have the last word.

## Pitfalls

1. **Only `N` saves a tile.** Closing the window loses the current tile. Say it twice; the panel
   says it in red.
2. **A tile the user annotated is the user's work — do not silently drop it.** Cellpose's
   `train_seg` defaults `min_train_masks=5` and silently removes anything below it. Stage 3
   uses `MIN_TRAIN_MASKS=0`: sparse tiles (1-4 objects) are real annotations, and **empty**
   tiles (the user pressed N twice on a debris-only field) are deliberate NEGATIVE examples —
   "none of this is a cell". If empty tiles come to dominate, the model learns to predict
   nothing; stage 3 warns above 40 %. **mSA is not comparable across different
   `MIN_TRAIN_MASKS` settings** — the held-out set changes with it.
3. **Fine-tuning can make a good model WORSE, and the wrong learning rate is the usual
   reason.** The gate catches it — stage 3 refuses to promote a model that scores below the
   baseline — but the user is then told "fine-tuning did not help", which reads as "your labels
   were no good". If a round collapses to near-zero from a decent base, suspect the learning
   rate before the annotations.
4. **Annotations that are not BETTER than the first guess make the model WORSE.** Boundary
   noise is the one thing training cannot average out. **Tell the user to ACCEPT an outline
   that looks right rather than redraw it**; "roughly right is fine" applies to new outlines,
   not to replacing a correct one with a slightly different one.
5. **Tight clumps.** Drawing is the only way to split touching objects here: trace one object at
   a time along the boundary. If a clump is too dense to tell where one object ends, leave it
   out and say so — a guess there is worse for training than nothing.
6. **An automatic content score cannot tell a cell from debris — this is why the user picks.**
   On a stained brightfield slide the tile a blob-count heuristic ranked highest was stain
   precipitate with zero cells in it. `PICK_MODE="interactive"` exists for this.
7. **All the tiles must come from images of the SAME size.** A fixed tile size cut from a
   512 px and a 2048 px field shows the same object 4x apart; fine-tuning on that mixture made a
   model worse even with perfect labels. Stage 1 warns when sources are 2x+ apart
   (`source_size_spread` in the manifest) — point `INPUT_DIR` at one size class first.
8. **A folder that mixes grayscale and RGB files.** Stage 1 writes one colour mode for the whole
   task (`tile_mode` in the manifest) — RGB if any source has colour — because one napari image
   layer cannot switch between them mid-series.
9. **Microscope exports are `.TIF`, and `glob("*.tif")` does not match them.** Stages 1 and 4
   match extensions case-insensitively; keep it that way in your own loops.
10. **An interactive stage must keep talking, or the watchdog kills it.** The run watchdog ends
    a script that prints nothing for 180 s, and stages 1 and 2 are silent while a person works
    (a real picker session was killed at 52 minutes). Both print a heartbeat every 45 s with
    `flush=True`; do the same in any interactive script you write.
11. **tqdm floods the agent's context.** All CP scripts set `TQDM_DISABLE=1` before importing
    cellpose. Do not remove it.
12. **Split by SOURCE IMAGE, never by tile.** Two tiles from one field share illumination,
    focus and cells; a tile-level split scores the model on what it has effectively seen.
13. **A second round must be measured against the first, not against stock.** Stage 1 records
    `base_checkpoint` (the previous round's promoted model, found via `evaluation.json`); stage 3
    continues from it AND makes it the baseline. When a round loses, stage 4 keeps the previous
    round's model.
14. **Stage 4 refuses to run without `evaluation.json`.** "We fine-tuned it" is not the same
    claim as "it got better". `USE_MODEL="finetuned"` can force a checkpoint that lost, and the
    script then says so — report that, do not quietly pass it.
15. **Every commit is logged to `<TASK_DIR>/prompt_log/<tile>.json`** — the traced shapes
    (`type`, `vertices_yx`) and the `label_ids` each C created. It is a history, not the
    annotation: objects deleted later still appear in it; the label tif in `annotations/` is
    what stage 3 trains on.
16. **A napari window launched from `python_data_analyst` can die on a Qt plugin mismatch**
    (*Could not load the Qt platform plugin "xcb" ... even though it was found*).
    `analyst_tools._child_env()` strips the inherited Qt plugin path for non-main envs; if you
    see that message from a script you launched yourself, look at the env, not napari.

## Files

| file | what |
|---|---|
| `WORKFLOW_FINETUNE_CP_1_PREPARE.py` | stage 1: tile picker (napari) + pre-segmentation + manifest + instructions |
| `WORKFLOW_FINETUNE_CP_2_ANNOTATE.py` | stage 2: the drawing annotator (fixed UI — edit `TASK_DIR` only) |
| `WORKFLOW_FINETUNE_CP_3_TRAIN.py` | stage 3: validate, train, measure, write `evaluation.json` (detached) |
| `WORKFLOW_FINETUNE_CP_4_APPLY.py` | stage 4: segment a folder with whichever model won |
| `WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py` | Cellpose subprocess used by stage 1 |

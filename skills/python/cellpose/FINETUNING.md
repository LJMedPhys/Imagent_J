# Fine-tuning Cellpose (cpsam) on the user's own annotations

The Cellpose half of the fine-tuning workflow. **Stages 1 and 2 are SHARED with micro_sam** —
the same tile picker, the same SAM-assisted annotator — because tiles and label masks do not
care which model consumes them, and clicking an object with SAM is far faster than painting it.
Only training and inference are Cellpose-specific.

| stage | script | env | shared? |
|---|---|---|---|
| 1 — the user picks tiles | `napari/micro_sam/WORKFLOW_FINETUNE_1_PREPARE.py` with `SEGMENT_BACKEND="cellpose"` + `CP_MODEL` | `napari-mcp` | shared |
| 2 — the user annotates | `napari/micro_sam/WORKFLOW_FINETUNE_2_ANNOTATE.py` | `napari-mcp` | shared, unchanged |
| 3 — train + measure | `WORKFLOW_FINETUNE_CP_3_TRAIN.py` | `cellpose4` | Cellpose |
| 4 — apply | `WORKFLOW_FINETUNE_CP_4_APPLY.py` | `cellpose4` | Cellpose |

`WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py` is not a stage — it is the subprocess stage 1 uses to
reach Cellpose from the napari env.

## Why the split, and why a subprocess

The two envs are disjoint and cannot be merged: `napari-mcp` has napari, micro_sam, skimage and
elf but **no cellpose**; `cellpose4` has cellpose and torch but **no napari, no skimage, no elf,
no imageio**. The picker must run where napari is, and it should show the user what **Cellpose**
currently gets wrong — so `SEGMENT_BACKEND="cellpose"` starts the worker in the other env and
talks to it over TIFFs on disk.

The worker stays **resident** (`--serve`, one job per stdin line). cpsam takes ~10 s to load and
the picker segments a new field every time the user asks for one; a process per field would make
it unusable.

That same split is why stage 3 computes mSA in numpy/scipy instead of importing `elf`. It is
implemented to elf's definition and **verified identical to elf to 1e-16 across 14 cases**,
including real annotations, gapped label ids and an id near the uint16 maximum — so a Cellpose
run and a micro_sam run on the same tiles are directly comparable.

## Which Cellpose model — ANY of them, and the script finds the right env

**Set `CP_MODEL` in stage 1, not stage 3.** Stage 1 segments the picker's fields with it, so
the user corrects THAT model's mistakes, and records it in the manifest; stage 3's `CP_MODEL`
defaults to `"auto"`, which reads it back. That is what keeps "the model the user corrected"
and "the model we train" the same object — they were two independent settings until a test run
set `CP_MODEL="nuclei"` for stage 1, where nothing read it, and the picker went on showing
cpsam while stage 3 would have trained `nuclei`.

`CP_MODEL` takes any model in either version:

| CP_MODEL | cellpose | env | notes |
|---|---|---|---|
| `cpsam` (default) | 4.1.1 | `cellpose4` | the SAM-backboned generalist; **the only model v4 ships** |
| `nuclei` | 3.1.1.2 | `cellpose` | `diam_mean` 17 px |
| `cyto3`, `cyto2`, `cyto` | 3.1.1.2 | `cellpose` | `diam_mean` 30 px |
| `livecell_cp3`, `tissuenet_cp3`, `deepbacs_cp3`, `bact_phase_cp3`, `yeast_BF_cp3`, … | 3.1.1.2 | `cellpose` | 26 zoo models in total |

`cellpose 4.1.1`'s `MODEL_NAMES` is literally `['cpsam']` — the v3 zoo is not there. So "train
`nuclei` instead" is not a config change, it is a **different interpreter, network and set of
hyperparameters**. The scripts handle that themselves: `ensure_right_env()` re-execs into the
other env when the requested model lives there, printing what it is doing. Stage 4 reads the
version out of `evaluation.json`, so it follows whatever stage 3 trained without being told.

**Pick the starting model by CONTRAST MECHANISM, not by name.** `nuclei` sounds right for any
nucleus task; whether it is depends on what it was trained on. It learned *fluorescent* nuclei —
bright objects on a dark ground — so on a stained brightfield slide, where the contrast is
inverted, it can return nothing at all while a generalist trained across modalities still finds
the objects. The name is not evidence.

**Read the target, not just the modality.** The same images asked for the NUCLEI and asked for
whole CELLS are two different problems with two different answers, and a model that wins one can
score zero on the other. A number measured for one target says nothing about the other — quoting
one as if it covered both is a mistake a real run made.

**So measure, do not guess.** Run the two or three candidates STOCK on a handful of your own
tiles, look at the overlays, and let YOUR numbers decide; it costs minutes. Stage 3 measures
again on held-out tiles afterwards, so a wrong guess is caught rather than shipped. A model that
starts from nothing can still end up the best base — see below — which is exactly why the
starting ranking is not the decision.

**Three things differ on v3 and they all matter:**

- **Hyperparameters.** v3: `lr=5e-4`, `weight_decay=1e-5`, `bsize=224`, `batch_size=8`.
  Note that is **not** cellpose v3's own default of `0.005` — that is a from-scratch rate, and
  fine-tuning a v3 model that is already good on the data with it destroys the network.
  Measured on fluorescence nuclei where stock `nuclei` scored 0.717: **lr 0.005 → 0.000**,
  lr 5e-4 → 0.948, lr 1e-4 → 0.942.
  v4: `lr=1e-5`, `weight_decay=0.1`, `bsize=256`, `batch_size=1`. v3's learning rate is **500x**
  v4's — copying a v3 recipe onto cpsam destroys it, and the reverse barely trains. Leave the
  `None` defaults alone unless you have a reason.
- **`CHANNELS`.** v3 needs `[cytoplasm, nucleus]` (0 = grayscale, 1/2/3 = R/G/B). `[0, 0]` is
  right for brightfield and for a single fluorescence channel. cpsam ignores it.
- **`DIAMETER`.** v3 rescales every image by `diameter / diam_mean` before the network sees it,
  which makes diameter the single biggest accuracy lever on a v3 model. Stage 3 **measures** it
  from the user's annotations and uses the SAME value for both models in the comparison — give
  them different diameters and the experiment measures the diameter, not the fine-tuning. After
  training, v3 writes the learned scale into `net.diam_labels`; stage 3 records it and stage 4
  pairs it with the fine-tuned model (and the measured diameter with the stock one). Applying a
  good fine-tuned v3 model at the wrong diameter reads as "fine-tuning failed".

## Choosing between micro_sam and Cellpose

Fine-tune whichever model is **already closest** on this data, and set `SEGMENT_BACKEND` to
match so the user corrects that model's mistakes. Run both stock first and look at the overlays;
it costs minutes and decides the rest of the workflow.

**"Which is better stock" and "which fine-tunes better" are different questions**, and they have
been measured disagreeing: the model that best rejected debris out of the box was not the model
that gained most from fine-tuning. A backbone that can MOVE beats one that is already close, so
judge the starting ranking as a hint and let stage 3's held-out measurement decide. "Which
target" is a third question again — see above.

## Pitfalls

1. **A tile the user annotated is the user's work — do not silently drop it.** cellpose's
   `train_seg` defaults `min_train_masks=5` and prints *"removing from train set"* for anything
   below it; micro_sam's sampler needs >= 2. On a real annotation set that can be a large
   fraction of the tiles the user spent their evening on. Two cases hide behind one number and
   they are not the same:
   - **Sparse** (1–4 objects): real annotations. `MIN_TRAIN_MASKS=0` keeps them. Tested with a
     FIXED validation set, varying only the training set, keeping them was better on some
     held-out tiles and worse on others — **no reliable difference** either way. Keeping them is
     therefore not an accuracy argument, it is a "do not throw away what the user did" argument,
     and it costs nothing measurable.
   - **Empty** (0 objects): the file EXISTS, so the user opened the tile and confirmed
     micro_sam's *"Nothing is segmented yet"* dialog. On a field of pure debris that is the
     correct answer and a deliberate NEGATIVE example — "none of this is a cell". Reporting it
     as "not annotated" is simply wrong, and it is the signal that teaches the model to ignore
     debris. Cellpose keeps these at `MIN_TRAIN_MASKS=0` (verified: only at 0 does it stop
     printing "removing from train set"). **micro_sam cannot** — torch_em's
     `MinInstanceSampler` has `p_reject=1.0`, so a patch with no instances is rejected every
     time; to use them there you must pass a sampler with `p_reject < 1.0`, or train that data
     through this Cellpose route.

   The guard that still matters: if empty tiles come to dominate, the model learns to predict
   nothing. Stage 3 warns above 40 %.

   **mSA is not comparable across different `MIN_TRAIN_MASKS` settings.** The held-out set is
   drawn from whatever passed validation, so keeping sparse tiles puts sparse tiles in the TEST
   set too, and they score lower. The SAME data and the SAME model can therefore report a much
   higher score on a few dense held-out tiles than on a mixed set — the lower number is the more
   honest one, and it is not a regression. Compare runs only within one setting.
2. **Fine-tuning can make a good model WORSE, and the wrong learning rate is the usual
   reason.** The gate catches it — stage 3 refuses to promote a model that scores below the
   baseline — but the user has already spent their annotation time and is told "fine-tuning
   did not help", which reads as "your labels were no good" when the real cause was a
   hyperparameter. If a round collapses to near-zero from a base that was already decent,
   suspect the learning rate before the annotations.
3. **v3 and v4 hyperparameters are not interchangeable.** cellpose 4's defaults are
   `learning_rate=1e-5`, `weight_decay=0.1`, `n_epochs=100`, `batch_size=1`, `rescale=False`.
   v3's *library* default `learning_rate=0.005` is **500x larger** and will destroy cpsam. The
   workflow pins its own value per version (v4 1e-5, v3 5e-4 — see pitfall 2); do not copy a
   raw v3 training recipe into either.
4. **A v3-fine-tuned file and a cpsam-fine-tuned file are not interchangeable either.** The
   state-dict keys differ, and loading one through the wrong env raises a key mismatch, not a
   readable "wrong model type". cpsam files load only through `cellpose4`.
5. **`diameter` is a v3 lever, not a v4 one.** cpsam does not rescale by diameter the way v3
   does. Leave `DIAMETER=None` unless you know why you are changing it — this is the single
   biggest accuracy knob on v3 models and a near-no-op on cpsam, which trips people who learned
   Cellpose on v3.
6. **tqdm floods the agent's context.** Cellpose prints a progress bar for the 1.15 GB model
   download and for every train and eval pass; `execute_script` hands all of stdout back. All
   three scripts set `TQDM_DISABLE=1` before importing cellpose. Do not remove it — the run
   goes from ~34 useful lines to thousands.
7. **Split by SOURCE IMAGE, never by tile.** Two tiles from one field share illumination, focus
   and cell population, so a tile-level split scores the model on what it has effectively
   already seen. Stage 3 holds out whole source images.
8. **A second round must be measured against the first, not against stock.** Stage 1 records
   `base_checkpoint`; stage 3 continues from it AND makes it the baseline. Scoring round 2
   against stock would credit it with round 1's gain and call a regression a win. When a round
   loses, stage 4 keeps the previous round's model rather than falling back to stock.
9. **Stage 4 refuses to run without `evaluation.json`.** "We fine-tuned it" is not the same
   claim as "it got better". `USE_MODEL="finetuned"` can force a checkpoint that lost, and then
   the script says so in its output — report that, do not quietly pass it.
10. **The task folder remembers which model the user corrected.** If stage 3 is pointed at a
   folder prepared with the other backend it trains anyway (the annotations are portable) but
   says so. The annotations are still valid; what is lost is the active-learning property that
   the user's time went on *this* model's remaining errors.

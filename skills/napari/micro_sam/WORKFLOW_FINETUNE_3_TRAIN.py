# imagentj-env: napari-mcp
"""
micro_sam fine-tuning — STAGE 3 of 4: validate the annotations, train, and PROVE it helped.

Reads the tiles the human finished in stage 2, refuses to train on anything that would produce
a broken model, fine-tunes the stock backbone on them (encoder + prompt/mask decoder + the AIS
decoder), exports a checkpoint micro_sam can load, and then measures the stock model and the
fine-tuned model on held-out tiles the training never saw.

The measurement is the point. Fine-tuning on a handful of tiles CAN make a model worse, and a
silent regression that only shows up 200 images into a batch run is the failure mode this
whole workflow exists to avoid. So this script always reports both numbers and names a winner;
stage 4 uses whichever won. If the fine-tuned model lost, say so to the user plainly — the
stock model stays in service and nothing downstream is affected.

GPU strongly recommended: ~10-20 min on an A100 for vit_b_lm. On CPU the same run is hours;
the script says so up front rather than appearing to hang.

Next: WORKFLOW_FINETUNE_4_APPLY.py

Run in the `napari-mcp` env via python_data_analyst (7200 s budget). Edit CONFIG, execute.
"""
import os
import glob
import json
import time
import shutil
import warnings

import numpy as np
import tifffile

warnings.filterwarnings("ignore")
# torch_em's trainer prints a tqdm bar per iteration. Left alone, a 1000-iteration run
# emits ~100 kB of progress bars, which is the whole tool-output budget and buries the
# results table below. tqdm honours this env var, so progress survives but as ~30 lines.
os.environ.setdefault("TQDM_MININTERVAL", "30")

# ---- CONFIG -----------------------------------------------------------------
TASK_DIR = "/app/data/projects/demo/microsam_finetune"   # the folder stage 1 wrote
RUN_NAME = "finetuned"        # names the checkpoint folder and the exported .pt
N_EPOCHS = 10                 # 1 epoch = 100 sampled training patches. 10 is a good default
                              # for 5-10 tiles; raise to 20-25 only if the gain is still rising.
N_OBJECTS_PER_BATCH = None    # prompts sampled per step. None = 8, which is a CPU budget,
                              # not a VRAM one: micro_sam builds each step's prompts
                              # iteratively on the CPU, so a big number starves the GPU
                              # rather than filling it. Measured on 1024 px tiles with an
                              # A100: 25 -> 8.7 s/it with the GPU at 0 %, 8 -> 0.65 s/it.
                              # Raise it only if you can see the GPU is the bottleneck.
N_SUB_ITERATION = 4           # prompt-refinement rounds per step (micro_sam's default is 8).
                              # Same CPU-side cost; 4 halves it for a marginal quality change.
NUM_WORKERS = 2               # dataloader processes. 0 (torch_em's default) puts the sampling
                              # on the training process and is the other half of the stall.
                              # 8 OOM'd a 12 GB container; 2 is safe and enough.
LEARNING_RATE = 1e-5          # micro_sam's default. Raising it on a few tiles overfits fast.
VAL_FRACTION = 0.25           # share of tiles held out to MEASURE the result (min 1 tile)
SAVE_EVERY_KTH_EPOCH = None   # None = judge only best.pt and latest.pt. An int k also keeps a
                              # checkpoint every k epochs and measures each of them, which finds
                              # the sweet spot when training overshoots — at ~1.3 GB per kept
                              # checkpoint during the run (all losers are deleted afterwards).
MIN_OBJECT_SIZE = 25          # px; objects smaller than this are dropped, matching micro_sam
FORCE = False                 # True = train even if the validation below reports problems
KEEP_RAW_CHECKPOINTS = False  # torch_em's own checkpoints are ~1.3 GB EACH and are only needed
                              # to resume training. The exported .pt is what every later stage
                              # loads, so they are deleted once the winner has been exported.
# -----------------------------------------------------------------------------


def ensure_model_cache(fallback_dir):
    """Point MICROSAM_CACHEDIR somewhere writable, and say so.

    micro_sam downloads its checkpoints with pooch into MICROSAM_CACHEDIR (default
    ~/.cache/micro_sam). In a container whose home is a named volume older than the image,
    that path can survive as a root-owned directory this process cannot write, and every
    model load then dies with `PermissionError: .../micro_sam/models` — a traceback that
    points at pooch and never mentions the volume. Probe it for real (mkdir + write, not a
    permission bit), fall back into the task folder, and carry over any weights already
    downloaded so the fallback costs no extra download."""
    import shutil

    current = os.environ.get("MICROSAM_CACHEDIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "micro_sam")
    models = os.path.join(current, "models")
    try:
        os.makedirs(models, exist_ok=True)
        probe = os.path.join(models, ".writable")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return current
    except OSError as exc:
        why = exc.strerror or str(exc)      # bind it: `exc` itself is gone after the block

    os.makedirs(os.path.join(fallback_dir, "models"), exist_ok=True)
    os.environ["MICROSAM_CACHEDIR"] = fallback_dir
    os.environ.setdefault("XDG_CACHE_HOME", os.path.dirname(fallback_dir))
    print(f"[train] model cache {current} is not writable ({why}) -> using {fallback_dir}")
    if os.path.isdir(models):
        for f in os.listdir(models):                       # reuse anything already downloaded
            src, dst = os.path.join(models, f), os.path.join(fallback_dir, "models", f)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy(src, dst)
                    print(f"[train]   carried over cached weight {f}")
                except OSError:
                    pass
    return fallback_dir

def load_manifest():
    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        return json.load(f)


def validate(manifest):
    """Reject anything that would train a broken model. Returns (usable, problems).

    Every rule here corresponds to a real failure: a shape mismatch silently pairs an image
    with the wrong labels; a tile with <2 objects is rejected by micro_sam's own
    MinInstanceSampler(2) and just burns sampling attempts; an all-zero tile teaches the AIS
    decoder that a field of objects is background.
    """
    usable, problems = [], []
    for e in manifest["tiles"]:
        name, p = e["name"], e["annotation_path"]
        if not os.path.exists(p):
            problems.append(f"{name}: not annotated (no {os.path.basename(p)})")
            continue
        lab = tifffile.imread(p)
        img = tifffile.imread(e["tile_path"])
        if lab.shape[:2] != img.shape[:2]:
            problems.append(f"{name}: label shape {lab.shape[:2]} != image shape {img.shape[:2]}")
            continue
        if lab.min() < 0 or not np.issubdtype(lab.dtype, np.integer):
            problems.append(f"{name}: labels must be non-negative integers, got {lab.dtype}")
            continue
        ids, counts = np.unique(lab, return_counts=True)
        keep = [(i, c) for i, c in zip(ids, counts) if i != 0 and c >= MIN_OBJECT_SIZE]
        # EMPTY is not the same as UNANNOTATED. The file exists, so the user opened this tile
        # and confirmed micro_sam's "Nothing is segmented yet" dialog — on a field of pure
        # debris that is the correct answer, and a deliberate negative example. micro_sam still
        # cannot train on it: torch_em's MinInstanceSampler(2) has p_reject=1.0, so a patch
        # with no instances is rejected every time and the tile is never sampled. Say that,
        # instead of reporting the user's careful work as missing.
        if not keep:
            problems.append(
                f"{name}: cleared to EMPTY by the user (a debris-only field). That is a "
                f"negative example, not a missing annotation — but torch_em's "
                f"MinInstanceSampler rejects a patch with no instances every time, so "
                f"micro_sam cannot learn from it. To use tiles like this, pass a sampler with "
                f"p_reject < 1.0, or train this data with the Cellpose route "
                f"(skills/python/cellpose/, MIN_TRAIN_MASKS=0), which accepts them.")
            continue
        if len(keep) < 2:
            problems.append(f"{name}: only {len(keep)} object(s) >= {MIN_OBJECT_SIZE} px. "
                            f"micro_sam's sampler needs >= 2 per training patch, so this real "
                            f"annotation cannot be used — excluded.")
            continue
        e = dict(e, n_objects=len(keep))
        usable.append(e)
    return usable, problems


def relabel_consecutive(lab):
    """1..N with no gaps and small objects dropped.

    Hand-edited masks always arrive with holes in the id sequence (delete object 7 of 30) and
    with slivers left over from a stray brush stroke. Both are harmless to look at and both
    break assumptions downstream, so they are normalised once, here.
    """
    out = np.zeros(lab.shape, dtype=np.uint32)
    nxt = 1
    for i in np.unique(lab):
        if i == 0:
            continue
        m = lab == i
        if m.sum() < MIN_OBJECT_SIZE:
            continue
        out[m] = nxt
        nxt += 1
    return out


def split_train_val(usable, val_fraction, seed=0):
    """Hold out whole SOURCE images when possible.

    Two tiles cut from the same field share illumination, focus and cell population. Splitting
    them across train and val makes the validation score look better than the model is, which
    defeats the only safeguard in this workflow.
    """
    rng = np.random.default_rng(seed)
    by_src = {}
    for e in usable:
        by_src.setdefault(e["source"], []).append(e)
    n_val = max(1, int(round(len(usable) * val_fraction)))

    if len(by_src) >= 3:
        srcs = sorted(by_src)
        rng.shuffle(srcs)
        val, i = [], 0
        while len(val) < n_val and i < len(srcs) - 1:      # never take every source
            val.extend(by_src[srcs[i]])
            i += 1
        val_names = {e["name"] for e in val}
        train = [e for e in usable if e["name"] not in val_names]
        mode = "by source image"
    else:
        order = sorted(usable, key=lambda e: e["name"])
        rng.shuffle(order)
        val, train, mode = order[:n_val], order[n_val:], "by tile (too few source images)"
    return train, val, mode


def materialise(entries, root, tag):
    """torch_em's ImageCollectionDataset wants folder + glob, so write the split to folders."""
    img_dir = os.path.join(root, tag, "images")
    lab_dir = os.path.join(root, tag, "labels")
    for d in (img_dir, lab_dir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    for e in entries:
        tifffile.imwrite(os.path.join(img_dir, e["name"] + ".tif"), tifffile.imread(e["tile_path"]))
        tifffile.imwrite(os.path.join(lab_dir, e["name"] + ".tif"),
                         relabel_consecutive(tifffile.imread(e["annotation_path"])))
    return img_dir, lab_dir


def segment_all(model_type, checkpoint, entries, device):
    import torch
    """AIS on each val tile. Val tiles are exactly one tile, so this matches what stage 4 does
    per tile on a full image — the reported numbers are the numbers you will actually get."""
    from micro_sam.automatic_segmentation import (
        get_predictor_and_segmenter, automatic_instance_segmentation,
    )
    predictor, segmenter = get_predictor_and_segmenter(
        model_type=model_type, checkpoint=checkpoint, device=device, segmentation_mode="ais",
    )
    out = {}
    for e in entries:
        img = tifffile.imread(e["tile_path"])
        out[e["name"]] = automatic_instance_segmentation(
            predictor=predictor, segmenter=segmenter, input_path=img, ndim=2, verbose=False,
        ).astype(np.uint32)
    del predictor, segmenter
    if device == "cuda":
        torch.cuda.empty_cache()
    return out


def score(preds, entries):
    from elf.evaluation import mean_segmentation_accuracy
    rows = []
    for e in entries:
        gt = relabel_consecutive(tifffile.imread(e["annotation_path"]))
        msa, accs = mean_segmentation_accuracy(preds[e["name"]], gt, return_accuracies=True)
        rows.append({"tile": e["name"], "msa": float(msa), "sa50": float(accs[0]),
                     "n_pred": int(preds[e["name"]].max()), "n_true": int(gt.max())})
    return rows


COLUMNS = (("what you annotated", (60, 255, 60)),
           ("stock model", (255, 80, 80)),
           ("fine-tuned model", (80, 160, 255)))


def comparison_png(entries, before, after, path):
    """One row per held-out tile, three columns. The single most useful artefact of the run:
    it shows at a glance WHERE the two models differ, which no scalar can."""
    from skimage.segmentation import find_boundaries
    import imageio.v3 as imageio
    panels = []
    for e in entries[:4]:
        img = tifffile.imread(e["tile_path"])
        gray = img.mean(-1) if img.ndim == 3 else img
        base = np.repeat(gray.astype(np.uint8)[..., None], 3, -1)
        row = []
        for lab, (_, colour) in zip(
            (relabel_consecutive(tifffile.imread(e["annotation_path"])),
             before[e["name"]], after[e["name"]]), COLUMNS
        ):
            v = base.copy()
            if lab.max() > 0:
                v[find_boundaries(lab, mode="outer")] = colour
            row.append(v)
        panels.append(np.concatenate(row, axis=1))
    if not panels:
        return
    grid = np.concatenate(panels, axis=0)

    try:                                   # a header strip, so the columns need no caption
        from PIL import Image, ImageDraw
        w = grid.shape[1] // 3
        header = Image.new("RGB", (grid.shape[1], 26), (0, 0, 0))
        draw = ImageDraw.Draw(header)
        for i, (title, colour) in enumerate(COLUMNS):
            draw.text((i * w + 8, 7), title, fill=colour)
        grid = np.concatenate([np.asarray(header), grid], axis=0)
    except Exception:
        pass
    imageio.imwrite(path, grid)


def main():
    import torch          # local: keeps validate()/relabel_consecutive()/split_train_val()
                        # importable and unit-testable without the GPU stack

    t0 = time.time()
    ensure_model_cache(os.path.join(TASK_DIR, ".micro_sam_cache"))
    manifest = load_manifest()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_type = manifest["model_type"]
    # Round 2+: the model the user actually corrected in stage 1/2. Training continues from it
    # and — this is the part that is easy to get wrong — the BASELINE becomes it too. Scoring
    # round 2 against stock would credit it with round 1's gain and call a regression a win.
    base_ckpt = manifest.get("base_checkpoint")
    if base_ckpt and not os.path.exists(base_ckpt):
        raise SystemExit(f"manifest names a base checkpoint that is gone: {base_ckpt}")
    baseline_name = "round-1 model" if base_ckpt else "stock"

    # --- validate ---------------------------------------------------------------
    usable, problems = validate(manifest)
    print("=" * 72)
    print(f"ANNOTATIONS: {len(usable)} of {manifest['n_tiles']} tiles usable, "
          f"{sum(e['n_objects'] for e in usable)} objects")
    for p in problems:
        print(f"  - {p}")
    if len(usable) < 3 and not FORCE:
        raise SystemExit(
            f"\nSTOP: {len(usable)} usable tile(s); at least 3 are needed (2 to train on, 1 to "
            f"measure with). Re-run WORKFLOW_FINETUNE_2_ANNOTATE.py — it resumes at the first "
            f"unfinished tile. Set FORCE=True only to override deliberately."
        )
    if len(usable) < 5:
        print(f"  NOTE: only {len(usable)} tiles. Training will run, but the measured gain will "
              f"be noisy and may be negative. 6-10 tiles is the reliable range.")

    train_e, val_e, split_mode = split_train_val(usable, VAL_FRACTION)
    print(f"SPLIT ({split_mode}): {len(train_e)} train, {len(val_e)} validation")
    print(f"  train: {', '.join(e['name'] for e in train_e)}")
    print(f"  val  : {', '.join(e['name'] for e in val_e)}   <- never seen during training")

    root = os.path.join(TASK_DIR, "training")
    tr_img, tr_lab = materialise(train_e, root, "train")
    va_img, va_lab = materialise(val_e, root, "val")

    # --- loaders ----------------------------------------------------------------
    import micro_sam.training as sam_training
    patch = (manifest["tile_size"], manifest["tile_size"])
    loader_kwargs = dict(
        raw_key="*.tif", label_key="*.tif", patch_shape=patch,
        with_segmentation_decoder=True, batch_size=1,
        # is_seg_dataset=False forces torch_em's ImageCollectionDataset, the only one that
        # copes with a folder of separate 2D images (grayscale or RGB, mixed sizes).
        is_seg_dataset=False,
        # identity, not the default require_8bit: stage 1 already wrote 8-bit tiles, and
        # require_8bit only rescales when max<1, so a 16-bit array would sail past it and
        # blow up in micro_sam's own [0,255] loader check.
        raw_transform=sam_training.identity,
        min_size=MIN_OBJECT_SIZE,
        # Sampling runs off the training process, and pinned memory makes the hand-off to
        # the GPU a DMA instead of a copy. Without these the GPU waits on the CPU all run.
        num_workers=NUM_WORKERS, pin_memory=(device == "cuda"),
    )
    train_loader = sam_training.default_sam_loader(
        raw_paths=tr_img, label_paths=tr_lab, is_train=True, shuffle=True, **loader_kwargs)
    val_loader = sam_training.default_sam_loader(
        raw_paths=va_img, label_paths=va_lab, is_train=False, shuffle=False, **loader_kwargs)

    # Not a VRAM decision: the cost of a large n_objects_per_batch is CPU-side prompt
    # construction, which leaves the GPU idle. 8 is the measured sweet spot on an A100;
    # a small GPU needs less for memory reasons, so only ever go DOWN from it.
    if N_OBJECTS_PER_BATCH is not None:
        n_obj = N_OBJECTS_PER_BATCH
    elif device == "cuda":
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        n_obj = 8 if vram >= 12 else 5
    else:
        n_obj = 5
    if device == "cpu":
        print("\n!! No GPU. This will take HOURS for a run that takes ~15 min on a GPU.\n"
              "   Either move to the GPU build, or stop here and keep the stock model.\n")

    # --- train ------------------------------------------------------------------
    print("-" * 72)
    print(f"TRAINING {model_type} on {device}  |  {N_EPOCHS} epochs x 100 patches  |  "
          f"n_objects_per_batch={n_obj}  n_sub_iteration={N_SUB_ITERATION}  "
          f"num_workers={NUM_WORKERS}")
    print("  (if this reports more than ~2 s/iteration on a GPU, the GPU is being starved by "
          "CPU-side\n   prompt sampling — lower N_OBJECTS_PER_BATCH before blaming the model.)")
    save_root = os.path.join(TASK_DIR, "training")
    sam_training.train_sam(
        name=RUN_NAME, model_type=model_type,
        train_loader=train_loader, val_loader=val_loader,
        n_epochs=N_EPOCHS, n_objects_per_batch=n_obj, lr=LEARNING_RATE,
        n_sub_iteration=N_SUB_ITERATION,
        checkpoint_path=base_ckpt,          # None on round 1 = start from the stock weights

        with_segmentation_decoder=True,     # required for AIS, i.e. for hands-off stage 4
        device=device, save_root=save_root,
        early_stopping=None,                # a few tiles give a noisy val curve; stopping on it
                                            # kills good runs after 10 epochs for no reason
        save_every_kth_epoch=SAVE_EVERY_KTH_EPOCH,
    )
    ckpt_dir = os.path.join(save_root, "checkpoints", RUN_NAME)
    if not os.path.exists(os.path.join(ckpt_dir, "best.pt")):
        raise SystemExit(f"Training produced no checkpoint in {ckpt_dir}.")

    # --- measure: stock vs every trained checkpoint, on the held-out tiles -------
    # Which checkpoint to keep is decided by SEGMENTATION QUALITY, not by the training loss.
    # torch_em's "best" epoch is chosen from the validation loss, which with 1-2 validation
    # tiles is 5 randomly cropped, randomly augmented patches per epoch — pure noise. A run
    # measured here went stock 0.573 -> best.pt 0.546 -> latest.pt 0.420 mSA: the loss said
    # epoch 0 was best, and the actual segmentation said neither was worth keeping. Scoring
    # the candidates directly costs a couple of minutes and removes that whole failure mode.
    from micro_sam.util import export_custom_sam_model
    model_dir = os.path.join(TASK_DIR, "model")
    os.makedirs(model_dir, exist_ok=True)

    candidates = []
    for fname in ("best.pt", "latest.pt"):
        if os.path.exists(os.path.join(ckpt_dir, fname)):
            candidates.append((os.path.splitext(fname)[0], os.path.join(ckpt_dir, fname)))
    for raw in sorted(glob.glob(os.path.join(ckpt_dir, "epoch-*.pt"))):
        candidates.append((os.path.splitext(os.path.basename(raw))[0], raw))

    print("-" * 72)
    print(f"EVALUATING the {baseline_name} + {len(candidates)} checkpoint(s) on "
          f"{len(val_e)} held-out tile(s) ...")
    before = segment_all(model_type, base_ckpt, val_e, device)
    rows_b = score(before, val_e)
    msa_b = float(np.mean([r["msa"] for r in rows_b]))
    print(f"  {baseline_name:<18} mSA {msa_b:.3f}")

    results, best_label, best_msa, after, rows_a = [], None, -1.0, None, None
    for label, raw in candidates:
        tmp = os.path.join(model_dir, f"_candidate_{label}.pt")
        export_custom_sam_model(
            checkpoint_path=raw,
            model_type=model_type[:5],      # "vit_b_lm" -> "vit_b": the BACKBONE, not the finetune
            save_path=tmp,
            with_segmentation_decoder=True,  # carries the AIS decoder into the exported file
        )
        preds = segment_all(model_type, tmp, val_e, device)
        rows = score(preds, val_e)
        msa = float(np.mean([r["msa"] for r in rows]))
        results.append({"checkpoint": label, "mean_msa": msa,
                        "mean_sa50": float(np.mean([r["sa50"] for r in rows]))})
        print(f"  {label:<18} mSA {msa:.3f}" + ("   <- best so far" if msa > best_msa else ""))
        if msa > best_msa:
            best_label, best_msa, after, rows_a = label, msa, preds, rows
        else:
            os.remove(tmp)
    exported = os.path.join(model_dir, f"{RUN_NAME}_{model_type}.pt")
    if os.path.exists(exported):
        os.remove(exported)
    os.rename(os.path.join(model_dir, f"_candidate_{best_label}.pt"), exported)
    print(f"kept {best_label} -> {exported}  ({os.path.getsize(exported) / 1e6:.0f} MB)")
    if not KEEP_RAW_CHECKPOINTS:
        freed = sum(os.path.getsize(os.path.join(ckpt_dir, f)) for f in os.listdir(ckpt_dir))
        shutil.rmtree(ckpt_dir, ignore_errors=True)
        print(f"     (removed {freed / 1e9:.1f} GB of raw training checkpoints; the exported "
              f"file above is all stage 4 needs)")

    print(f"\n{'tile':<14}{'objects':>8} | {'stock mSA':>10}{'  SA50':>8}{'  n':>5} | "
          f"{'tuned mSA':>10}{'  SA50':>8}{'  n':>5}")
    print("-" * 72)
    for b, a in zip(rows_b, rows_a):
        print(f"{b['tile']:<14}{b['n_true']:>8} | {b['msa']:>10.3f}{b['sa50']:>8.3f}{b['n_pred']:>5} | "
              f"{a['msa']:>10.3f}{a['sa50']:>8.3f}{a['n_pred']:>5}")
    msa_b, msa_a = float(np.mean([r["msa"] for r in rows_b])), float(np.mean([r["msa"] for r in rows_a]))
    sa_b, sa_a = float(np.mean([r["sa50"] for r in rows_b])), float(np.mean([r["sa50"] for r in rows_a]))
    print("-" * 72)
    print(f"{'MEAN':<14}{'':>8} | {msa_b:>10.3f}{sa_b:>8.3f}{'':>5} | {msa_a:>10.3f}{sa_a:>8.3f}")

    improved = msa_a > msa_b
    delta = msa_a - msa_b
    # A baseline of exactly 0 (the stock model finds nothing at all) has no percentage —
    # printing "+nan %" in the headline result reads like a crash.
    rel = (f"{100 * delta / msa_b:+.1f} %" if msa_b > 0
           else "up from a baseline that found nothing")
    # Losing means "keep what we had" — which on round 2 is the ROUND-1 checkpoint, not stock.
    # Returning None here would silently throw away a good round-1 model.
    winner_ckpt = exported if improved else base_ckpt
    print("-" * 72)
    if improved:
        print(f"RESULT: fine-tuned model WINS ({best_label}).  mSA {msa_b:.3f} -> {msa_a:.3f} "
              f"({delta:+.3f}, {rel}).  Stage 4 will use the fine-tuned checkpoint.")
    else:
        print(f"RESULT: fine-tuning did NOT help. The BEST of {len(candidates)} checkpoint(s) "
              f"still scored {msa_a:.3f} against the {baseline_name}'s {msa_b:.3f} ({delta:+.3f}).\n"
              f"        Stage 4 will keep the "
              f"{'ROUND-1 fine-tuned model' if base_ckpt else 'STOCK ' + model_type}. "
              f"Tell the user plainly.\n"
              f"        Most likely causes, in order:\n"
              f"        1. The annotations are not better than what the stock model already does.\n"
              f"           Look at evaluation_comparison.png — if the 'your annotation' column is\n"
              f"           not visibly tighter than the 'stock' column, there is nothing to learn.\n"
              f"        2. Too few tiles (have {len(usable)}, want 6-10).\n"
              f"        3. Inconsistent annotation between tiles — outlines drawn tight on one tile\n"
              f"           and loose on the next teach the model to be inconsistent.\n"
              f"        4. This data is already IN the stock model's training set. The *_lm\n"
              f"           generalists were trained on LIVECell, DeepBacs, TissueNet, NeurIPS\n"
              f"           CellSeg, PlantSeg (root), Nucleus DSB and 8 Cell Tracking Challenge\n"
              f"           datasets (Nat Methods 2024, s41592-024-02580-4). If the data looks\n"
              f"           like one of those, a handful of tiles cannot improve on it.")

    comparison_png(val_e, before, after, os.path.join(TASK_DIR, "evaluation_comparison.png"))

    result = {
        "run_name": RUN_NAME, "model_type": model_type, "device": device,
        "base_checkpoint": base_ckpt, "baseline": baseline_name,
        "n_epochs": N_EPOCHS, "n_objects_per_batch": n_obj, "lr": LEARNING_RATE,
        "n_sub_iteration": N_SUB_ITERATION, "num_workers": NUM_WORKERS,
        "tile_size": manifest["tile_size"], "tiled_inference": manifest.get("tiled_inference", False),
        "split_mode": split_mode,
        "train_tiles": [e["name"] for e in train_e], "val_tiles": [e["name"] for e in val_e],
        "n_train_objects": sum(e["n_objects"] for e in train_e),
        "n_val_objects": sum(e["n_objects"] for e in val_e),
        "checkpoint": exported, "selected_checkpoint": best_label,
        "checkpoint_candidates": results,
        "stock": {"mean_msa": msa_b, "mean_sa50": sa_b, "per_tile": rows_b},
        "finetuned": {"mean_msa": msa_a, "mean_sa50": sa_a, "per_tile": rows_a},
        "improved": bool(improved), "delta_msa": delta, "relative_percent": rel,
        # stage 4 reads exactly this: None means "the stock weights won, do not load a checkpoint"
        "recommended_checkpoint": winner_ckpt,
        "comparison_png": os.path.join(TASK_DIR, "evaluation_comparison.png"),
        "minutes": round((time.time() - t0) / 60, 1),
        "problems": problems,
    }
    with open(os.path.join(TASK_DIR, "evaluation.json"), "w") as f:
        json.dump(result, f, indent=2)

    print("-" * 72)
    print(f"evaluation.json : {os.path.join(TASK_DIR, 'evaluation.json')}")
    print(f"comparison PNG  : {result['comparison_png']}  "
          f"(columns: your annotation | stock | fine-tuned)")
    print(f"total time      : {result['minutes']} min")
    print(f"NEXT -> WORKFLOW_FINETUNE_4_APPLY.py with TASK_DIR = {TASK_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()

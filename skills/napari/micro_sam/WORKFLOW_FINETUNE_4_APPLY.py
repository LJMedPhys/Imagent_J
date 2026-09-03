# imagentj-env: napari-mcp
"""
micro_sam fine-tuning — STAGE 4 of 4: segment the whole dataset with the model that won.

Reads `evaluation.json` from stage 3 and uses `recommended_checkpoint`: the fine-tuned weights
if they beat the stock model on the held-out tiles, the stock weights if they did not. Nothing
here re-decides that — stage 3 measured it, this stage obeys it — so a fine-tuning run that
failed can never silently degrade a whole batch.

Two things this gets right that a hand-written loop does not:
  * TILED inference at the annotation tile size when the images are bigger than the tiles.
    SAM resizes whatever it is handed to 1024 px, so a model trained on 512 px crops has
    learned objects at the size they appear AFTER that resize. Feed it a whole 2048 px field
    and every object arrives 4x smaller than anything it was trained on and the fine-tuning
    gain disappears. Tiling makes inference see exactly the scale training did.
  * The same 8-bit conversion and channel selection stage 1 applied to the tiles, so the model
    is not handed a differently-scaled version of the same data.

Output: one uint32 label TIFF per image, a counts CSV, and a few overlay previews.
These masks feed straight into a python_data_analyst measurement step (regionprops /
cp_measure), exactly like a StarDist or Cellpose mask.

Run in the `napari-mcp` env via python_data_analyst. Edit CONFIG, execute.
"""
import os
import glob
import json
import time

import numpy as np
import pandas as pd
import tifffile

os.environ.setdefault("TQDM_MININTERVAL", "30")   # keep the progress bars out of the transcript

# ---- CONFIG -----------------------------------------------------------------
TASK_DIR = "/app/data/projects/demo/microsam_finetune"   # the folder stage 1 wrote
INPUT_DIR = None       # None = the folder stage 1 used. Set a path to run on a different
                       # (e.g. much larger) folder acquired the same way.
OUTPUT_DIR = None      # None = <TASK_DIR>/segmentation
USE_MODEL = "auto"     # "auto"      -> whatever stage 3 measured as better (recommended)
                       # "finetuned" -> force the fine-tuned checkpoint
                       # "stock"     -> force the original weights
EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")   # matched CASE-INSENSITIVELY (".TIF" too)
N_PREVIEWS = 3         # overlay PNGs to write so the result can be eyeballed / VLM-checked
MIN_OBJECT_SIZE = 25   # px; drop specks, matching the training-time filter
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
    print(f"[apply] model cache {current} is not writable ({why}) -> using {fallback_dir}")
    if os.path.isdir(models):
        for f in os.listdir(models):                       # reuse anything already downloaded
            src, dst = os.path.join(models, f), os.path.join(fallback_dir, "models", f)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy(src, dst)
                    print(f"[apply]   carried over cached weight {f}")
                except OSError:
                    pass
    return fallback_dir

def to_uint8(arr):
    arr = np.asarray(arr)
    if arr.dtype == np.uint8:
        return arr
    a = arr.astype(np.float32)
    lo, hi = np.percentile(a, 0.1), np.percentile(a, 99.9)
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros(a.shape, np.uint8)
    return np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def read_image(path, channel):
    """Identical reduction to stage 1's — same channel, same 8-bit scaling."""
    if path.lower().endswith((".tif", ".tiff")):
        img = tifffile.imread(path)
    else:
        import imageio.v3 as imageio
        img = imageio.imread(path)
    img = np.squeeze(np.asarray(img))
    if img.ndim == 3 and img.shape[-1] in (3, 4):
        img = img[..., :3]
    elif img.ndim == 3:
        if channel is None:
            raise ValueError(f"{os.path.basename(path)} is 3D {img.shape} but the manifest has no "
                             f"channel — re-run stage 1 with CHANNEL set.")
        img = img.max(axis=0) if channel == "max" else img[int(channel)]
    elif img.ndim != 2:
        raise ValueError(f"{os.path.basename(path)}: unsupported shape {img.shape}")
    return to_uint8(img)


def drop_small(labels, min_size):
    ids, counts = np.unique(labels, return_counts=True)
    small = {int(i) for i, c in zip(ids, counts) if i != 0 and c < min_size}
    if small:
        labels = np.where(np.isin(labels, list(small)), 0, labels)
    return labels.astype(np.uint32)


def main():
    import torch          # local: keeps this module importable without the GPU stack

    t0 = time.time()
    ensure_model_cache(os.path.join(TASK_DIR, ".micro_sam_cache"))
    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    eval_path = os.path.join(TASK_DIR, "evaluation.json")
    if not os.path.exists(eval_path):
        raise SystemExit(f"No {eval_path}. Run WORKFLOW_FINETUNE_3_TRAIN.py first.")
    with open(eval_path) as f:
        ev = json.load(f)

    model_type = manifest["model_type"]
    if USE_MODEL == "auto":
        checkpoint = ev.get("recommended_checkpoint")
    elif USE_MODEL == "finetuned":
        checkpoint = ev["checkpoint"]
    elif USE_MODEL == "stock":
        checkpoint = None
    else:
        raise ValueError(f"USE_MODEL must be auto/finetuned/stock, got {USE_MODEL!r}")
    if checkpoint and not os.path.exists(checkpoint):
        raise SystemExit(f"Checkpoint missing: {checkpoint}")

    which = "FINE-TUNED" if checkpoint else "STOCK"
    print("=" * 72)
    print(f"MODEL: {which} {model_type}" + (f"\n       {checkpoint}" if checkpoint else ""))
    print(f"       held-out mSA  stock {ev['stock']['mean_msa']:.3f}  ->  "
          f"fine-tuned {ev['finetuned']['mean_msa']:.3f}"
          + ("" if ev["improved"] else "   (fine-tuning did NOT help — using stock, as measured)"))
    if USE_MODEL != "auto":
        print(f"       (forced by USE_MODEL={USE_MODEL!r}, overriding the measurement)")

    in_dir = INPUT_DIR or manifest["input_dir"]
    out_dir = OUTPUT_DIR or os.path.join(TASK_DIR, "segmentation")
    os.makedirs(out_dir, exist_ok=True)
    # Case-INSENSITIVE: microscope exports are routinely ".TIF", and globbing "*.tif" on a
    # case-sensitive filesystem matches none of them and reports the folder as empty.
    wanted = {e.lower() for e in EXTS}
    paths = sorted(os.path.join(in_dir, f) for f in os.listdir(in_dir)
                   if os.path.splitext(f)[1].lower() in wanted
                   and os.path.isfile(os.path.join(in_dir, f)))
    if not paths:
        raise FileNotFoundError(f"No images matching {EXTS} in {in_dir}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tile = manifest["tile_size"]
    channel = manifest.get("channel")

    # Decide tiling from THIS folder, not from the manifest: the apply set may differ in size
    # from the images the tiles were cut out of.
    probe = read_image(paths[0], channel)
    h, w = probe.shape[:2]
    use_tiling = max(h, w) > tile
    halo = (max(tile // 8, 32),) * 2
    print(f"IMAGES: {len(paths)} in {in_dir}  (first is {h}x{w})")
    print(f"TILING: {'ON' if use_tiling else 'off'}"
          + (f"  tile_shape={(tile, tile)} halo={halo}  <- matches the annotation tile size, "
             f"so objects reach the model at the scale it was trained on" if use_tiling
             else f"  (images fit in one {tile} px tile)"))
    print("-" * 72)

    from micro_sam.automatic_segmentation import (
        get_predictor_and_segmenter, automatic_instance_segmentation,
    )
    predictor, segmenter = get_predictor_and_segmenter(
        model_type=model_type, checkpoint=checkpoint, device=device,
        segmentation_mode="ais",            # needs the decoder — stage 3 trained and exported one
        is_tiled=use_tiling,                # must match the tile_shape passed below
    )

    tiled_kwargs = dict(tile_shape=(tile, tile), halo=halo) if use_tiling else {}
    rows, previews = [], []
    for i, path in enumerate(paths):
        img = read_image(path, channel)
        labels = automatic_instance_segmentation(
            predictor=predictor, segmenter=segmenter, input_path=img, ndim=2,
            verbose=False, **tiled_kwargs,
        )
        labels = drop_small(np.asarray(labels), MIN_OBJECT_SIZE)
        n = int(len(np.unique(labels)) - (1 if 0 in labels else 0))
        stem = os.path.splitext(os.path.basename(path))[0]
        out_tif = os.path.join(out_dir, f"{stem}_masks.tif")
        tifffile.imwrite(out_tif, labels)
        rows.append({"image": os.path.basename(path), "n_objects": n, "mask_path": out_tif})
        print(f"  [{i + 1}/{len(paths)}] {os.path.basename(path):<40} {n:>5} objects")
        if len(previews) < N_PREVIEWS:
            previews.append((img, labels, stem))

    csv_path = os.path.join(out_dir, "object_counts.csv")
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)

    prev_dir = os.path.join(out_dir, "previews")
    os.makedirs(prev_dir, exist_ok=True)
    from skimage.segmentation import find_boundaries
    import imageio.v3 as imageio
    for img, labels, stem in previews:
        gray = img.mean(-1) if img.ndim == 3 else img
        rgb = np.repeat(gray.astype(np.uint8)[..., None], 3, -1)
        if labels.max() > 0:
            rgb[find_boundaries(labels, mode="outer")] = (255, 60, 60)
        imageio.imwrite(os.path.join(prev_dir, f"{stem}_overlay.png"), rgb)

    print("-" * 72)
    print(f"masks     : {out_dir}")
    print(f"counts CSV: {csv_path}")
    print(f"previews  : {prev_dir}")
    print(f"objects   : {int(df.n_objects.sum())} total, "
          f"{df.n_objects.mean():.1f} per image (min {int(df.n_objects.min())}, "
          f"max {int(df.n_objects.max())})")
    print(f"time      : {(time.time() - t0) / 60:.1f} min "
          f"({(time.time() - t0) / max(len(paths), 1):.1f} s per image on {device})")
    print("=" * 72)


if __name__ == "__main__":
    main()

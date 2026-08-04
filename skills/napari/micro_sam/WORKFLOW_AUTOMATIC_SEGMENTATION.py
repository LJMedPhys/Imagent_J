# imagentj-env: napari-mcp
"""
micro_sam batch automatic instance segmentation.

Segments every image in an input folder with a microscopy-finetuned Segment-Anything model
and writes, per image, a uint32 label TIFF plus one row in an object-count CSV. The SAM model
is built ONCE and reused across the folder. GPU is used automatically when available.

This is the headless (backend = python_data_analyst) route for micro_sam. For interactive,
click-corrected segmentation the supervisor instead drives annotator_2d in the live napari
viewer via mcp__napari_mcp__execute_code — see the SKILL.

Run in the `napari-mcp` env (the `# imagentj-env` header above selects it). Edit the three
CONFIG paths and the model, then execute.
"""
import os
import glob
import numpy as np
import pandas as pd
import tifffile
import torch
from micro_sam.automatic_segmentation import (
    get_predictor_and_segmenter,
    automatic_instance_segmentation,
)

# ---- CONFIG -----------------------------------------------------------------
INPUT_DIR = "/app/data/projects/demo/raw_images"
OUTPUT_DIR = "/app/data/projects/demo/processed"
MODEL_TYPE = None              # None = auto-pick by device (see below). Pin a string to
                               # override, e.g. "vit_b_lm", or "*_em_organelles" for EM.
CHECKPOINT_PATH = None         # Path to a FINE-TUNED checkpoint (e.g. produced by
                               # micro_sam.training on a first, hand-corrected image), or
                               # None for the stock MODEL_TYPE weights. THIS is the field
                               # that must be set for a fine-tuned model to actually reach
                               # the rest of the folder — MODEL_TYPE alone always loads the
                               # stock weights, silently ignoring any fine-tuning you did.
SEG_MODE = "ais"               # decoder-based Automatic Instance Segmentation (recommended)
EXTS = ("*.tif", "*.tiff", "*.png")
# -----------------------------------------------------------------------------

os.makedirs(OUTPUT_DIR, exist_ok=True)
device = "cuda" if torch.cuda.is_available() else "cpu"
# vit_b_lm is ~9x larger than vit_t_lm and much slower to embed on CPU, so the
# tiny backbone is the right default on a CPU build.
if MODEL_TYPE is None:
    MODEL_TYPE = "vit_b_lm" if device == "cuda" else "vit_t_lm"
print(f"micro_sam: model={MODEL_TYPE} checkpoint={CHECKPOINT_PATH or '(stock)'} "
      f"mode={SEG_MODE} device={device}")

# Build the model ONCE (loads weights / downloads the checkpoint on first use) and reuse
# it for every image below — this is what makes "fine-tune once, apply to the rest of the
# folder" work; CHECKPOINT_PATH is the only thing that actually carries a fine-tuned model
# into this loop, `get_predictor_and_segmenter` has no separate decoder override, so a
# custom checkpoint used with SEG_MODE="ais" must already carry a matching decoder.
predictor, segmenter = get_predictor_and_segmenter(
    model_type=MODEL_TYPE, checkpoint=CHECKPOINT_PATH, device=device, segmentation_mode=SEG_MODE,
)

paths = sorted(p for ext in EXTS for p in glob.glob(os.path.join(INPUT_DIR, ext)))
if not paths:
    raise FileNotFoundError(f"No images matching {EXTS} in {INPUT_DIR}")

rows = []
for path in paths:
    image = tifffile.imread(path) if path.lower().endswith((".tif", ".tiff")) else \
        np.asarray(__import__("skimage.io", fromlist=["imread"]).imread(path))

    labels = automatic_instance_segmentation(
        predictor=predictor, segmenter=segmenter,
        input_path=image,
        ndim=2,                       # REQUIRED for array input (2D plane)
        verbose=False,
    ).astype(np.uint32)

    n_objects = int(len(np.unique(labels)) - 1)   # minus background (0)
    stem = os.path.splitext(os.path.basename(path))[0]
    out_tif = os.path.join(OUTPUT_DIR, f"{stem}_masks.tif")
    tifffile.imwrite(out_tif, labels)
    rows.append({"image": os.path.basename(path), "n_objects": n_objects, "mask_path": out_tif})
    print(f"  {os.path.basename(path)} -> {n_objects} objects -> {out_tif}")

csv_path = os.path.join(OUTPUT_DIR, "micro_sam_object_counts.csv")
pd.DataFrame(rows).to_csv(csv_path, index=False)
print(f"Wrote {csv_path}")
# The per-image label TIFFs feed straight into a python_data_analyst measurement step
# (skimage.measure.regionprops_table or cp_measure), exactly like a StarDist/Cellpose mask.

# imagentj-env: napari-mcp
"""
Apply an object classifier trained interactively on the first image to the REST of the
folder — headless, no napari window, no further clicking.

This is the automatic counterpart to WORKFLOW_OBJECT_CLASSIFIER.py. The interactive
session exports `rf.joblib`; this script loads it and classifies every remaining image
with micro_sam's own `run_prediction_with_object_classifier`.

Verified end-to-end on micro_sam 1.8.2: a forest trained on one image, exported to
rf.joblib, then loaded in a FRESH process with no viewer, classified 12/12 objects
correctly across two unseen images.

WHAT THIS DOES AND DOES NOT DO
------------------------------
It CLASSIFIES objects that are already segmented — it does not create masks. Every image
needs a label mask as input. So "segment the rest automatically" is TWO stages:

    stage A   WORKFLOW_AUTOMATIC_SEGMENTATION.py   images -> label masks
    stage B   this script                          masks + rf.joblib -> class labels

If the user's masks came from StarDist/Cellpose/ImageJ instead, that is fine — stage A is
whatever produced the masks; only the label TIFFs matter here.

>>> IMPORTANT — this does NOT carry over SAM point prompts. <<<
Clicking a point in `annotator_2d` and pressing `S` is inference-time conditioning for that
ONE image: nothing is learned and no model is updated, so there is nothing to transfer. Only
the object CLASSIFIER (the `annotations` layer + "Train and predict") learns anything reusable.
To auto-generate masks for the rest of the folder, run automatic instance segmentation
(stage A) — it does not and cannot use the prompts from image 1.
"""
import os
import glob
import json

import numpy as np
import pandas as pd
import tifffile
import torch

from micro_sam.util import get_sam_model
from micro_sam.object_classification import run_prediction_with_object_classifier

# ---- CONFIG -----------------------------------------------------------------
IMAGE_DIR = "/app/data/projects/demo/raw_images"
SEG_DIR = "/app/data/projects/demo/processed"        # label masks (stage A output)
SESSION_DIR = "/app/data/projects/demo/classified"   # holds rf.joblib from the UI session
OUTPUT_DIR = "/app/data/projects/demo/classified_batch"
SEG_SUFFIX = "_masks"        # seg file = <image stem><SEG_SUFFIX>.tif; "" if names match
MODEL_TYPE = None            # None = read from classifier_meta.json (recommended)
SKIP_ALREADY_ANNOTATED = True  # skip images the interactive session already wrote
EXTS = ("*.tif", "*.tiff", "*.png")
# -----------------------------------------------------------------------------

RF_PATH = os.path.join(SESSION_DIR, "rf.joblib")
if not os.path.exists(RF_PATH):
    raise FileNotFoundError(
        f"No classifier at {RF_PATH}. Run WORKFLOW_OBJECT_CLASSIFIER.py first and press "
        f"'Next Image [N]' at least once — rf.joblib is written on each advance."
    )

# The forest is trained on SAM embedding features. Every backbone emits 256 channels, so a
# 257-wide vector from the WRONG model still fits and sklearn predicts silently wrong classes
# rather than raising. Pin the backbone to whatever trained it.
meta_path = os.path.join(SESSION_DIR, "classifier_meta.json")
trained_with = None
if os.path.exists(meta_path):
    with open(meta_path) as f:
        trained_with = json.load(f).get("model_type")

if MODEL_TYPE is None:
    if trained_with is None:
        raise ValueError(
            f"No {meta_path} and MODEL_TYPE is None. Set MODEL_TYPE to the SAME model the "
            f"interactive session used — a mismatch does NOT error, it silently misclassifies."
        )
    MODEL_TYPE = trained_with
elif trained_with is not None and MODEL_TYPE != trained_with:
    raise ValueError(
        f"MODEL_TYPE={MODEL_TYPE!r} but the classifier was trained with {trained_with!r}. "
        f"Feature widths match across backbones, so this would misclassify silently rather "
        f"than fail. Use {trained_with!r}, or retrain."
    )


def _seg_path_for(image_path):
    stem = os.path.splitext(os.path.basename(image_path))[0]
    for ext in (".tif", ".tiff", ".png"):
        candidate = os.path.join(SEG_DIR, f"{stem}{SEG_SUFFIX}{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


os.makedirs(OUTPUT_DIR, exist_ok=True)
all_images = sorted(p for ext in EXTS for p in glob.glob(os.path.join(IMAGE_DIR, ext)))
if not all_images:
    raise FileNotFoundError(f"No images matching {EXTS} in {IMAGE_DIR}")

image_paths, seg_paths, skipped = [], [], []
for p in all_images:
    stem = os.path.splitext(os.path.basename(p))[0]
    # Images the user already classified by hand keep their interactive result.
    if SKIP_ALREADY_ANNOTATED and os.path.exists(os.path.join(SESSION_DIR, f"{stem}_prediction.tif")):
        skipped.append(os.path.basename(p))
        continue
    seg = _seg_path_for(p)
    if seg is None:
        skipped.append(f"{os.path.basename(p)} (no mask)")
        continue
    image_paths.append(p)
    seg_paths.append(seg)

if not image_paths:
    raise FileNotFoundError(
        f"Nothing left to classify. Skipped: {skipped}. Masks must exist in {SEG_DIR} — "
        f"run the segmentation stage first."
    )

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"object classifier batch: {len(image_paths)} images, model={MODEL_TYPE}, device={device}")
if skipped:
    print(f"  skipped {len(skipped)}: {skipped}")

images = [np.asarray(tifffile.imread(p)) if p.lower().endswith((".tif", ".tiff"))
          else np.asarray(__import__("skimage.io", fromlist=["imread"]).imread(p))
          for p in image_paths]
segmentations = [np.asarray(tifffile.imread(p)).astype("uint32") for p in seg_paths]

predictor = get_sam_model(model_type=MODEL_TYPE, device=device)
predictions = run_prediction_with_object_classifier(
    images=images, segmentations=segmentations,
    predictor=predictor, rf_path=RF_PATH, ndim=2,
)

rows = []
for path, seg, pred in zip(image_paths, segmentations, predictions):
    stem = os.path.splitext(os.path.basename(path))[0]
    out_tif = os.path.join(OUTPUT_DIR, f"{stem}_classified.tif")
    tifffile.imwrite(out_tif, pred.astype("uint32"))

    # Per-class object counts: count each OBJECT once, not its pixels.
    row = {"image": os.path.basename(path), "n_objects": int(len(np.unique(seg)) - 1)}
    for obj_id in np.unique(seg):
        if obj_id == 0:
            continue
        cls = int(np.bincount(pred[seg == obj_id].ravel()).argmax())
        row[f"class_{cls}"] = row.get(f"class_{cls}", 0) + 1
    row["mask_path"] = out_tif
    rows.append(row)
    counts = {k: v for k, v in row.items() if k.startswith("class_")}
    print(f"  {os.path.basename(path)} -> {counts} -> {out_tif}")

csv_path = os.path.join(OUTPUT_DIR, "object_class_counts.csv")
pd.DataFrame(rows).fillna(0).to_csv(csv_path, index=False)
print(f"Wrote {csv_path}")

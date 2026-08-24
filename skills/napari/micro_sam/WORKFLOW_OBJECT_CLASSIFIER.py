# imagentj-env: napari-mcp
"""
micro_sam interactive object classifier over an image series — with the trained
classifier ACTUALLY applied to every subsequent image.

Annotate object classes on the first image (paint a dot on each object with the
`annotations` layer), press "Train and predict", then press "Next Image [N]".
Images 2..N are classified automatically with what was learned so far; correct
anything wrong and press "Train and predict" again to fold those corrections in.

WHY THIS WRAPPER EXISTS
-----------------------
Stock `image_series_object_classifier` trains a random forest on image 1 and keeps
it in `AnnotatorState().object_rf`, but its `next_image()` never calls it. It ends
with `annotator._update_image()`, which ZEROES the `prediction` layer, then nulls
`object_features`/`seg_ids` — so image 2 comes up blank and the classifier is never
applied. Worse, the next press of `N` saves that blank: `_save_prediction` writes
whatever is in the `prediction` layer, so images 2..N land on disk as all-zero
label TIFFs. micro_sam knows the path is incomplete — `object_classifier.py`
carries `# TODO handle cases where rf for the image was not trained ...` directly
above `next_image`.

Verified against micro_sam 1.8.2: the classifier itself transfers fine (a RF
trained on image 1 classified image 2's objects 6/6 correctly). The only missing
piece is the call, which is what this file adds.

HOW
---
One hook: wrap `ObjectClassifier._update_image` so that after it resets the layers
it re-runs the retained RF on the new image. That is the same work the "Train and
predict" button does, minus the training. Everything else — feature/label
accumulation, `rf.joblib` export, the end-of-series dialog — is stock micro_sam.

RUNNING IT
----------
Run as a `python_data_analyst` script (the `# imagentj-env` header selects the env).
It opens its own napari window on the VNC desktop and BLOCKS until the user closes
it — that is correct for an interactive tool and is why it must not go through
`mcp__napari_mcp__execute_code` (90 s Qt-thread timeout; the NapariComputeGuard
middleware blocks that route anyway).

Segmentations are an INPUT here. This tool classifies objects that already exist —
produce the masks first (WORKFLOW_AUTOMATIC_SEGMENTATION.py, StarDist, Cellpose,
...), then classify them here.
"""
import os
import glob
import json

import numpy as np
import imageio.v3 as imageio
import torch

from micro_sam.sam_annotator._state import AnnotatorState
from micro_sam.sam_annotator.object_classifier import (
    ObjectClassifier,
    image_series_object_classifier,
)
from micro_sam.object_classification import (
    compute_object_features,
    project_prediction_to_segmentation,
)

# ---- CONFIG -----------------------------------------------------------------
IMAGE_DIR = "/app/data/projects/demo/raw_images"
SEG_DIR = "/app/data/projects/demo/processed"      # label masks, one per image
OUTPUT_DIR = "/app/data/projects/demo/classified"  # predictions + rf.joblib + features
SEG_SUFFIX = "_masks"        # seg file = <image stem><SEG_SUFFIX>.tif; "" if names match
MODEL_TYPE = None            # None = auto-pick by device
EXTS = ("*.tif", "*.tiff", "*.png")
# -----------------------------------------------------------------------------

device = "cuda" if torch.cuda.is_available() else "cpu"
if MODEL_TYPE is None:
    MODEL_TYPE = "vit_b_lm" if device == "cuda" else "vit_t_lm"


# ---- the fix: auto-apply the trained classifier on every new image ----------
_ORIG_UPDATE_IMAGE = ObjectClassifier._update_image


def _update_image_and_apply_rf(self, segmentation_result=None):
    """Stock `_update_image`, then re-run the retained RF on the freshly loaded image.

    Called on initial setup (no RF yet -> no-op), from the embedding widget's run
    button, and from `next_image` after the new image/segmentation/embeddings are
    already in place. Every failure mode here is non-fatal: a classifier that
    cannot be applied must not take the annotation session down with it, so the
    user is told and left with the blank layer they would have had anyway.
    """
    _ORIG_UPDATE_IMAGE(self, segmentation_result=segmentation_result)

    state = AnnotatorState()
    rf = getattr(state, "object_rf", None)
    if rf is None:
        return  # nothing trained yet — first image

    viewer = self._viewer
    if "segmentation" not in viewer.layers or "prediction" not in viewer.layers:
        return

    embeddings = getattr(state, "image_embeddings", None)
    if embeddings is None:
        return  # embeddings not computed for this image yet

    segmentation = np.asarray(viewer.layers["segmentation"].data)
    if segmentation.max() == 0:
        return  # nothing to classify

    try:
        seg_ids, features = compute_object_features(embeddings, segmentation, verbose=False)
        prediction = rf.predict(features)
        viewer.layers["prediction"].data = project_prediction_to_segmentation(
            segmentation, prediction, seg_ids
        )
        n = int(len(np.unique(prediction)))
        print(f"[auto-apply] classified {len(seg_ids)} objects into {n} class(es) "
              f"using the classifier trained so far")
    except Exception as e:
        print(f"[auto-apply] could not apply the classifier to this image: "
              f"{type(e).__name__}: {e}")


ObjectClassifier._update_image = _update_image_and_apply_rf
# -----------------------------------------------------------------------------


def _seg_path_for(image_path):
    stem = os.path.splitext(os.path.basename(image_path))[0]
    for ext in (".tif", ".tiff", ".png"):
        candidate = os.path.join(SEG_DIR, f"{stem}{SEG_SUFFIX}{ext}")
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        f"No segmentation for {os.path.basename(image_path)} — expected "
        f"{stem}{SEG_SUFFIX}.tif in {SEG_DIR}. Segment the folder first."
    )


image_paths = sorted(p for ext in EXTS for p in glob.glob(os.path.join(IMAGE_DIR, ext)))
if not image_paths:
    raise FileNotFoundError(f"No images matching {EXTS} in {IMAGE_DIR}")

images = [np.asarray(imageio.imread(p)) for p in image_paths]
segmentations = [np.asarray(imageio.imread(_seg_path_for(p))).astype("uint32")
                 for p in image_paths]

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Record which backbone produced the features this classifier was trained on. The forest
# is trained on SAM embeddings, and EVERY backbone emits 256 channels -> a 257-wide feature
# vector either way. So re-using this rf.joblib with a different model_type raises no shape
# error, it just predicts nonsense. WORKFLOW_OBJECT_CLASSIFIER_BATCH.py reads this file and
# refuses the mismatch instead.
with open(os.path.join(OUTPUT_DIR, "classifier_meta.json"), "w") as f:
    json.dump({"model_type": MODEL_TYPE, "ndim": 2, "seg_suffix": SEG_SUFFIX}, f, indent=2)

print(f"micro_sam object classifier: {len(images)} images, model={MODEL_TYPE}, device={device}")
print("Annotate classes on image 1 -> 'Train and predict' -> 'Next Image [N]'.")
print("Images 2..N are classified automatically; correct and re-train as needed.")

# Blocks on napari.run() until the user closes the viewer.
image_series_object_classifier(
    images=images,
    segmentations=segmentations,
    output_folder=OUTPUT_DIR,
    model_type=MODEL_TYPE,
    device=device,
    ndim=2,
)

print(f"Done. Predictions, features/labels and rf.joblib are in {OUTPUT_DIR}")

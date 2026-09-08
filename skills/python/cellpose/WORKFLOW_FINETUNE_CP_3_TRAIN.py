# imagentj-env: cellpose4
"""Stage 3 (Cellpose): train cpsam on the user's annotated tiles, then MEASURE whether it helped.

This is the Cellpose twin of `skills/napari/micro_sam/WORKFLOW_FINETUNE_3_TRAIN.py` and reads
the SAME `manifest.json`. Stages 1 and 2 are shared: the user picks tiles in the napari picker
(`SEGMENT_BACKEND="cellpose"` makes it show what Cellpose currently gets wrong) and corrects
them in the SAM-assisted annotator. SAM is the annotation ASSISTANT there — clicking an object
and pressing S/C is far faster than painting it — but what gets trained here is Cellpose.

Only stages 3 and 4 are Cellpose-specific, because only they need the `cellpose4` env: it has
cellpose and torch but NO napari, NO skimage, NO elf and NO imageio. That is also why the mSA
metric below is implemented here in numpy/scipy instead of imported from elf — the numbers are
computed to elf's definition so they are directly comparable to a micro_sam run on the same
tiles.

WHAT IT DOES
    1. Validate the annotations (Cellpose's own `min_train_masks=5` is stricter than
       micro_sam's 2 — a tile with fewer is DROPPED BY CELLPOSE SILENTLY, so it is rejected
       here with a reason instead).
    2. Split by SOURCE IMAGE, never by tile: two tiles from one field share illumination,
       focus and cell population, so a tile-level split scores the model on what it has
       effectively already seen and reports a gain that does not exist.
    3. Fine-tune with `cellpose.train.train_seg`.
    4. Segment the held-out tiles with the STOCK model and with the fine-tuned one, score both,
       and write the winner into `evaluation.json`. Stage 4 reads that and uses whichever won.

    The measurement is the point. Fine-tuning frequently does NOT help — on annotations that
    merely reproduce what the stock model already does, it cannot. Reporting a fine-tuned model
    that was never shown to be better is the failure mode this stage exists to prevent.

RUN IT
    Set TASK_DIR to the folder stage 1 created, then run as a python_data_analyst script.
    GPU strongly recommended.
"""
import os
import sys
import json
import glob
import time
import shutil

# ------------------------------------------------------------------ CONFIG (edit these)
TASK_DIR = "/app/data/projects/<project>/cellpose_finetune"

CP_MODEL = "auto"       # WHICH cellpose model to fine-tune. "auto" = the model stage 1 showed
                        # the user (recorded in the manifest as `cp_model`), falling back to
                        # "cpsam". Leave it on "auto" unless you deliberately want to train a
                        # DIFFERENT model from the one whose mistakes the user corrected —
                        # that throws away the active-learning property of the whole workflow.
                        # Explicitly, any of:
                        #   "cpsam"                     -> cellpose 4 (env cellpose4)
                        #   "nuclei", "cyto3", "cyto2", "livecell_cp3", "tissuenet_cp3",
                        #   "bact_phase_cp3", "deepbacs_cp3", ...  -> cellpose 3 (env cellpose)
                        # The script RE-EXECS into the right env by itself — cellpose 4 ships
                        # ONLY cpsam, and the v3 zoo exists only in the v3 env. Pick the model
                        # that is already closest on this data; fine-tuning amplifies a good
                        # starting point, it does not rescue a wrong one.
PRETRAINED = None       # None = start from CP_MODEL's stock weights, or a PATH to a previously
                        # fine-tuned file to CONTINUE from. Round 2+ is picked up automatically
                        # from the manifest's `base_checkpoint`; set this only to override it.
CHANNELS = [0, 0]       # v3 ONLY (ignored by cpsam). [cytoplasm, nucleus], 0=grayscale,
                        # 1=red, 2=green, 3=blue. [0,0] = treat the image as grayscale, which is
                        # right for brightfield and for a single fluorescence channel. For a
                        # two-channel stain use e.g. [2,3] (green cyto, blue nuclei).
DIAMETER = None         # v3 ONLY. None = MEASURED from the user's annotations and then used for
                        # BOTH models in the comparison, which is the only fair way to score
                        # them — on a v3 model diameter is the single biggest accuracy lever, so
                        # giving the two models different diameters measures the diameter, not
                        # the fine-tuning.
RUN_NAME = "finetuned"
# Hyperparameters are PER VERSION and are not interchangeable: v3's learning rate is 500x v4's
# and would destroy cpsam, while v4's would barely move a v3 net. None = use the version default
# chosen below.
N_EPOCHS = None         # None -> 100 (v4) / 300 (v3). v3's library default of 2000 is for
                        # training from scratch on a large corpus, not for fine-tuning 10 tiles.
LEARNING_RATE = None    # None -> 1e-5 (v4) / 5e-4 (v3). NOT v3's library default of 0.005:
                        # that is a from-scratch rate and it DESTROYS a v3 model that is
                        # already good on the data (measured: 0.717 -> 0.000).
WEIGHT_DECAY = None     # None -> 0.1  (v4) / 1e-5  (v3)
BATCH_SIZE = None       # None -> 1    (v4) / 8     (v3)
BSIZE = None            # None -> 256  (v4) / 224   (v3). The TRAINING CROP taken from each tile.
MIN_TRAIN_MASKS = 0     # Minimum annotated objects for a tile to be TRAINED ON. This is a
                        # `train_seg` PARAMETER (cellpose's own default is 5), not a constant —
                        # and 5 throws away the user's work. A tile holding 2 carefully
                        # outlined cells is real data, and a tile the user CLEARED because it
                        # held nothing but debris is the most explicit negative example they
                        # can give: "none of this is a cell". At 0 both are kept; cellpose only
                        # prints "removing from train set" above 0. Raise it only if the run is
                        # dominated by near-empty tiles (see the EMPTY warning in the output).
VAL_FRACTION = 0.25     # share of SOURCE IMAGES held out for the measurement
SEED = 0
KEEP_RAW_CHECKPOINTS = False
# ---------------------------------------------------------------------------------------

# Cellpose prints a tqdm bar for the 1.15 GB model download and for every train/eval pass.
# `execute_script` hands ALL of stdout back to the agent, where several thousand progress lines
# are worse than useless — they push the actual result out of context. Disable before importing
# cellpose; the timings and the result table below carry the information a reader needs.
os.environ.setdefault("TQDM_DISABLE", "1")


# ------------------------------------------------------------------ model <-> env registry
# cellpose 4.1.1 ships EXACTLY ONE model: `cpsam` (MODEL_NAMES == ['cpsam']). The whole v3 zoo
# — nuclei, cyto3, cyto2, livecell, tissuenet, the bacteria and yeast models — exists only in
# the `cellpose` env (3.1.1.2). So "fine-tune nuclei instead" is not a config change, it is a
# different interpreter, a different network and a different set of hyperparameters. This block
# is duplicated in all three CP scripts on purpose: `skills/` is a read-only bind mount and the
# agent copies ONE script into the project, so a shared-module import would break at runtime.
V4_PYTHON = "/opt/conda/envs/cellpose4/bin/python"
V3_PYTHON = "/opt/conda/envs/cellpose/bin/python"
V4_MODELS = ("cpsam",)
V3_MODELS = (
    "cyto3", "nuclei", "cyto2_cp3", "tissuenet_cp3", "livecell_cp3", "yeast_PhC_cp3",
    "yeast_BF_cp3", "bact_phase_cp3", "bact_fluor_cp3", "deepbacs_cp3", "cyto2", "cyto",
    "CPx", "transformer_cp3", "neurips_cellpose_default", "neurips_cellpose_transformer",
    "neurips_grayscale_cyto2", "CP", "TN1", "TN2", "TN3", "LC1", "LC2", "LC3", "LC4",
)


def model_major(model):
    """4 for cpsam, 3 for a zoo model, and 3 for a PATH that came out of a v3 run.

    A fine-tuned file carries no version marker, so a bare path is ambiguous. The convention
    here: a path is v3 unless it sits next to a `cpsam` marker or the caller says otherwise via
    CP_MODEL. Loading a cpsam file through v3 (or the reverse) raises a state_dict KEY MISMATCH,
    not a readable "wrong model type" — see the cellpose skill.
    """
    if model in V4_MODELS:
        return 4
    if model in V3_MODELS:
        return 3
    return 4 if "cpsam" in os.path.basename(str(model)).lower() else 3


def ensure_right_env(model, script_name):
    """Re-exec into the interpreter that HAS this model, or explain why we cannot.

    The `# imagentj-env:` header picks the starting env; this hops if the requested model lives
    in the other one. Only when run as a script — an imported module must not have its process
    replaced under the caller.
    """
    want = V4_PYTHON if model_major(model) == 4 else V3_PYTHON
    if os.path.realpath(sys.executable) == os.path.realpath(want):
        return
    running_as_script = os.path.basename(sys.argv[0] or "") == script_name
    where = "cellpose4" if want is V4_PYTHON else "cellpose"
    if not running_as_script:
        raise SystemExit(
            f"{model!r} needs the `{where}` env, but this module was imported under "
            f"{sys.executable}. Run the script directly, or set the `# imagentj-env:` header "
            f"to `{where}`.")
    if not os.path.exists(want):
        raise SystemExit(f"{model!r} needs {want}, which does not exist in this image.")
    print(f"[cp] {model!r} lives in cellpose v{model_major(model)} -> re-running under {where}",
          flush=True)
    os.execv(want, [want] + sys.argv)


MSA_THRESHOLDS = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))   # 0.50 .. 0.95, as elf


def ensure_model_cache(fallback_dir):
    """Guarantee a writable cellpose model cache, the way stage 3 does for micro_sam.

    `~/.cellpose` is inside a NAMED VOLUME. On a deployment whose volume predates the image's
    model bake, that directory survives as an empty ROOT-OWNED folder while this process runs
    as `imagentj`, and every model load dies with a PermissionError from deep inside cellpose's
    downloader — a traceback that never mentions the volume. Probe it for real (mkdir + write,
    not a permission bit) and fall back to somewhere writable by construction.
    """
    import errno

    cache = os.environ.get("CELLPOSE_LOCAL_MODELS_PATH") or os.path.expanduser("~/.cellpose/models")
    probe = os.path.join(cache, ".writable")
    try:
        os.makedirs(cache, exist_ok=True)
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return cache
    except OSError as exc:
        why = exc.strerror or str(exc)
        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOSPC):
            raise
    os.makedirs(fallback_dir, exist_ok=True)
    os.environ["CELLPOSE_LOCAL_MODELS_PATH"] = fallback_dir
    print(f"[cp-train] model cache {cache} is not writable ({why}) -> using {fallback_dir}",
          flush=True)
    for seed in (cache, "/home/imagentj.seed/.cellpose/models"):
        if os.path.isdir(seed):
            for f in glob.glob(os.path.join(seed, "*")):
                dst = os.path.join(fallback_dir, os.path.basename(f))
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(f, dst)
                    except OSError:
                        pass
    return fallback_dir


# --------------------------------------------------------------------------- measurement


def iou_matrix(true, pred):
    """Object-wise IoU, background excluded. One bincount, no Python loop over objects.

    Both label images are DENSIFIED with np.unique first, and that is not a tidiness detail —
    it is required twice over. Hand-edited masks arrive with holes in the id sequence (delete
    object 7 of 30), and indexing a matrix by raw label VALUE turns each hole into a phantom
    object with zero area: unmatchable, so it counts as a false negative and silently deflates
    the score. Verified against elf on real annotations — the naive version disagreed by up to
    0.85 mSA. Densifying also bounds the histogram by the OBJECT count instead of the largest
    id, so a uint16 mask with ids near 65535 no longer tries to allocate a 65536x65536 matrix.
    """
    import numpy as np

    ids_t, idx_t = np.unique(np.asarray(true), return_inverse=True)
    ids_p, idx_p = np.unique(np.asarray(pred), return_inverse=True)
    hist = np.bincount(idx_t.ravel() * len(ids_p) + idx_p.ravel(),
                       minlength=len(ids_t) * len(ids_p)).reshape(len(ids_t), len(ids_p))
    area_t = hist.sum(axis=1)
    area_p = hist.sum(axis=0)

    keep_t = np.nonzero(ids_t != 0)[0]        # background is a label value of 0, not a row index
    keep_p = np.nonzero(ids_p != 0)[0]
    if len(keep_t) == 0 or len(keep_p) == 0:
        return np.zeros((len(keep_t), len(keep_p)), dtype=float)

    inter = hist[np.ix_(keep_t, keep_p)]
    union = area_t[keep_t][:, None] + area_p[keep_p][None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(union > 0, inter / union, 0.0)


def mean_segmentation_accuracy(pred, true):
    """elf's mSA: mean over IoU thresholds 0.50..0.95 of TP / (TP + FP + FN).

    Implemented here because `elf` is not in the cellpose4 env. Matching is optimal
    (linear_sum_assignment), the same as elf — greedy matching inflates the score.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    iou = iou_matrix(true, pred)
    if iou.size == 0:
        return 0.0, 0.0
    rows, cols = linear_sum_assignment(-iou)
    matched = iou[rows, cols]
    scores = []
    for th in MSA_THRESHOLDS:
        tp = int((matched >= th).sum())
        fp, fn = iou.shape[1] - tp, iou.shape[0] - tp
        scores.append(tp / (tp + fp + fn) if (tp + fp + fn) else 0.0)
    sa50 = scores[0]
    return float(sum(scores) / len(scores)), float(sa50)


# ----------------------------------------------------------------------------- pipeline


def version_defaults(major):
    """The v3 and v4 recipes, which are NOT interchangeable."""
    if major == 4:
        return dict(n_epochs=100, lr=1e-5, weight_decay=0.1, batch_size=1, bsize=256)
    # lr is 5e-4, NOT cellpose v3's library default of 0.005. That default is for training
    # from scratch on a large corpus; applied to FINE-TUNING a model that is already good on
    # the data, it destroys it. Measured on a fluorescence nuclei set where stock `nuclei`
    # already scored mSA 0.717: lr 0.005 -> 0.000 (the network collapses), lr 5e-4 -> 0.948,
    # lr 1e-4 -> 0.942. The promotion gate refuses the collapsed model, so nothing broken ever
    # ships — but the user has already spent their annotation time and is told "fine-tuning did
    # not help", which is a FALSE NEGATIVE caused by the hyperparameter, not by their labels.
    # The cost is small where the base model is useless: on CD177 brightfield (stock 0.020)
    # lr 0.005 reached 0.744 and lr 5e-4 reaches 0.661 — still a 33x gain.
    return dict(n_epochs=300, lr=5e-4, weight_decay=1e-5, batch_size=8, bsize=224)


def open_model(model, gpu, major):
    """Load a zoo NAME or a fine-tuned PATH, on either version."""
    from cellpose import models

    is_path = os.path.sep in str(model) or str(model).endswith(".pt")
    if major == 4:
        return models.CellposeModel(gpu=gpu, pretrained_model=str(model))
    if is_path:
        return models.CellposeModel(gpu=gpu, pretrained_model=str(model))
    return models.CellposeModel(gpu=gpu, model_type=str(model))


def measure_diameter(label_images):
    """Median equivalent-circle diameter of the user's annotated objects, in pixels.

    v3 rescales every image by `diameter / diam_mean` before the network sees it, which makes
    diameter the single biggest accuracy lever on a v3 model. Measuring it from the annotations
    and then using the SAME number for both models in the comparison is the only fair way to
    score them: give the two models different diameters and the experiment measures the
    diameter, not the fine-tuning. Ignored by cpsam, which does not rescale.
    """
    import numpy as np

    diams = []
    for lab in label_images:
        ids, counts = np.unique(lab, return_counts=True)
        for i, c in zip(ids, counts):
            if i != 0:
                diams.append(2.0 * float(np.sqrt(c / np.pi)))
    return float(np.median(diams)) if diams else 30.0


def resolve_cp_model(task_dir=None):
    """The model to fine-tune: the explicit CP_MODEL, else the one stage 1 put the user in
    front of. Reading it from the manifest is what keeps "the model the user corrected" and
    "the model we train" the same object — they used to be two independent settings that a
    caller had to keep in sync by hand, and nothing detected it when they drifted."""
    if CP_MODEL and CP_MODEL != "auto":
        return CP_MODEL
    try:
        with open(os.path.join(task_dir or TASK_DIR, "manifest.json")) as f:
            return json.load(f).get("cp_model") or "cpsam"
    except Exception:
        return "cpsam"


def load_manifest():
    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        return json.load(f)


def validate(manifest):
    """Reject anything that would train a broken model, with the reason spelled out."""
    import numpy as np
    import tifffile

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
        n = int(len(np.unique(lab)) - (1 if 0 in lab else 0))
        # An EMPTY annotation is not a missing one. The file exists, so the user opened this
        # tile and pressed N on it — micro_sam even makes them confirm "Nothing is segmented
        # yet". On a field of pure debris that is the correct answer and a deliberate NEGATIVE
        # example. Calling it "not annotated" and dropping it silently discards exactly the
        # signal that teaches the model debris is not a cell.
        if n == 0:
            if MIN_TRAIN_MASKS == 0:
                usable.append(dict(e, n_objects=0))
            else:
                problems.append(f"{name}: cleared to EMPTY by the user (debris-only field). That "
                                f"is a negative example, not a missing annotation — set "
                                f"MIN_TRAIN_MASKS=0 to train on it. Excluded at "
                                f"{MIN_TRAIN_MASKS}.")
            continue
        if n < MIN_TRAIN_MASKS:
            problems.append(f"{name}: only {n} object(s), below MIN_TRAIN_MASKS="
                            f"{MIN_TRAIN_MASKS} — excluded, and cellpose would have dropped it "
                            f"silently anyway. These are real annotations; lower the setting to "
                            f"keep them.")
            continue
        usable.append(dict(e, n_objects=n))
    return usable, problems


def split_by_source(entries, val_fraction, seed):
    """Hold out whole SOURCE IMAGES. Two tiles from one field are not independent samples."""
    import random

    by_src = {}
    for e in entries:
        by_src.setdefault(e.get("source", e["name"]), []).append(e)
    sources = sorted(by_src)
    rng = random.Random(seed)
    rng.shuffle(sources)
    n_val = max(1, int(round(len(sources) * val_fraction)))
    if len(sources) - n_val < 1:
        n_val = len(sources) - 1
    val_src, train_src = set(sources[:n_val]), set(sources[n_val:])
    train = [e for s in train_src for e in by_src[s]]
    val = [e for s in val_src for e in by_src[s]]
    return train, val, sorted(train_src), sorted(val_src)


def segment_all(pretrained, entries, gpu, major, diameter=None, channels=None):
    """Segment the held-out tiles with one model. Returns a list of label arrays."""
    import numpy as np
    import tifffile

    model = open_model(pretrained, gpu, major)
    kw = {} if major == 4 else dict(diameter=diameter, channels=channels)
    out = []
    for e in entries:
        masks, _f, _s = model.eval(tifffile.imread(e["tile_path"]), normalize=True, **kw)
        out.append(np.asarray(masks))
    del model
    return out


def score(preds, entries):
    import tifffile

    rows = []
    for pred, e in zip(preds, entries):
        true = tifffile.imread(e["annotation_path"])
        msa, sa50 = mean_segmentation_accuracy(pred, true)
        rows.append({"tile": e["name"], "msa": msa, "sa50": sa50,
                     "n_true": int(true.max()), "n_pred": int(pred.max())})
    return rows


def main():
    import numpy as np
    import tifffile
    import torch
    from cellpose import models, train as cp_train

    t0 = time.time()
    ensure_model_cache(os.path.join(TASK_DIR, ".cellpose_cache"))
    manifest = load_manifest()
    gpu = torch.cuda.is_available()
    cp_model = resolve_cp_model()
    major = model_major(cp_model)
    D = version_defaults(major)
    n_epochs = N_EPOCHS if N_EPOCHS is not None else D["n_epochs"]
    lr = LEARNING_RATE if LEARNING_RATE is not None else D["lr"]
    wd = WEIGHT_DECAY if WEIGHT_DECAY is not None else D["weight_decay"]
    bs = BATCH_SIZE if BATCH_SIZE is not None else D["batch_size"]
    bsize = BSIZE if BSIZE is not None else D["bsize"]

    backend = manifest.get("segment_backend", "micro_sam")
    if backend != "cellpose":
        print(f"[cp-train] NOTE: this task folder was prepared for the '{backend}' backend, so "
              f"the\n           pre-segmentations the user corrected came from that model, not "
              f"from Cellpose.\n           The ANNOTATIONS are model-agnostic, so training on "
              f"them is valid — but the\n           user was shown a different model's mistakes. "
              f"Prefer SEGMENT_BACKEND='cellpose'\n           in stage 1 when the goal is a "
              f"Cellpose model.")

    # Round 2+: continue from, and MEASURE AGAINST, the model the user actually corrected.
    base = PRETRAINED or manifest.get("base_checkpoint")
    if base and not os.path.exists(base):
        raise SystemExit(f"base checkpoint is gone: {base}")
    start_from = base or cp_model
    baseline_name = "previous round" if base else f"stock {cp_model}"

    usable, problems = validate(manifest)
    print("=" * 72)
    n_empty = sum(1 for e in usable if e["n_objects"] == 0)
    print(f"ANNOTATIONS: {len(usable)} of {manifest['n_tiles']} tiles usable, "
          f"{sum(e['n_objects'] for e in usable)} objects"
          + (f" ({n_empty} of them deliberately EMPTY — debris-only fields, kept as negative "
             f"examples)" if n_empty else ""))
    if usable and n_empty / len(usable) > 0.4:
        print(f"  !! {n_empty} of {len(usable)} tiles are empty. Training mostly on empty fields "
              f"teaches the model to predict nothing.\n"
              f"     Pick denser tiles, or raise MIN_TRAIN_MASKS to exclude them.")
    for p in problems:
        print(f"  - {p}")
    if len(usable) < 3:
        raise SystemExit(
            f"Only {len(usable)} usable tile(s). Re-run stage 2 and annotate more before "
            f"training — with fewer than 3 there is nothing to hold out and no way to tell "
            f"whether training helped.")

    train_e, val_e, train_src, val_src = split_by_source(usable, VAL_FRACTION, SEED)
    print(f"SPLIT: {len(train_e)} train tile(s) from {len(train_src)} source image(s); "
          f"{len(val_e)} held-out tile(s) from {len(val_src)}")
    if not val_e:
        raise SystemExit("No held-out tiles — cannot measure. Annotate tiles from more than "
                         "one source image.")

    train_data = [tifffile.imread(e["tile_path"]) for e in train_e]
    train_labels = [tifffile.imread(e["annotation_path"]) for e in train_e]
    val_data = [tifffile.imread(e["tile_path"]) for e in val_e]
    val_labels = [tifffile.imread(e["annotation_path"]) for e in val_e]

    diameter = None
    if major == 3:
        diameter = DIAMETER if DIAMETER is not None else measure_diameter(train_labels)
        print(f"DIAMETER: {diameter:.1f} px "
              f"({'from the config' if DIAMETER is not None else 'measured from the annotations'})"
              f" — used for BOTH models in the comparison")

    print("-" * 72)
    print(f"TRAINING cellpose v{major} {cp_model} from {start_from} on "
          f"{'GPU' if gpu else 'CPU'}  |  {n_epochs} epochs  |  lr={lr}  wd={wd}  "
          f"bsize={bsize}  batch_size={bs}")
    if not gpu:
        print("  !! No GPU. This will take hours for a run that takes minutes on one.")

    save_path = os.path.join(TASK_DIR, "training")
    os.makedirs(save_path, exist_ok=True)
    model = open_model(start_from, gpu, major)
    extra = {} if major == 4 else dict(channels=CHANNELS, rescale=True)
    ckpt, train_losses, test_losses = cp_train.train_seg(
        model.net,
        train_data=train_data, train_labels=train_labels,
        test_data=val_data, test_labels=val_labels,
        n_epochs=n_epochs, learning_rate=lr, weight_decay=wd,
        batch_size=bs, bsize=bsize, min_train_masks=MIN_TRAIN_MASKS,
        save_path=save_path, model_name=RUN_NAME,
        normalize=True, **extra,
    )
    ckpt = str(ckpt)
    # v3 writes the mean training-object diameter into the net. That is the number inference
    # must use afterwards — a fine-tuned v3 model applied at the WRONG diameter can score worse
    # than the stock model it came from, which reads as "fine-tuning failed".
    diam_labels = float(getattr(model.net, "diam_labels", diameter or 30.0)) if major == 3 else None
    print(f"  trained checkpoint: {ckpt}"
          + (f"   (learned diameter {diam_labels:.1f} px)" if diam_labels else ""))
    del model
    if gpu:
        torch.cuda.empty_cache()

    # --- measure: the whole point of this stage ---------------------------------
    print("-" * 72)
    print(f"EVALUATING the {baseline_name} and the fine-tuned model on "
          f"{len(val_e)} held-out tile(s) ...")
    rows_b = score(segment_all(start_from, val_e, gpu, major, diameter, CHANNELS), val_e)
    rows_a = score(segment_all(ckpt, val_e, gpu, major, diameter, CHANNELS), val_e)

    print(f"{'tile':<14}{'objects':>8} | {baseline_name:>16} {'':>8}{'':>5} | {'fine-tuned':>12}")
    print(f"{'':<14}{'(yours)':>8} | {'mSA':>16}{'SA50':>8}{'n':>5} | {'mSA':>12}{'SA50':>8}{'n':>5}")
    for b, a in zip(rows_b, rows_a):
        print(f"{b['tile']:<14}{b['n_true']:>8} | {b['msa']:>16.3f}{b['sa50']:>8.3f}{b['n_pred']:>5} | "
              f"{a['msa']:>12.3f}{a['sa50']:>8.3f}{a['n_pred']:>5}")
    msa_b = float(np.mean([r["msa"] for r in rows_b]))
    msa_a = float(np.mean([r["msa"] for r in rows_a]))
    sa_b = float(np.mean([r["sa50"] for r in rows_b]))
    sa_a = float(np.mean([r["sa50"] for r in rows_a]))
    print("-" * 72)
    print(f"{'MEAN':<14}{'':>8} | {msa_b:>16.3f}{sa_b:>8.3f}{'':>5} | {msa_a:>12.3f}{sa_a:>8.3f}")

    improved = msa_a > msa_b
    delta = msa_a - msa_b
    model_dir = os.path.join(TASK_DIR, "model")
    os.makedirs(model_dir, exist_ok=True)
    exported = os.path.join(model_dir, f"{RUN_NAME}_{cp_model}.pt")
    shutil.copy2(ckpt, exported)
    # Losing means "keep what we had" — on round 2 that is the PREVIOUS checkpoint, not stock.
    winner = exported if improved else base

    print("-" * 72)
    if improved:
        # A baseline of exactly 0 (the stock model finds nothing at all) has no percentage —
        # printing "+nan %" in the headline result reads like a crash.
        rel = (f"{100 * delta / msa_b:+.1f} %" if msa_b > 0
               else "up from a baseline that found nothing")
        print(f"RESULT: the fine-tuned model WINS.  mSA {msa_b:.3f} -> {msa_a:.3f} "
              f"({delta:+.3f}, {rel}).  Stage 4 will use it.")
    else:
        print(f"RESULT: fine-tuning did NOT help — {msa_a:.3f} against the "
              f"{baseline_name}'s {msa_b:.3f} ({delta:+.3f}).\n"
              f"        Stage 4 will keep the "
              f"{'previous round`s model' if base else 'STOCK ' + cp_model}. Tell the user plainly.\n"
              f"        Most likely causes, in order:\n"
              f"        1. The annotations reproduce what the stock model already does — there\n"
              f"           is nothing to learn. Look at the per-tile table above.\n"
              f"        2. Too few objects: cellpose needs {MIN_TRAIN_MASKS}+ per tile and this\n"
              f"           run had {sum(e['n_objects'] for e in train_e)} across "
              f"{len(train_e)} training tile(s).\n"
              f"        3. The held-out tiles are unrepresentative — only "
              f"{len(val_src)} source image(s).")

    if not KEEP_RAW_CHECKPOINTS:
        for stale in glob.glob(os.path.join(save_path, "models", "*")):
            if os.path.abspath(stale) != os.path.abspath(ckpt):
                try:
                    os.remove(stale)
                except OSError:
                    pass

    out = {
        "backend": "cellpose", "run_name": RUN_NAME, "model": cp_model,
        "cellpose_major": major, "channels": CHANNELS if major == 3 else None,
        # stage 4 MUST use these: a v3 model at the wrong diameter scores worse than stock.
        "diameter": diameter, "diam_labels": diam_labels,
        "base_checkpoint": base, "baseline": baseline_name,
        "gpu": bool(gpu), "n_epochs": n_epochs, "lr": lr, "bsize": bsize,
        "train_tiles": [e["name"] for e in train_e], "val_tiles": [e["name"] for e in val_e],
        "train_sources": train_src, "val_sources": val_src,
        "n_train_objects": sum(e["n_objects"] for e in train_e),
        "before": {"msa": msa_b, "sa50": sa_b, "per_tile": rows_b},
        "after": {"msa": msa_a, "sa50": sa_a, "per_tile": rows_a},
        "improved": bool(improved), "delta_msa": delta,
        "checkpoint": exported,
        # stage 4 reads exactly this: None means "the baseline won, do not load a checkpoint"
        "recommended_checkpoint": winner,
        "minutes": round((time.time() - t0) / 60, 1),
    }
    with open(os.path.join(TASK_DIR, "evaluation.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {os.path.join(TASK_DIR, 'evaluation.json')}  ({out['minutes']} min)")


if __name__ == "__main__":
    ensure_right_env(resolve_cp_model(), "WORKFLOW_FINETUNE_CP_3_TRAIN.py")
    main()

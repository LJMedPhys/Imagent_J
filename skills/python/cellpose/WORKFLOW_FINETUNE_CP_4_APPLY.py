# imagentj-env: cellpose4
"""Stage 4 (Cellpose): segment the whole folder with whichever model stage 3 measured as better.

The Cellpose twin of `skills/napari/micro_sam/WORKFLOW_FINETUNE_4_APPLY.py`. It reads
`evaluation.json` and uses `recommended_checkpoint`:

    a path  -> the fine-tuned model won on the held-out tiles
    null    -> it did NOT, and the baseline (stock cpsam, or the previous round's model) is used

Do not override that by hand. The whole point of stage 3 is that "we fine-tuned it" is not the
same claim as "it got better", and this stage is where the distinction becomes a result the
user acts on. If you want the fine-tuned model regardless, set USE_MODEL="finetuned" and say so
in the report — do not quietly pass a checkpoint that lost.

Writes one label TIFF per input image plus a per-image object-count CSV.
"""
import os
import sys
import csv
import json
import glob
import time

# ------------------------------------------------------------------ CONFIG (edit these)
TASK_DIR = "/app/data/projects/<project>/cellpose_finetune"
INPUT_DIR = None        # None = the INPUT_DIR recorded in the manifest (the folder the tiles
                        # were cut from). Set it to segment a different folder with this model.
OUTPUT_DIR = None       # None = <TASK_DIR>/segmentation

USE_MODEL = "auto"      # "auto"      -> whatever stage 3 measured as better (RECOMMENDED)
                        # "finetuned" -> force the fine-tuned checkpoint even if it lost
                        # "stock"     -> force the stock cpsam
DIAMETER = None         # v3 ONLY. None = the diameter stage 3 recorded, which is what the model
                        # was trained at. Overriding it is the fastest way to make a good
                        # fine-tuned v3 model look broken. cpsam ignores it entirely.
FLOW_THRESHOLD = 0.4
CELLPROB_THRESHOLD = 0.0
MIN_SIZE = 15
EXTS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")   # matched CASE-INSENSITIVELY (".TIF" too)
RECURSIVE = False
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


def open_model(model, gpu, major):
    """Load a zoo NAME or a fine-tuned PATH, on either version.

    v3 wants a zoo name in `model_type` and a file in `pretrained_model`; v4 takes either in
    `pretrained_model`. Passing a name as `pretrained_model` on v3 makes cellpose look for a
    FILE by that name and fail with a path error, not a "no such model".
    """
    from cellpose import models

    is_path = os.path.sep in str(model) or str(model).endswith(".pt")
    if major == 4 or is_path:
        return models.CellposeModel(gpu=gpu, pretrained_model=str(model))
    return models.CellposeModel(gpu=gpu, model_type=str(model))


def ensure_model_cache(fallback_dir):
    """See the stage 3 twin: ~/.cellpose can be an empty root-owned directory on a deployment
    whose named volume predates the image's model bake, and the resulting PermissionError comes
    out of cellpose's downloader with no hint that a stale volume is the cause."""
    import errno
    import shutil

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
    print(f"[cp-apply] model cache {cache} is not writable ({why}) -> using {fallback_dir}")
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


def list_images(folder, exts, recursive):
    """Case-INSENSITIVE. A folder of `.TIF` files is common off a microscope and a plain
    glob("*.tif") silently finds nothing, which looks like an empty folder rather than a bug."""
    low = tuple(e.lower() for e in exts)
    out = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            out += [os.path.join(root, f) for f in files
                    if os.path.splitext(f)[1].lower() in low]
    else:
        out = [os.path.join(folder, f) for f in os.listdir(folder)
               if os.path.splitext(f)[1].lower() in low
               and os.path.isfile(os.path.join(folder, f))]
    return sorted(out)


def main():
    import numpy as np
    import tifffile
    import torch
    from cellpose import models

    t0 = time.time()
    ensure_model_cache(os.path.join(TASK_DIR, ".cellpose_cache"))

    with open(os.path.join(TASK_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    ev_path = os.path.join(TASK_DIR, "evaluation.json")
    if not os.path.exists(ev_path):
        raise SystemExit(f"No {ev_path}. Run stage 3 first — this stage applies whichever model "
                         f"stage 3 MEASURED as better, and without that measurement there is no "
                         f"basis for using a fine-tuned model at all.")
    with open(ev_path) as f:
        ev = json.load(f)

    cp_model = ev.get("model", "cpsam")
    major = ev.get("cellpose_major") or model_major(cp_model)
    if USE_MODEL == "auto":
        pretrained = ev.get("recommended_checkpoint")
    elif USE_MODEL == "finetuned":
        pretrained = ev["checkpoint"]
    elif USE_MODEL == "stock":
        pretrained = None
    else:
        raise SystemExit(f"USE_MODEL must be auto/finetuned/stock, got {USE_MODEL!r}")

    # v3 rescales by diameter before the network sees anything, so the diameter must MATCH the
    # model being used: the fine-tuned net learned `diam_labels`, the stock one is scored at the
    # diameter measured from the annotations. Mixing them measures the diameter, not the model.
    diameter = DIAMETER
    if diameter is None and major == 3:
        diameter = ev.get("diam_labels") if pretrained else ev.get("diameter")
    channels = ev.get("channels") or [0, 0]

    if pretrained and not os.path.exists(pretrained):
        raise SystemExit(f"Checkpoint missing: {pretrained}")
    which = "FINE-TUNED" if pretrained else f"STOCK {cp_model}"
    if USE_MODEL == "auto" and not pretrained:
        print(f"[cp-apply] stage 3 measured the fine-tuned model as NO BETTER than the "
              f"{ev.get('baseline', 'baseline')}\n"
              f"           ({ev['after']['msa']:.3f} vs {ev['before']['msa']:.3f} mSA), so this "
              f"run uses the baseline.\n           Say that to the user — it is a result, not a "
              f"failure.")
    elif USE_MODEL == "finetuned" and not ev.get("improved"):
        print(f"[cp-apply] WARNING: USE_MODEL='finetuned' is forcing a checkpoint that stage 3 "
              f"measured as WORSE\n           ({ev['after']['msa']:.3f} vs "
              f"{ev['before']['msa']:.3f} mSA). Report this in the results.")

    in_dir = INPUT_DIR or manifest["input_dir"]
    out_dir = OUTPUT_DIR or os.path.join(TASK_DIR, "segmentation")
    os.makedirs(out_dir, exist_ok=True)
    paths = list_images(in_dir, EXTS, RECURSIVE)
    if not paths:
        raise SystemExit(f"No images in {in_dir} matching {EXTS} (case-insensitive).")

    gpu = torch.cuda.is_available()
    print("=" * 72)
    print(f"MODEL: {which}  (cellpose v{major})"
          + (f"\n       {pretrained}" if pretrained else "")
          + (f"\n       diameter {diameter:.1f} px, channels {channels}" if major == 3 else ""))
    print(f"IMAGES: {len(paths)} from {in_dir}")
    print(f"OUTPUT: {out_dir}   ({'GPU' if gpu else 'CPU'})")
    print("=" * 72)

    model = open_model(pretrained or cp_model, gpu, major)
    v3_kw = {} if major == 4 else dict(diameter=diameter, channels=channels)
    rows, failed = [], []
    for i, p in enumerate(paths, 1):
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            masks, _f, _s = model.eval(
                tifffile.imread(p), flow_threshold=FLOW_THRESHOLD,
                cellprob_threshold=CELLPROB_THRESHOLD, min_size=MIN_SIZE, normalize=True,
                **v3_kw)
            masks = np.asarray(masks)
            masks = masks.astype(np.uint16 if masks.max() < 65535 else np.int32)
            dst = os.path.join(out_dir, f"{name}_labels.tif")
            tifffile.imwrite(dst, masks)
            n = int(masks.max())
            rows.append({"image": os.path.basename(p), "n_objects": n, "labels": dst})
            print(f"  [{i}/{len(paths)}] {os.path.basename(p)[:48]:<48} {n:>5} objects")
        except Exception as exc:      # one unreadable file must not lose the whole folder
            failed.append((os.path.basename(p), f"{type(exc).__name__}: {exc}"))
            print(f"  [{i}/{len(paths)}] {os.path.basename(p)[:48]:<48} FAILED: {exc}")

    csv_path = os.path.join(TASK_DIR, "object_counts.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["image", "n_objects", "labels"])
        w.writeheader()
        w.writerows(rows)

    total = sum(r["n_objects"] for r in rows)
    print("-" * 72)
    print(f"{len(rows)} image(s) segmented, {total} objects total "
          f"(median {sorted(r['n_objects'] for r in rows)[len(rows) // 2] if rows else 0} per image)")
    if failed:
        print(f"{len(failed)} FAILED:")
        for n, why in failed:
            print(f"  - {n}: {why}")
    print(f"Counts: {csv_path}   ({(time.time() - t0) / 60:.1f} min)")


def _model_from_evaluation():
    """The env hop has to happen BEFORE cellpose is imported, and which env we need is recorded
    in evaluation.json rather than configured here — stage 4 uses whatever stage 3 trained."""
    try:
        with open(os.path.join(TASK_DIR, "evaluation.json")) as f:
            return json.load(f).get("model", "cpsam")
    except Exception:
        return "cpsam"


if __name__ == "__main__":
    ensure_right_env(_model_from_evaluation(), "WORKFLOW_FINETUNE_CP_4_APPLY.py")
    main()

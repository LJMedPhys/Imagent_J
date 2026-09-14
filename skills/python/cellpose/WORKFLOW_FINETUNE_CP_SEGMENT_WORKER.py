# imagentj-env: cellpose4
"""Segment a batch of images with Cellpose and write label TIFFs. Called as a SUBPROCESS.

WHY THIS EXISTS
---------------
cellpose and napari cannot share an interpreter in this container: `napari-mcp` has napari,
micro_sam and skimage but NO cellpose; `cellpose4` has cellpose and torch but NO napari, NO
skimage and NO imageio. The fine-tuning tile picker must run where napari is, and it wants to
show the user what CELLPOSE currently gets wrong — so the segmentation crosses the env boundary
as a subprocess over TIFF files on disk.

Batch, never per image: loading cpsam costs ~10 s, so a per-image process makes the picker
unusable. One call segments a whole list.

    # batch: segment a list, then exit
    /opt/conda/envs/cellpose4/bin/python WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py job.json

    # serve: load the model ONCE, then take one job per stdin line
    /opt/conda/envs/cellpose4/bin/python WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py --serve setup.json

job.json:
    {"pretrained_model": "cpsam" | "/path/to/finetuned.pt",
     "diameter": null | float,          # null = cpsam's own scale (v4 does not rescale)
     "flow_threshold": 0.4, "cellprob_threshold": 0.0, "min_size": 15,
     "pairs": [["/in/a.tif", "/out/a.tif"], ...]}

Serve mode exists for the interactive tile picker. Loading cpsam costs ~10 s; the picker
segments a new field every time the user asks for one, so a fresh process per field would make
it unusable. `--serve` takes the same JSON minus `pairs`, then reads one {"pairs": [...]} per
line from stdin and answers with one summary line per job.

Prints one JSON line per finished pair so the caller can report progress, then a final summary
line. Every failure is reported per-pair rather than taking the whole batch down: one unreadable
tile must not cost the user the picker session.
"""
import json
import sys
import os


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
    """Load a zoo NAME or a fine-tuned PATH, on either version."""
    from cellpose import models

    is_path = os.path.sep in str(model) or str(model).endswith(".pt")
    if major == 4 or is_path:
        return models.CellposeModel(gpu=gpu, pretrained_model=str(model))
    return models.CellposeModel(gpu=gpu, model_type=str(model))


def _run_pairs(model, job, pairs):
    import numpy as np
    import tifffile

    ok = 0
    for src, dst in pairs:
        try:
            img = tifffile.imread(src)
            masks, _flows, _styles = model.eval(
                img,
                **({} if job.get("major", 4) == 4 else
                   dict(diameter=job.get("diameter"), channels=job.get("channels") or [0, 0])),
                flow_threshold=job.get("flow_threshold", 0.4),
                cellprob_threshold=job.get("cellprob_threshold", 0.0),
                min_size=job.get("min_size", 15),
                normalize=True,
            )
            masks = np.asarray(masks)
            masks = masks.astype(np.uint16 if masks.max() < 65535 else np.int32)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            tifffile.imwrite(dst, masks)
            ok += 1
            print(json.dumps({"event": "done", "src": src, "dst": dst,
                              "n_objects": int(masks.max())}), flush=True)
        except Exception as exc:                       # one bad tile must not kill the batch
            print(json.dumps({"event": "error", "src": src,
                              "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    print(json.dumps({"event": "summary", "ok": ok, "total": len(pairs)}), flush=True)
    return ok


def main() -> int:
    serve = sys.argv[1] == "--serve"
    with open(sys.argv[2 if serve else 1]) as f:
        job = json.load(f)

    pretrained = job.get("pretrained_model") or "cpsam"
    ensure_right_env(pretrained, "WORKFLOW_FINETUNE_CP_SEGMENT_WORKER.py")

    import torch

    gpu = torch.cuda.is_available()
    major = job.get("major") or model_major(pretrained)
    # A zoo NAME goes in `model_type` on v3 and a PATH in `pretrained_model`; v4 takes either in
    # `pretrained_model`. A fine-tuned file only loads under the version that produced it — the
    # state dict keys differ and the error is a key mismatch, not "wrong model type".
    model = open_model(pretrained, gpu, major)
    print(json.dumps({"event": "model_ready", "pretrained": pretrained, "major": major,
                      "gpu": bool(gpu)}), flush=True)

    if not serve:
        return 0 if _run_pairs(model, job, job["pairs"]) else 1

    # Serve: one job per stdin line, model stays loaded. EOF (the caller closing the pipe) is
    # the shutdown signal — the picker exits without ceremony and must not leave this hanging.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:
            print(json.dumps({"event": "summary", "ok": 0, "total": 0,
                              "error": f"bad request: {exc}"}), flush=True)
            continue
        _run_pairs(model, {**job, **req}, req.get("pairs", []))
    return 0


if __name__ == "__main__":
    sys.exit(main())

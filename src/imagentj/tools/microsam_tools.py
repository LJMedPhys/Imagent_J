"""micro-sam segmentation tool for ImagentJ.

Runs micro_sam.automatic_segmentation headlessly inside the napari-mcp conda
env (which has micro_sam + PyTorch installed). No napari viewer is opened —
this is a pure file-in / file-out operation. Use the napari MCP tools to
visualise the resulting label TIFF afterwards if needed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import threading
from typing import Optional

from langchain_core.tools import tool

_NAPARI_PYTHON = "/opt/conda/envs/napari-mcp/bin/python"
_DEFAULT_TIMEOUT = 300

_registry_lock = threading.Lock()
_running_processes: list[subprocess.Popen] = []


def _register(proc: subprocess.Popen) -> None:
    with _registry_lock:
        _running_processes.append(proc)


def _unregister(proc: subprocess.Popen) -> None:
    with _registry_lock:
        try:
            _running_processes.remove(proc)
        except ValueError:
            pass


def kill_microsam_processes() -> int:
    killed = 0
    with _registry_lock:
        for proc in list(_running_processes):
            try:
                proc.kill()
                killed += 1
            except Exception:
                pass
        _running_processes.clear()
    return killed


@tool
def run_microsam_segmentation(
    input_path: str,
    output_path: str,
    model_type: str = "vit_b",
    segmentation_mode: str = "amg",
    ndim: Optional[int] = None,
    embedding_path: Optional[str] = None,
) -> str:
    """Run micro-sam automatic instance segmentation on an image file.

    Executes headlessly in the napari-mcp conda env (no napari window opened).
    The result is a label TIFF where each integer value is a unique instance ID.
    Use napari MCP tools (mcp__napari_mcp__add_layer) to visualise the result.

    Args:
        input_path: Absolute path to the input image (TIFF, PNG, etc.).
            Use /app/data/... paths for container-local files.
        output_path: Absolute path where the label TIFF will be saved.
            Parent directory must exist.
        model_type: SAM model variant. Options:
            "vit_b"  — ViT-Base (~375 MB, fastest, good general quality)
            "vit_l"  — ViT-Large (~1.2 GB, slower, better quality)
            "vit_h"  — ViT-Huge (~2.5 GB, slowest, best quality)
            "vit_b_lm" — micro-sam finetuned for light microscopy (recommended
                          for fluorescence / phase-contrast images)
            "vit_l_lm" — large finetuned LM model
        segmentation_mode: Segmentation algorithm:
            "amg" — Automatic Mask Generation (works with any model, default)
            "ais" — Automatic Instance Segmentation with decoder (faster,
                    requires a finetuned micro-sam model like vit_b_lm)
        ndim: Dimensionality of the image (2 for 2D, 3 for 3D/volumetric).
            If omitted, micro-sam infers it from the image shape.
        embedding_path: Optional path to cache/load SAM image embeddings.
            Reuse across multiple calls on the same image to avoid recomputing
            the expensive encoder pass.

    Returns:
        A status string: number of instances found and output path on success,
        or a descriptive error message on failure.
    """
    if not os.path.isfile(input_path):
        return f"Error: input file not found: {input_path}"

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        return f"Error: output directory does not exist: {output_dir}"

    ndim_arg = f", ndim={ndim}" if ndim is not None else ""
    embedding_arg = f', embedding_path="{embedding_path}"' if embedding_path else ""

    script = textwrap.dedent(f"""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

        from micro_sam.automatic_segmentation import (
            get_predictor_and_segmenter,
            automatic_instance_segmentation,
        )

        print("Loading model: {model_type} / mode: {segmentation_mode}")
        predictor, segmenter = get_predictor_and_segmenter(
            model_type="{model_type}",
            segmentation_mode="{segmentation_mode}",
        )

        print("Running segmentation on: {input_path}")
        result = automatic_instance_segmentation(
            predictor=predictor,
            segmenter=segmenter,
            input_path="{input_path}",
            output_path="{output_path}"{ndim_arg}{embedding_arg},
        )

        n_instances = int(result.max())
        print(f"DONE: {{n_instances}} instances | saved to {output_path}")
    """).strip()

    script_fd, script_path = tempfile.mkstemp(suffix=".py", prefix="microsam_")
    try:
        with os.fdopen(script_fd, "w") as f:
            f.write(script)

        proc = subprocess.Popen(
            [_NAPARI_PYTHON, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _register(proc)
        try:
            stdout, _ = proc.communicate(timeout=_DEFAULT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return f"Error: micro-sam timed out after {_DEFAULT_TIMEOUT}s."
        finally:
            _unregister(proc)

        if proc.returncode != 0:
            return f"micro-sam failed (exit {proc.returncode}):\n{stdout}"

        for line in reversed(stdout.splitlines()):
            if line.startswith("DONE:"):
                return line
        return f"Segmentation finished.\n{stdout}"

    except Exception as e:
        return f"Error launching micro-sam: {e}"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

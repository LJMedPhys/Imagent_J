import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from tests.module_loader import load_source_module


os.environ.setdefault("CHAT_DATA_PATH", tempfile.mkdtemp(prefix="imagentj-tests-"))
vision_tools = load_source_module(
    "vision_tools_under_test",
    "src/imagentj/tools/vision_tools.py",
)


def _invoke(tool, **kwargs):
    return tool.invoke(kwargs)


def test_build_mask_overlay_handles_16_bit_source(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_tools, "_CAPTURE_DIR", tmp_path)
    original_path = tmp_path / "original.tif"
    mask_path = tmp_path / "mask.tif"

    original = np.arange(100, dtype=np.uint16).reshape(10, 10) * 500
    mask = np.zeros((10, 10), dtype=np.uint16)
    mask[2:6, 3:7] = 4  # labelled masks use non-zero object IDs
    Image.fromarray(original).save(original_path)
    Image.fromarray(mask).save(mask_path)

    result = _invoke(
        vision_tools.build_mask_overlay,
        original_path=str(original_path),
        mask_path=str(mask_path),
        opacity=0.4,
        color="magenta",
    )

    output_path = Path(result)
    assert output_path.exists()
    overlay = np.asarray(Image.open(output_path))
    assert overlay.shape == (10, 10, 3)
    # A foreground pixel receives the magenta tint; a background pixel does not.
    assert overlay[3, 4, 0] > overlay[3, 4, 1]
    assert overlay[3, 4, 2] > overlay[3, 4, 1]
    assert np.array_equal(overlay[0, 0], [0, 0, 0])


def test_build_mask_overlay_rejects_dimension_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_tools, "_CAPTURE_DIR", tmp_path)
    original_path = tmp_path / "original.png"
    mask_path = tmp_path / "mask.png"
    Image.new("L", (10, 10), 100).save(original_path)
    Image.new("L", (9, 10), 255).save(mask_path)

    result = _invoke(
        vision_tools.build_mask_overlay,
        original_path=str(original_path),
        mask_path=str(mask_path),
    )

    assert result.startswith("ERROR: Original/mask dimensions do not match")


def test_build_compilation_uses_unique_output_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_tools, "_CAPTURE_DIR", tmp_path)
    image_path = tmp_path / "image.png"
    Image.new("RGB", (8, 8), "white").save(image_path)

    first = _invoke(
        vision_tools.build_compilation,
        image_paths=[str(image_path), str(image_path)],
        labels=["A", "B"],
    )
    second = _invoke(
        vision_tools.build_compilation,
        image_paths=[str(image_path), str(image_path)],
        labels=["A", "B"],
    )

    assert first != second
    assert Path(first).exists()
    assert Path(second).exists()

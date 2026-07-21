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


def test_build_mask_overlay_handles_prepared_16_bit_png_source(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_tools, "_CAPTURE_DIR", tmp_path)
    original_path = tmp_path / "original.png"
    mask_path = tmp_path / "mask.png"

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


def test_prepare_image_source_keeps_direct_images_and_window_titles(tmp_path):
    direct_path = tmp_path / "preview.png"
    Image.new("L", (4, 4), 1).save(direct_path)

    direct = _invoke(
        vision_tools.prepare_image_source_for_vlm,
        image_source=str(direct_path),
    )
    window = _invoke(
        vision_tools.prepare_image_source_for_vlm,
        image_source="Already Open Window",
    )

    assert direct == str(direct_path.resolve())
    assert window == "Already Open Window"


def test_prepare_image_source_routes_tiff_through_fiji(tmp_path, monkeypatch):
    tiff_path = tmp_path / "stack.tif"
    Image.new("I;16", (4, 4), 1024).save(tiff_path)
    prepared_path = tmp_path / "fiji_preview.png"

    class FakeCaptureTool:
        def invoke(self, args):
            assert args == {"image_path": str(tiff_path)}
            return str(prepared_path)

    monkeypatch.setattr(
        vision_tools,
        "capture_image_file_via_fiji",
        FakeCaptureTool(),
    )

    result = _invoke(
        vision_tools.prepare_image_source_for_vlm,
        image_source=str(tiff_path),
    )

    assert result == str(prepared_path)


def test_capture_image_file_via_fiji_closes_only_new_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_tools, "_CAPTURE_DIR", tmp_path)
    source_path = tmp_path / "sample.czi"
    source_path.touch()

    class FakeImage:
        def __init__(self, image_id):
            self.image_id = image_id
            self.changes = True
            self.closed = False

        def getID(self):
            return self.image_id

        def duplicate(self):
            return FakeImage(-self.image_id)

        def close(self):
            self.closed = True

    existing = FakeImage(1)
    opened = FakeImage(2)

    class FakeWindowManager:
        images = {1: existing}

        @classmethod
        def getIDList(cls):
            return list(cls.images)

        @classmethod
        def getCurrentImage(cls):
            return cls.images[max(cls.images)]

        @classmethod
        def getImage(cls, image_id):
            return cls.images.get(image_id)

    class FakeIJ:
        @staticmethod
        def open(path):
            assert path == str(source_path.resolve())
            FakeWindowManager.images[2] = opened

        @staticmethod
        def saveAs(image, image_format, path):
            assert image_format == "PNG"
            Image.new("RGB", (4, 4), "white").save(path)

    monkeypatch.setattr(
        vision_tools,
        "_get_ij_classes",
        lambda: (FakeWindowManager, FakeIJ),
    )

    result = _invoke(
        vision_tools.capture_image_file_via_fiji,
        image_path=str(source_path),
    )

    assert Path(result).exists()
    assert opened.closed is True
    assert existing.closed is False


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

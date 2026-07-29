"""
Self-contained validation of the Big-FISH spot-detection skill.

Builds synthetic Gaussian-spot fields with KNOWN ground truth and asserts that the
AUTOMATIC threshold (threshold=None) recovers them in 2D and 3D, that sub-pixel
fitting improves localization, and that the documented broken function is still the
only broken one.

It also guards the three failure modes that were observed on real data:
  B1  calibration is READ from the file (ResolutionUnit=1 + ImageJ unit) and the
      reader returns None rather than silently guessing
  B2  a spot_radius that does not match the objects destroys detection
  B4  segmentation follows real object extent and splits touching objects,
      rather than stamping fixed-radius disks

Prints "RESULT: PASS" / "RESULT: FAIL" and exits nonzero on failure.

    /opt/conda/envs/local_imagent_J/bin/python TEST_SPOT_DETECTION.py
"""
import importlib.util
import os
import sys
import tempfile

import numpy as np
import tifffile
from skimage import measure

import bigfish.detection as detection

TOL_PX = 2.0        # a detection within 2 px of a ground-truth spot counts as a match
failures = []


def _load_segmentation_workflow():
    """Import the sibling workflow so its helpers are tested, not a copy of them."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "WORKFLOW_SPOT_SEGMENTATION.py")
    spec = importlib.util.spec_from_file_location("bf_segmentation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _segment(seg, image, pixel_size_nm):
    """Run the workflow's segmentation stages on an in-memory image."""
    flat = seg.denoise(image)
    mask = seg.foreground(flat)
    radius_nm, _ = seg.measure_object_radius_nm(mask, pixel_size_nm)
    labels, _ = seg.split_touching(flat, mask, pixel_size_nm, radius_nm)
    return labels


def check(label, condition, detail=""):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def match(spots, truth):
    """Greedy nearest-neighbour matching -> (TP, FP, FN, median localization error)."""
    truth = np.asarray(truth, dtype=float)
    matched, errors = set(), []
    for spot in np.asarray(spots, dtype=float):
        distances = np.linalg.norm(truth - spot, axis=1)
        index = int(np.argmin(distances))
        if distances[index] <= TOL_PX and index not in matched:
            matched.add(index)
            errors.append(distances[index])
    tp = len(matched)
    return tp, len(spots) - tp, len(truth) - tp, (np.median(errors) if errors else np.nan)


def make_2d(rng, size=512, step=60, sigma=1.4):
    image = np.full((size, size), 100.0)
    yy, xx = np.mgrid[0:size, 0:size]
    truth = []
    for y in range(40, size - 40, step):
        for x in range(40, size - 40, step):
            cy, cx = y + rng.uniform(-0.4, 0.4), x + rng.uniform(-0.4, 0.4)
            truth.append((cy, cx))
            image += 900.0 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))
    image += rng.normal(0, 12, image.shape)
    return np.clip(image, 0, 65535).astype(np.uint16), truth


def make_3d(rng, nz=24, size=256):
    image = np.full((nz, size, size), 100.0)
    zz, yy, xx = np.mgrid[0:nz, 0:size, 0:size]
    truth = []
    for z in range(6, nz - 6, 6):
        for y in range(30, size - 30, 60):
            for x in range(30, size - 30, 60):
                truth.append((z, y, x))
                image += 900.0 * np.exp(
                    -(((zz - z) ** 2) / (2 * 2.0 ** 2)
                      + ((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.4 ** 2)))
    image += rng.normal(0, 12, image.shape)
    return np.clip(image, 0, 65535).astype(np.uint16), truth


def make_varied_2d(rng, size=512, step=90):
    """Isolated puncta whose sigma spans a 3x range, so extent genuinely varies."""
    image = np.full((size, size), 100.0)
    yy, xx = np.mgrid[0:size, 0:size]
    count = 0
    for i, y in enumerate(range(50, size - 50, step)):
        for j, x in enumerate(range(50, size - 50, step)):
            sigma = 1.5 + 1.5 * ((i + j) % 3)      # 1.5 / 3.0 / 4.5 px
            image += 900.0 * np.exp(-(((yy - y) ** 2 + (xx - x) ** 2) / (2 * sigma ** 2)))
            count += 1
    image += rng.normal(0, 10, image.shape)
    return np.clip(image, 0, 65535).astype(np.uint16), count


def make_touching_pairs(rng, size=512, step=90, separation=11):
    """Pairs close enough to merge under a threshold — the case splitting must fix."""
    image = np.full((size, size), 100.0)
    yy, xx = np.mgrid[0:size, 0:size]
    pairs = 0
    for y in range(60, size - 60, step):
        for x in range(60, size - 60, step):
            for dx, amp, sigma in ((0, 900, 3.0), (separation, 800, 2.5)):
                image += amp * np.exp(-(((yy - y) ** 2 + (xx - x - dx) ** 2) / (2 * sigma ** 2)))
            pairs += 1
    image += rng.normal(0, 10, image.shape)
    return np.clip(image, 0, 65535).astype(np.uint16), pairs


def main():
    rng = np.random.default_rng(0)

    # ── 2D, automatic threshold ──────────────────────────────────────────────
    image2d, truth2d = make_2d(rng)
    spots2d, threshold = detection.detect_spots(
        images=image2d, threshold=None, return_threshold=True,
        voxel_size=(100, 100), spot_radius=(150, 150))
    tp, fp, fn, err = match(spots2d, truth2d)
    print(f"[test] 2D: truth={len(truth2d)} detected={len(spots2d)} auto_threshold={threshold}")
    print(f"[test] 2D: TP={tp} FP={fp} FN={fn} medianLocErr={err:.3f} px")
    check("2D recall >= 0.95", tp / len(truth2d) >= 0.95, f"{tp / len(truth2d):.3f}")
    check("2D false positives <= 2", fp <= 2, f"FP={fp}")
    check("2D coordinates are (y, x)", spots2d.shape[1] == 2, f"shape={spots2d.shape}")

    # ── sub-pixel refinement must actually improve localization ──────────────
    refined = detection.fit_subpixel(image2d, spots2d, (100, 100), (150, 150))
    _, _, _, err_sub = match(refined, truth2d)
    print(f"[test] sub-pixel: medianLocErr {err:.3f} px -> {err_sub:.3f} px")
    check("fit_subpixel improves localization", err_sub < err, f"{err:.3f} -> {err_sub:.3f} px")

    # ── 3D anisotropic, automatic threshold ──────────────────────────────────
    image3d, truth3d = make_3d(rng)
    spots3d, threshold3d = detection.detect_spots(
        images=image3d, threshold=None, return_threshold=True,
        voxel_size=(300, 100, 100), spot_radius=(400, 150, 150))
    tp3, fp3, fn3, err3 = match(spots3d, truth3d)
    print(f"[test] 3D: truth={len(truth3d)} detected={len(spots3d)} auto_threshold={threshold3d}")
    print(f"[test] 3D: TP={tp3} FP={fp3} FN={fn3} medianLocErr={err3:.3f} px")
    check("3D recall >= 0.95", tp3 / len(truth3d) >= 0.95, f"{tp3 / len(truth3d):.3f}")
    check("3D false positives <= 2", fp3 <= 2, f"FP={fp3}")
    check("3D coordinates are (z, y, x)", spots3d.shape[1] == 3, f"shape={spots3d.shape}")

    # ── batch mode shares ONE threshold across the list (pitfall B7) ─────────
    batch, batch_threshold = detection.detect_spots(
        images=[image2d, image2d], threshold=None, return_threshold=True,
        voxel_size=(100, 100), spot_radius=(150, 150))
    check("batch mode returns one result per image",
          isinstance(batch, list) and len(batch) == 2, f"{[len(s) for s in batch]}")
    check("batch mode shares a single threshold",
          np.isscalar(batch_threshold) or np.ndim(batch_threshold) == 0,
          f"threshold={batch_threshold}")

    # ── elbow QC values are available and agree with detect_spots ────────────
    thresholds, log_counts, auto = detection.get_elbow_values(
        images=image2d, voxel_size=(100, 100), spot_radius=(150, 150))
    check("get_elbow_values agrees with detect_spots",
          np.isclose(auto, threshold), f"elbow={auto} detect={threshold}")
    check("elbow curve is populated", len(thresholds) == len(log_counts) > 0,
          f"{len(thresholds)} points")
    # Guards pitfall B9: the second return is log(count), so exp() of the value at the
    # chosen threshold must equal the number of spots detect_spots actually returned.
    plateau = np.exp(log_counts[np.searchsorted(thresholds, auto) + 5])
    check("elbow counts are LOG-scaled (B9)",
          np.isclose(plateau, len(spots2d), rtol=0.05),
          f"exp(log_count) on the plateau = {plateau:.1f}, detected = {len(spots2d)}")

    # ── B2: a mismatched spot_radius silently wrecks detection ──────────────
    wrong = detection.detect_spots(images=image2d, threshold=None,
                                   voxel_size=(100, 100), spot_radius=(1800, 1800))
    tp_w, _, _, _ = match(wrong, truth2d)
    print(f"[test] radius 12x too large: detected={len(wrong)} TP={tp_w} "
          f"(correct radius gave {len(spots2d)})")
    check("mismatched spot_radius degrades recall (B2)",
          tp_w < 0.5 * len(truth2d),
          f"recall {tp_w / len(truth2d):.2f} vs 1.00 at the right radius")

    # ── B1: calibration is read, not guessed ────────────────────────────────
    seg = _load_segmentation_workflow()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cal.tif")
        # Exactly the layout that defeats naive readers: ResolutionUnit=1 with the
        # real unit only in ImageJ's metadata block (see B1).
        tifffile.imwrite(path, image2d, resolution=(3.104115, 3.104115),
                         resolutionunit=1, imagej=True, metadata={"unit": "micron"})
        px, source = seg.read_pixel_size_nm(path)
        ok = px is not None and np.isclose(px[0], 1e3 / 3.104115, rtol=1e-3)
        check("read_pixel_size_nm handles ResolutionUnit=1 + ImageJ unit (B1)",
              ok, f"got {px} via {source}; expected ~322.2 nm/px")

        blank = os.path.join(tmp, "nocal.tif")
        tifffile.imwrite(blank, image2d)
        px_none, _ = seg.read_pixel_size_nm(blank)
        check("read_pixel_size_nm returns None rather than guessing (B1)",
              px_none is None, f"got {px_none}")

    # ── B4: segmentation tracks real object SIZE, not a stamped constant ─────
    varied, varied_truth = make_varied_2d(np.random.default_rng(3))
    labels = _segment(seg, varied, (100, 100))
    props = measure.regionprops(labels)
    areas = np.array([p.area for p in props])
    print(f"[test] segmentation: {len(areas)} objects, areas "
          f"{areas.min():.0f}/{np.median(areas):.0f}/{areas.max():.0f} px")
    check("segmentation recovers about the right object count (B4)",
          abs(len(areas) - varied_truth) <= 0.1 * varied_truth,
          f"{len(areas)} objects vs {varied_truth} truth")
    # Objects were seeded across a 3x range of sigma, so a segmentation that follows
    # real extent must show a correspondingly wide area spread. Stamped disks cannot.
    check("segmented areas span the seeded size range (B4)",
          areas.max() / areas.min() >= 2.0,
          f"max/min = {areas.max() / areas.min():.1f}x")

    # ── B4/B2: touching objects split when the radius is the SINGLE-object one ─
    pairs, n_pairs = make_touching_pairs(np.random.default_rng(4))
    flat_p = seg.denoise(pairs)
    mask_p = seg.foreground(flat_p)
    merged = measure.label(mask_p).max()
    split, n_seeds = seg.split_touching(flat_p, mask_p, (100, 100), (300, 300))
    print(f"[test] touching pairs: {merged} merged regions -> {split.max()} split "
          f"({n_seeds} seeds), truth={2 * n_pairs}")
    check("watershed splits touching objects at the single-object radius (B4)",
          split.max() > merged and abs(split.max() - 2 * n_pairs) <= 0.15 * 2 * n_pairs,
          f"{merged} -> {split.max()} (truth {2 * n_pairs})")

    # ── decompose_dense is a safe no-op when there are no dense regions ──────
    post, dense_regions, _ = detection.decompose_dense(
        image=image2d, spots=spots2d, voxel_size=(100, 100), spot_radius=(150, 150),
        alpha=0.7, beta=1, gamma=5)
    check("decompose_dense is a no-op without dense regions",
          len(post) == len(spots2d), f"{len(spots2d)} -> {len(post)}")

    # ── the documented breakage (pitfall B8) is still exactly this one ───────
    try:
        detection.compute_snr_spots(image2d, spots2d, (100, 100), (150, 150))
        check("compute_snr_spots still documented as broken", False,
              "it now WORKS — update pitfall B11 in SKILL.md and SCRIPT_API.md")
    except AttributeError:
        check("compute_snr_spots still broken as documented (B11)", True, "AttributeError np.int")

    print("\nRESULT:", "FAIL" if failures else "PASS")
    if failures:
        print("failed checks:", ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

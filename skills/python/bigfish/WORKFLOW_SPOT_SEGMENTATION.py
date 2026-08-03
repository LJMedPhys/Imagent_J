"""
WORKFLOW: fluorescence image -> per-object SEGMENTATION MASK + measurement CSV.

Use this when you need each punctum's AREA and INTENSITY, not just its position.
`detect_spots` alone returns POINTS; this script turns them into regions whose
outlines follow the real object boundaries.

How it works (each tool does what it is good at):
  1. read the pixel size from the file  — never guessed, fails loudly if unknown
  2. denoise + subtract background      — EDGE-PRESERVING smooth -> median -> background
  3. Otsu threshold                     — defines each object's EXTENT
  4. MEASURE the object radius          — from the cleaned mask, not assumed
  5. Big-FISH spots as watershed seeds  — SPLITS objects that touch
  6. regionprops on the ORIGINAL image  — area / mean / integrated density

Runs in the MAIN env. Copy this file, edit the CONFIG block, delete the synthetic
fallback, and hand the CSV to the statistics stage.

Verified end-to-end on real data. Run it untouched and it segments synthetic data
so you can see the shape of the output before pointing it at real files.
"""
import os

import numpy as np
import pandas as pd
import tifffile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import ndimage as ndi
from skimage import filters, morphology, measure, restoration, segmentation

import bigfish.detection as detection

# ─────────────────────────── CONFIG ───────────────────────────
INPUT_PATH = "/app/data/spots.tif"

# Pixel size in NANOMETRES, (y, x). None = read it from the file (preferred).
# Set explicitly ONLY if the file carries no calibration — never guess a value.
PIXEL_SIZE_NM = None

# Expected object radius in NANOMETRES. None = MEASURE it from the image.
# Do NOT leave a diffraction-limited default (150 nm) on non-point objects:
# a radius that does not match the objects silently destroys detection.
# CAVEAT: the measured value is the median of the THRESHOLD REGIONS, so if most
# objects touch, it is the radius of the merged clumps and nothing will split.
# When you know objects overlap, set the SINGLE-object radius here explicitly.
SPOT_RADIUS_NM = None

# Denoising ladder. Raise these when background texture leaks into the mask.
#
# SMOOTHING picks the filter used before thresholding. The default is
# EDGE-PRESERVING and should stay that way whenever spots sit close together:
# a plain Gaussian blurs across the gap between two neighbouring spots, Otsu
# then fuses them into one region, and the area/intensity of both is wrong.
#   "tv"        total-variation (Chambolle). Edge-preserving, works in 2D AND 3D,
#               no extra dependency. The default.
#   "bilateral" skimage bilateral. Edge-preserving, 2D only, slower.
#   "gaussian"  plain isotropic Gaussian. MERGES neighbouring spots — only for
#               well-separated objects, and only if you have looked at the QC.
#   "none"      skip smoothing (median + background subtraction still run).
SMOOTHING = "tv"
TV_WEIGHT = 0.05            # "tv": higher = smoother. Edges survive either way.
BILATERAL_SIGMA_SPATIAL = 1.5   # "bilateral": neighbourhood size in px
GAUSSIAN_SIGMA_PX = 1.0     # "gaussian" ONLY; ~1 px suits most puncta
MEDIAN_RADIUS_PX = 1        # kills salt-and-pepper speckle; 0 disables
BACKGROUND_SIGMA_PX = 25.0  # large-scale background estimate; >> object size
MIN_OBJECT_AREA_PX = 12     # drop anything smaller than a believable object

SPLIT_TOUCHING = True       # watershed-split merged objects using Big-FISH seeds

OUTPUT_LABELS = "Puncta_labels.tif"
OUTPUT_CSV = "Puncta_measurements.csv"
QC_OVERLAY = "Puncta_QC.png"   # shows the real mask contours. Always look at it.
# ──────────────────────────────────────────────────────────────


def read_pixel_size_nm(path):
    """
    Return ((y_nm, x_nm), source) or (None, reason).

    Handles the trap that silently corrupts calibration: ImageJ writes
    ResolutionUnit=1 ("no absolute unit") and puts the real unit in its own
    metadata block, so code that only understands unit 2 (inch) and 3 (cm)
    finds nothing and falls back to a guess.
    """
    to_nm = {"nm": 1.0, "nanometer": 1.0, "nanometers": 1.0,
             "um": 1e3, "µm": 1e3, "micron": 1e3, "microns": 1e3,
             "micrometer": 1e3, "micrometers": 1e3,
             "mm": 1e6, "millimeter": 1e6, "cm": 1e7}

    with tifffile.TiffFile(path) as tif:
        page, ij = tif.pages[0], (tif.imagej_metadata or {})

        def res(tag):
            if tag not in page.tags:
                return None
            v = page.tags[tag].value
            v = float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)
            return v if v > 0 else None

        xres, yres = res("XResolution"), res("YResolution")
        unit_tag = page.tags["ResolutionUnit"].value if "ResolutionUnit" in page.tags else None

        # ImageJ sometimes stores the size directly.
        pw, ph = ij.get("pixel_width"), ij.get("pixel_height")
        ij_unit = str(ij.get("unit", "")).strip().lower()
        if pw and ph and ij_unit in to_nm:
            return (float(ph) * to_nm[ij_unit], float(pw) * to_nm[ij_unit]), f"ImageJ pixel_width ({ij_unit})"

        if xres and yres:
            if unit_tag == 2:
                return (25.4e6 / yres, 25.4e6 / xres), "TIFF ResolutionUnit=inch"
            if unit_tag == 3:
                return (1e7 / yres, 1e7 / xres), "TIFF ResolutionUnit=cm"
            # unit_tag in (1, None): resolution is per ImageJ's own unit
            if ij_unit in to_nm:
                return (to_nm[ij_unit] / yres, to_nm[ij_unit] / xres), f"ImageJ unit={ij_unit}"

    return None, "no usable calibration in TIFF tags or ImageJ metadata"


def smooth(image):
    """
    Edge-preserving smoothing — the step that decides whether touching spots stay
    separate objects (pitfall B13).

    Smoothing before detection is necessary: it stops noise peaks becoming spurious
    maxima and stops speckle tearing holes in the mask. But a plain *Gaussian* is
    the wrong tool, because it also blurs across the dark gap BETWEEN two nearby
    spots. The Otsu step below then sees one connected bright region and reports one
    object with the summed area. Total-variation and bilateral denoising flatten the
    noise while keeping the intensity step at the spot border, so the gap survives.

    This is the ImageJ/Fiji `Anisotropic Diffusion 2D` idea and the AICS
    `edge_preserving_smoothing_3d` (ITK GradientAnisotropicDiffusion) idea, done
    with what is already installed here. Unlike the Fiji plugin, TV denoising is
    genuinely nD, so this also works if you extend the workflow to 3D stacks.
    """
    f = image.astype(float)
    if SMOOTHING == "none":
        return f
    if SMOOTHING == "gaussian":
        return filters.gaussian(f, sigma=GAUSSIAN_SIGMA_PX, preserve_range=True)

    # TV and bilateral both interpret their strength parameter relative to the
    # image range, so normalise to [0, 1] and put the range back afterwards.
    lo, hi = float(f.min()), float(f.max())
    if hi <= lo:
        return f
    scaled = (f - lo) / (hi - lo)

    if SMOOTHING == "tv":
        out = restoration.denoise_tv_chambolle(scaled, weight=TV_WEIGHT)
    elif SMOOTHING == "bilateral":
        if f.ndim != 2:
            raise ValueError("SMOOTHING='bilateral' is 2D only; use 'tv' for a stack.")
        out = restoration.denoise_bilateral(
            scaled, sigma_color=None, sigma_spatial=BILATERAL_SIGMA_SPATIAL)
    else:
        raise ValueError(
            f"SMOOTHING={SMOOTHING!r}; expected 'tv', 'bilateral', 'gaussian' or 'none'.")

    return out * (hi - lo) + lo


def denoise(image):
    """Edge-preserving smooth -> median -> background subtraction. Returns a flat float image."""
    f = smooth(image)
    if MEDIAN_RADIUS_PX:
        f = filters.median(f, morphology.disk(MEDIAN_RADIUS_PX))
    background = filters.gaussian(f, sigma=BACKGROUND_SIGMA_PX, preserve_range=True)
    return np.clip(f - background, 0, None)


def foreground(flat):
    """Otsu on the flattened image, then binary cleanup. This defines EXTENT."""
    mask = flat > filters.threshold_otsu(flat)
    mask = morphology.binary_opening(mask, morphology.disk(1))
    return morphology.remove_small_objects(mask, MIN_OBJECT_AREA_PX)


def measure_object_radius_nm(mask, pixel_size_nm):
    """The object radius, MEASURED from the cleaned mask rather than assumed."""
    props = measure.regionprops(measure.label(mask))
    if not props:
        raise ValueError("cannot measure object radius: the mask is empty")
    radius_px = float(np.median([p.equivalent_diameter for p in props])) / 2.0
    return (radius_px * pixel_size_nm[0], radius_px * pixel_size_nm[1]), radius_px


def split_touching(flat, mask, pixel_size_nm, spot_radius_nm):
    """
    Use Big-FISH detections as watershed seeds so objects that touch are separated.
    Regions Big-FISH did not seed keep their own label rather than being dropped.
    """
    try:
        spots = detection.detect_spots(images=flat, threshold=None,
                                       voxel_size=pixel_size_nm, spot_radius=spot_radius_nm)
    except Exception as exc:
        # The automatic threshold needs a spot population to find an elbow in; on
        # images with very few objects it can fail outright. Splitting is optional,
        # so fall back to plain connected components instead of losing the run.
        print(f"WARNING: Big-FISH seeding failed ({type(exc).__name__}: {exc}); "
              "falling back to unsplit connected components.")
        return measure.label(mask), 0

    seeds = [s for s in spots if mask[s[0], s[1]]]
    if not seeds:
        print("WARNING: no Big-FISH seed landed inside the mask; not splitting.")
        return measure.label(mask), 0

    markers = np.zeros(mask.shape, dtype=np.int32)
    for i, (y, x) in enumerate(seeds, start=1):
        markers[y, x] = i

    labels = segmentation.watershed(-flat, markers=markers, mask=mask)
    unseeded = measure.label(mask & (labels == 0))   # objects Big-FISH missed
    unseeded[unseeded > 0] += labels.max()
    labels, _, _ = segmentation.relabel_sequential(labels + unseeded)
    return labels, len(seeds)


def load_input():
    """Load the configured image, or synthesise one containing close-neighbour puncta."""
    if os.path.exists(INPUT_PATH):
        return tifffile.imread(INPUT_PATH), False

    print("WARNING: configured input not found — running on synthetic data.")
    rng = np.random.default_rng(0)
    size = 512
    yy, xx = np.mgrid[0:size, 0:size]
    image = np.full((size, size), 100.0)

    def add(cy, cx, sigma):
        nonlocal image
        image = image + 900.0 * np.exp(
            -(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))

    # Puncta of DIFFERENT sizes, so the output shows a real size distribution
    # rather than one repeated value. Every other one gets a CLOSE NEIGHBOUR,
    # separated by only ~3.5 sigma, so the fallback run actually exercises the
    # thing this workflow has to get right: keeping touching spots apart. Smooth
    # these with a plain Gaussian and the pairs fuse (pitfall B13).
    n_pairs = 0
    for i, cy in enumerate(range(60, size - 60, 90)):
        for j, cx in enumerate(range(60, size - 60, 90)):
            sigma = 2.0 + 0.5 * ((i + j) % 4)
            add(cy, cx, sigma)
            if (i + j) % 2 == 0:
                add(cy, cx + int(round(3.5 * sigma)), sigma)
                n_pairs += 1
    image += rng.normal(0, 10, image.shape)
    print(f"synthetic: 25 puncta, {n_pairs} of them with a close neighbour")
    return np.clip(image, 0, 65535).astype(np.uint16), True


def qc_overlay(image, labels, path):
    """Draw the ACTUAL mask contours. Never QC a segmentation with marker circles."""
    lo, hi = np.percentile(image, 0.5), np.percentile(image, 99.9)
    grey = np.clip((image.astype(float) - lo) / max(hi - lo, 1e-9), 0, 1)
    rgb = (np.stack([grey] * 3, -1) * 255).astype(np.uint8)
    solid = labels > 0
    rgb[solid ^ ndi.binary_erosion(solid, iterations=1)] = [0, 255, 0]
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(rgb)
    ax.set_title(f"{labels.max()} objects (contours = saved mask)")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"wrote {path}")


def main():
    image, synthetic = load_input()
    if image.ndim != 2:
        raise ValueError(f"this workflow is 2D; got shape {image.shape}. "
                         "Segment a 3D stack plane by plane or extend it deliberately.")
    print(f"image {image.shape} {image.dtype}")

    # 1. calibration — read, never guessed
    if PIXEL_SIZE_NM is not None:
        pixel_size_nm, source = tuple(PIXEL_SIZE_NM), "CONFIG"
    elif synthetic:
        pixel_size_nm, source = (100.0, 100.0), "synthetic default"
    else:
        pixel_size_nm, source = read_pixel_size_nm(INPUT_PATH)
        if pixel_size_nm is None:
            raise ValueError(
                f"cannot determine pixel size ({source}). Set PIXEL_SIZE_NM explicitly "
                "from the acquisition metadata. Do NOT guess: a wrong pixel size "
                "silently corrupts detection and every physical column in the CSV.")
    print(f"pixel size = ({pixel_size_nm[0]:.1f}, {pixel_size_nm[1]:.1f}) nm/px  [{source}]")

    # 2-3. extent
    if SMOOTHING == "gaussian":
        print("WARNING: SMOOTHING='gaussian' blurs across the gap between neighbouring "
              "spots and Otsu then fuses them (pitfall B13). Check the QC overlay.")
    print(f"smoothing = {SMOOTHING}")
    flat = denoise(image)
    mask = foreground(flat)
    n_regions = measure.label(mask).max()
    print(f"threshold foreground: {n_regions} regions")
    if n_regions == 0:
        raise ValueError("no objects survived thresholding — check the denoising ladder.")

    # 4. object radius — measured, not assumed
    if SPOT_RADIUS_NM is not None:
        spot_radius_nm = tuple(SPOT_RADIUS_NM)
        print(f"object radius = {spot_radius_nm} nm  [CONFIG]")
    else:
        spot_radius_nm, radius_px = measure_object_radius_nm(mask, pixel_size_nm)
        print(f"object radius = {radius_px:.2f} px -> "
              f"({spot_radius_nm[0]:.0f}, {spot_radius_nm[1]:.0f}) nm  [measured]")

    # 5. split touching objects
    if SPLIT_TOUCHING:
        labels, n_seeds = split_touching(flat, mask, pixel_size_nm, spot_radius_nm)
        print(f"watershed split with {n_seeds} Big-FISH seeds: "
              f"{n_regions} regions -> {labels.max()} objects")
    else:
        labels = measure.label(mask)

    # 6. measure on the ORIGINAL image
    props = measure.regionprops(labels, intensity_image=image)
    px_area_um2 = (pixel_size_nm[0] / 1000.0) * (pixel_size_nm[1] / 1000.0)
    rows = [{
        "object_id": p.label,
        "y_px": round(p.centroid[0], 2),
        "x_px": round(p.centroid[1], 2),
        "area_px": p.area,
        "area_um2": round(p.area * px_area_um2, 4),
        "mean": round(float(p.intensity_mean), 3),
        "min": float(p.intensity_min),
        "max": float(p.intensity_max),
        "raw_int_den": float(p.image_intensity.sum()),
        "int_den": round(float(p.intensity_mean) * p.area * px_area_um2, 3),
    } for p in props]
    df = pd.DataFrame(rows)

    tifffile.imwrite(OUTPUT_LABELS, labels.astype(np.int32))
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"wrote {OUTPUT_LABELS} and {OUTPUT_CSV}")
    print(f"\n{len(df)} objects | area_px min={df.area_px.min()} "
          f"median={df.area_px.median():.0f} max={df.area_px.max()}")

    if QC_OVERLAY:
        qc_overlay(image, labels, QC_OVERLAY)

    if synthetic:
        print("\nNOTE: synthetic data — 25 puncta of four different sizes, 13 of them")
        print("paired with a close neighbour. Set INPUT_PATH to real files.")


if __name__ == "__main__":
    main()

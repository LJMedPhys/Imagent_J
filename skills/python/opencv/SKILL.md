---
name: opencv
description: >-
  OpenCV (`import cv2`, package opencv-python) is in the MAIN env (local_imagent_J). Use it for
  contour extraction and shape approximation (findContours, approxPolyDP, minAreaRect,
  convexHull, fitEllipse), true pixel areas via connectedComponentsWithStats, template matching,
  feature detection and matching (ORB/SIFT + BFMatcher), affine/perspective warping
  (warpAffine, warpPerspective, findHomography), and video IO. CRITICAL GOTCHAS: cv2 reads colour
  as BGR not RGB (cvtColor with COLOR_BGR2RGB before matplotlib or skimage); most cv2 functions
  need uint8 and findContours rejects uint16, so a 16-bit image must be rescaled, which DESTROYS
  quantitative intensity — never measure intensity through cv2; cv2.contourArea is polygon area
  through pixel centres and undercounts (a 256-px square reports 225); contour order is not label
  order; cv2.imwrite silently applies JPEG compression by extension. Prefer scikit-image for
  quantitative, 16-bit, float, or 3D work.
---

# OpenCV (cv2) — Documentation Index

Main env (`local_imagent_J`). Verified on **cv2 4.13.0** (currently in the image) and
**cv2 5.0.0** (what a fresh `pip install opencv-python` gives) — identical behaviour on
everything documented here.

> **Default to scikit-image.** OpenCV is 8-bit-centric, BGR-ordered and 2D-only. Reach
> for it only when it has an algorithm skimage lacks.

## When to use this vs. scikit-image

| Task | Use |
|---|---|
| Threshold, filter, measure 16-bit/float data | scikit-image |
| 3D / ND stacks | scikit-image |
| Rigid translation registration, same modality | scikit-image (`phase_cross_correlation`) |
| Contour polygons, `minAreaRect`, `convexHull`, `approxPolyDP` | OpenCV |
| ORB/SIFT keypoints + matching | OpenCV |
| Perspective / affine warp from point pairs | OpenCV |
| Template matching | OpenCV |
| Reading a video file frame by frame | OpenCV |

## The gotchas, in order of how often they bite

1. **BGR, not RGB.** `cv2.imread` returns channels in BGR order. Handing that straight
   to `plt.imshow` or a skimage function produces silently wrong colours.
   ```python
   rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
   ```

2. **uint8 only.** `findContours` raises on `uint16`. Rescaling to `uint8` **destroys
   quantitative intensity** — so **never measure intensity through cv2**. Segment with
   cv2 if you must, then measure on the ORIGINAL array with
   `skimage.measure.regionprops_table`.
   ```python
   img8 = cv2.normalize(img16, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
   ```

3. **`contourArea` is not the pixel count.** It is the polygon area through pixel
   centres. A solid 16×16 square has **256** pixels but `contourArea` reports **225**.
   For true areas use `connectedComponentsWithStats` (reports 256). Use `contourArea`
   only for shape *ratios* (circularity, solidity), where the bias largely cancels.

4. **Contour order is not label order.** `findContours` returns contours bottom-up.
   Never assume `contours[i]` is label `i+1` — match by centroid.

5. **`CHAIN_APPROX_SIMPLE` breaks `fitEllipse` on rectangles.** A square compresses to
   4 contour points; `fitEllipse` needs ≥ 5 and raises. Use `CHAIN_APPROX_NONE`, or
   guard with `if len(contour) >= 5`.

6. **The matcher norm must match the descriptor.** ORB/BRISK are binary →
   `cv2.NORM_HAMMING`. SIFT is float → `cv2.NORM_L2`. Mixing them returns garbage
   matches **with no error**.

7. **`warpPerspective`/`warpAffine` take `dsize=(width, height)`** — the reverse of
   `img.shape[:2]`. Passing it backwards silently produces a transposed, cropped image.

8. **`cv2.imwrite` compresses by extension.** `.jpg` applies lossy JPEG with no warning.
   Write `.tif` or `.png` for anything that will be re-analysed. For publication images,
   save through ImageJ (see `image_publication_standarts`).

## Headless — never call the GUI functions

The container has no display. **`cv2.imshow`, `cv2.waitKey` and `cv2.destroyAllWindows`
exist and will hang or crash the subprocess.** Save with `cv2.imwrite`, or plot through
matplotlib.

## The pattern — contours and shape descriptors

```python
import cv2
import numpy as np

binary = (labels > 0).astype(np.uint8) * 255      # uint8, 0 or 255

# True pixel areas (label 0 is background)
n_labels, cc, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
areas_px = stats[1:, cv2.CC_STAT_AREA]

# Contour polygons — 2 return values in cv2 >= 4
contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
for c in contours:
    perim = cv2.arcLength(c, closed=True)
    poly_area = cv2.contourArea(c)
    circularity = 4 * np.pi * poly_area / perim**2 if perim else np.nan
    hull_area = cv2.contourArea(cv2.convexHull(c))
    solidity = poly_area / hull_area if hull_area else np.nan
```

`contourArea` and `arcLength` are in **pixels** — convert with the PROJECT STATE pixel
size exactly as for `regionprops` (see the `scikit_image` skill).

## Files

| File | What it covers |
|---|---|
| `SCRIPT_API.md` | Verified dtype contract, contour modes/methods, `contourArea` vs pixel count, `connectedComponentsWithStats` columns, matcher norms, transform shapes |
| `WORKFLOW_CONTOUR_SHAPE.py` | Mask → per-object shape descriptors CSV. Uses `connectedComponentsWithStats` for true areas and matches contours to components by centroid |
| `WORKFLOW_FEATURE_REGISTRATION.py` | ORB + RANSAC homography aligning two views; verifies it improved correlation with the reference |

Both workflows run untouched on synthetic data and were verified on cv2 4.13 and 5.0.

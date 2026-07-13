# OpenCV (cv2) — Python Script API

Verified against **cv2 4.13.0** (the version currently in the image) and **cv2 5.0.0**
(what `pip install opencv-python` resolves to today). Every call documented below
behaves identically on both — the 4→5 major bump did not change this surface.

Main env (`local_imagent_J`), `import cv2`.

> **Default to scikit-image.** OpenCV is 8-bit-centric, BGR-ordered and 2D-only. Reach
> for it only when it has something skimage lacks: contour polygons, feature matching,
> perspective warps, template matching, video IO.

## The dtype contract

| Function family | Accepts |
|---|---|
| `findContours` | `uint8` or `int32` **only** — `uint16` raises `cv2.error` |
| `GaussianBlur`, `filter2D` | `uint8`, `uint16`, `float32`, `float64` (dtype preserved) |
| `ORB`/`SIFT.detectAndCompute` | `uint8` grayscale |
| `connectedComponentsWithStats` | `uint8` |

Rescaling a 16-bit image to `uint8` **destroys quantitative intensity**. Segment with
cv2 if you must, then measure on the ORIGINAL array with
`skimage.measure.regionprops_table`. **Never measure intensity through cv2.**

```python
img8 = cv2.normalize(img16, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
```

## Contours

```python
contours, hierarchy = cv2.findContours(binary_u8, mode, method)
```
Returns **2 values** in OpenCV ≥ 4 (it returned 3 in OpenCV 3). Verified on both 4.13
and 5.0.

| Mode | Meaning |
|---|---|
| `cv2.RETR_EXTERNAL` | outermost contours only — what you usually want |
| `cv2.RETR_LIST` | all contours, no hierarchy |
| `cv2.RETR_CCOMP` | two-level hierarchy (outer + holes) |
| `cv2.RETR_TREE` | full nesting hierarchy |

| Method | Meaning |
|---|---|
| `cv2.CHAIN_APPROX_SIMPLE` | compresses straight runs to endpoints — default choice |
| `cv2.CHAIN_APPROX_NONE` | every boundary pixel |

**`CHAIN_APPROX_SIMPLE` breaks `fitEllipse` on rectangles.** A solid 16×16 square
compresses to exactly **4** contour points, and `cv2.fitEllipse` requires **≥ 5** — it
raises. With `CHAIN_APPROX_NONE` the same square yields 60 points and fits fine.
`arcLength` and `contourArea` are identical either way (60.0 and 225.0), so only the
point-count-sensitive fitters care.

If you need `fitEllipse` on possibly-polygonal objects, use `CHAIN_APPROX_NONE`, or
guard with `if len(contour) >= 5`.

### `contourArea` is NOT the pixel count

`contourArea` is the area of the **polygon through pixel centres**, so it undercounts a
filled region by roughly half a pixel on every edge.

Verified on a solid 16×16 square:

| Measure | Value |
|---|---|
| true pixel count | **256** |
| `cv2.contourArea` | **225.0** (= 15²) |
| `cv2.arcLength(c, True)` | 60.0 |

If you need the true pixel area, use `connectedComponentsWithStats` (which reports
`256`) or `skimage.measure.regionprops_table`. Use `contourArea` only for **shape
ratios** — circularity, solidity — where the bias mostly cancels.

### Contour order is not label order

`findContours` returns contours bottom-up, not in label order. Verified: a small square
at the top and a large one at the bottom come back **largest first**. Never assume
`contours[i]` corresponds to label `i+1`. Match by centroid or use
`connectedComponentsWithStats`.

### Shape descriptors

```python
area   = cv2.contourArea(c)
perim  = cv2.arcLength(c, closed=True)
circ   = 4 * np.pi * area / perim**2            # 1.0 = perfect circle
hull   = cv2.convexHull(c)
solid  = area / cv2.contourArea(hull)
(cx, cy), (w, h), angle = cv2.minAreaRect(c)    # rotated bounding box
(x, y), radius = cv2.minEnclosingCircle(c)
approx = cv2.approxPolyDP(c, epsilon=0.02 * perim, closed=True)
ellipse = cv2.fitEllipse(c)                     # needs >= 5 points
M = cv2.moments(c)                              # M['m00'] == contourArea(c)
```
`fitEllipse` raises on a contour with fewer than 5 points — guard it.

## `connectedComponentsWithStats` — true pixel areas

```python
n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_u8, connectivity=8)
# label 0 is BACKGROUND — always slice [1:]
areas = stats[1:, cv2.CC_STAT_AREA]
```
`stats` has 5 columns: `CC_STAT_LEFT, CC_STAT_TOP, CC_STAT_WIDTH, CC_STAT_HEIGHT,
CC_STAT_AREA` (indices 0–4). Verified: reports `[256, 400]` for 16×16 and 20×20 squares,
i.e. the exact pixel counts.

## Feature detection & matching

```python
orb  = cv2.ORB_create(nfeatures=2000)     # binary descriptors
sift = cv2.SIFT_create()                  # float descriptors; patent expired, ships in main
kp, des = orb.detectAndCompute(img_u8, None)
```

**The matcher norm must match the descriptor type**, or you get garbage matches with no
error:

| Detector | Descriptor | Norm |
|---|---|---|
| ORB, BRIEF, BRISK | binary | `cv2.NORM_HAMMING` |
| SIFT, SURF | float | `cv2.NORM_L2` |

```python
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
matches = sorted(bf.match(des1, des2), key=lambda m: m.distance)
```
`crossCheck=True` is a cheap, effective filter. `m.queryIdx` indexes `kp1`,
`m.trainIdx` indexes `kp2` — swapping them silently inverts the transform.

## Geometric transforms

```python
M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, ransacReprojThreshold=5.0)
warped  = cv2.warpPerspective(img, M, (width, height))     # note (W, H), not (H, W)

M2, inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts)   # rigid + scale, 2x3
warped2 = cv2.warpAffine(img, M2, (width, height))
```
- `findHomography` needs **≥ 4** point pairs; `estimateAffinePartial2D` needs ≥ 2.
- Point arrays must be `float32`, shaped `(N, 1, 2)`.
- `dsize` is `(width, height)` — the **reverse** of `img.shape[:2]`. Passing it backwards
  silently produces a transposed, cropped image.
- If the scene is a rigid translation of the same modality, prefer
  `skimage.registration.phase_cross_correlation` — far simpler and subpixel-accurate.

## Colour and IO

- **`cv2.imread` returns BGR.** Convert before handing to matplotlib or skimage:
  `rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)` (`COLOR_BGR2RGB == 4`).
- `cv2.imread(path, cv2.IMREAD_UNCHANGED)` preserves 16-bit and alpha;
  `cv2.IMREAD_GRAYSCALE` forces a single 8-bit channel.
- **`cv2.imwrite` picks the codec from the extension.** `.jpg` applies lossy JPEG with no
  warning. Write `.tif` or `.png` for anything that will be re-analysed.

## Headless: never call the GUI functions

The container has no display. **`cv2.imshow`, `cv2.waitKey` and `cv2.destroyAllWindows`
exist and will hang or crash the subprocess.** Save with `cv2.imwrite` or plot through
matplotlib.

## Files

| File | What it covers |
|---|---|
| `SKILL.md` | When to use cv2 vs skimage; the three gotchas in brief |
| `SCRIPT_API.md` | This file — dtype contract, contour semantics, matcher norms, transform shapes |
| `WORKFLOW_CONTOUR_SHAPE.py` | Binary/label mask → per-object shape descriptors CSV, using `connectedComponentsWithStats` for true areas |
| `WORKFLOW_FEATURE_REGISTRATION.py` | ORB + RANSAC homography to align two views; recovers a known transform |

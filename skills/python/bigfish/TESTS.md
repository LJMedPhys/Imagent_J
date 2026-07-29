# Big-FISH — running the test

`TEST_SPOT_DETECTION.py` is a self-contained validation: it synthesizes Gaussian-spot
fields with known ground truth and asserts that the **automatic** threshold recovers
them in 2D and 3D. It prints `RESULT: PASS` / `RESULT: FAIL` and exits nonzero on
failure.

## Against the live container

```bash
C=imagent_j-imagentj-1
docker cp skills/python/bigfish/TEST_SPOT_DETECTION.py "$C":/tmp/TEST_SPOT_DETECTION.py
docker exec "$C" /opt/conda/envs/local_imagent_J/bin/python /tmp/TEST_SPOT_DETECTION.py \
  ; echo "exit=$?"
```

No display and no JVM are needed — this is pure Python in the main env.

A `RuntimeWarning: divide by zero encountered in log` from `spot_detection.py` is
expected and benign (see `SCRIPT_API.md`).

## What it covers

| Check | Guards |
|---|---|
| 2D recall / false positives with `threshold=None` | the automatic threshold works at all |
| 3D recall / false positives on an anisotropic stack | `(z,y,x)` voxel size handling |
| Returned array shape is `(N,2)` / `(N,3)` | coordinate convention, pitfall B3 |
| `read_pixel_size_nm` decodes `ResolutionUnit=1` + ImageJ `unit` | pitfall B1 — the 3.2× calibration error seen on real data |
| `read_pixel_size_nm` returns `None` on an uncalibrated file | pitfall B1 — must raise, never guess |
| A 12×-too-large `spot_radius` collapses recall | pitfall B2 — the highest-impact silent failure |
| Segmented areas span the seeded size range (≥2×) | pitfall B4 — real extent, not stamped disks |
| Touching pairs split at the single-object radius | pitfall B4 — 25 merged regions → 50 objects |
| `fit_subpixel` lowers median localization error | pitfall B5 |
| Batch mode returns per-image results under one threshold | pitfall B7 |
| `get_elbow_values` agrees with `detect_spots` | the QC plot reflects the real choice |
| `exp(log_counts)` on the plateau equals the detected count | pitfall B9 (log-scaled return) |
| `decompose_dense` is a no-op without dense regions | safe default |
| `compute_snr_spots` still raises `AttributeError` | pitfall B11 — **fails loudly if upstream is fixed**, so the docs get updated |

## Expected output (abridged)

```
[test] 2D: truth=64 detected=64 auto_threshold=8.0
[test] 2D: TP=64 FP=0 FN=0 medianLocErr=0.345 px
[test] sub-pixel: medianLocErr 0.345 px -> 0.012 px
[test] 3D: truth=32 detected=32 auto_threshold=8.0
[test] 3D: TP=32 FP=0 FN=0 medianLocErr=0.000 px
RESULT: PASS
exit=0
```

## The workflows are runnable tests too

Both workflow scripts fall back to synthetic data when their configured inputs are
missing, so they run untouched:

```bash
docker exec -w /tmp "$C" /opt/conda/envs/local_imagent_J/bin/python WORKFLOW_SPOT_DETECTION.py
docker exec -w /tmp "$C" /opt/conda/envs/local_imagent_J/bin/python WORKFLOW_SPOTS_PER_CELL.py
docker exec -w /tmp "$C" /opt/conda/envs/local_imagent_J/bin/python WORKFLOW_SPOT_SEGMENTATION.py
```

`WORKFLOW_SPOT_SEGMENTATION.py` was additionally validated against a real
2048×2048 confocal image and an independent Fiji segmentation of the same file:
**54 objects (areas 21/104/578 px) vs the reference's 55 (12/115/847)**, with the
calibration read correctly as 322.2 nm/px and the object radius measured at
1836 nm.

## Requirements

`big-fish` (0.6.2) and its dep `mrc` in the main env (`local_imagent_J`). Declared in
`environment.yml`, so a rebuilt image has them; `pip install big-fish` adds them to a
running container.

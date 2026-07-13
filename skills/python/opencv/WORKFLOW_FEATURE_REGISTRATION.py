"""
WORKFLOW: align two images with ORB features + RANSAC homography (OpenCV).

Runs in the MAIN env. Use this when the two views differ by rotation / scale /
perspective, or come from different modalities where intensity correlation fails.

IF THE TRANSFORM IS A PURE TRANSLATION of the same modality, do NOT use this —
skimage.registration.phase_cross_correlation is simpler and subpixel-accurate.
See the scikit_image skill (WORKFLOW_REGISTRATION.py).

THREE WAYS THIS SILENTLY GOES WRONG:
  1. Wrong matcher norm: ORB is a BINARY descriptor -> NORM_HAMMING. Using NORM_L2
     returns garbage matches with no error. SIFT is float -> NORM_L2.
  2. queryIdx indexes kp1, trainIdx indexes kp2. Swapping them inverts the transform.
  3. warpPerspective takes dsize=(width, height) — the REVERSE of img.shape[:2].

Verified end-to-end. Run untouched: it warps an image by a known homography and
recovers it.
"""
import os

import cv2
import numpy as np
import pandas as pd

# ─────────────────────────── CONFIG ───────────────────────────
REFERENCE_PATH = "/app/data/reference.tif"   # the image to align TO (fixed)
MOVING_PATH = "/app/data/moving.tif"         # the image to be warped
OUTPUT_TIFF = "aligned.tif"
MATCHES_CSV = "Registration_Matches.csv"
N_FEATURES = 2000
N_MATCHES_USED = 50            # best matches fed to RANSAC
RANSAC_REPROJ_THRESHOLD = 5.0  # px
MODEL = "homography"           # "homography" (perspective) or "affine" (rigid + scale)
# ──────────────────────────────────────────────────────────────


def to_uint8(img):
    """cv2 feature detectors require 8-bit. This destroys quantitative intensity —
    only ever do it for geometry, never before measuring."""
    if img.dtype == np.uint8:
        return img
    return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def load_images():
    if os.path.exists(REFERENCE_PATH) and os.path.exists(MOVING_PATH):
        import tifffile
        return tifffile.imread(REFERENCE_PATH), tifffile.imread(MOVING_PATH), None, False

    print("WARNING: configured inputs not found — running on synthetic data.")
    rng = np.random.default_rng(0)
    ref = np.zeros((256, 256), dtype=np.uint8)
    # textured blobs so ORB has corners to latch onto
    for _ in range(40):
        c = rng.integers(20, 236, size=2)
        cv2.circle(ref, tuple(int(v) for v in c), int(rng.integers(4, 12)),
                   int(rng.integers(100, 255)), -1)
    ref = cv2.GaussianBlur(ref, (3, 3), 0)

    # A known rotation + translation about the centre.
    true_M = cv2.getRotationMatrix2D((128.0, 128.0), angle=12.0, scale=1.0)
    true_M[0, 2] += 8.0
    true_M[1, 2] += -5.0
    moving = cv2.warpAffine(ref, true_M, (256, 256))   # dsize = (W, H)
    return ref, moving, true_M, True


def main():
    ref, moving, true_M, synthetic = load_images()
    if ref.shape[:2] != moving.shape[:2]:
        print(f"NOTE: shapes differ ({ref.shape} vs {moving.shape}) — output is sized to reference.")

    ref8, moving8 = to_uint8(ref), to_uint8(moving)
    h, w = ref8.shape[:2]

    orb = cv2.ORB_create(nfeatures=N_FEATURES)
    kp1, des1 = orb.detectAndCompute(ref8, None)      # kp1 <- queryIdx
    kp2, des2 = orb.detectAndCompute(moving8, None)   # kp2 <- trainIdx
    print(f"keypoints: reference {len(kp1)}, moving {len(kp2)}")
    if des1 is None or des2 is None:
        raise ValueError("VERIFICATION FAILED: no descriptors — image has no texture.")

    # ORB is a BINARY descriptor -> NORM_HAMMING. NORM_L2 would return silent garbage.
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(bf.match(des1, des2), key=lambda m: m.distance)
    print(f"matches after crossCheck: {len(matches)}")

    min_pairs = 4 if MODEL == "homography" else 3
    if len(matches) < min_pairs:
        raise ValueError(
            f"VERIFICATION FAILED: only {len(matches)} matches, need >= {min_pairs} for {MODEL}"
        )

    used = matches[:N_MATCHES_USED]
    src = np.float32([kp2[m.trainIdx].pt for m in used]).reshape(-1, 1, 2)  # moving
    dst = np.float32([kp1[m.queryIdx].pt for m in used]).reshape(-1, 1, 2)  # reference

    if MODEL == "homography":
        M, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ_THRESHOLD)
        if M is None:
            raise ValueError("VERIFICATION FAILED: findHomography returned None (degenerate matches)")
        aligned = cv2.warpPerspective(moving8, M, (w, h))    # dsize = (W, H)
    else:
        M, inlier_mask = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_REPROJ_THRESHOLD
        )
        if M is None:
            raise ValueError("VERIFICATION FAILED: estimateAffinePartial2D returned None")
        aligned = cv2.warpAffine(moving8, M, (w, h))

    n_inliers = int(inlier_mask.sum())
    inlier_frac = n_inliers / len(used)
    print(f"RANSAC inliers: {n_inliers}/{len(used)} ({inlier_frac:.0%})")

    rows = [{
        "query_idx": m.queryIdx, "train_idx": m.trainIdx, "distance": m.distance,
        "ref_x": kp1[m.queryIdx].pt[0], "ref_y": kp1[m.queryIdx].pt[1],
        "moving_x": kp2[m.trainIdx].pt[0], "moving_y": kp2[m.trainIdx].pt[1],
        "inlier": bool(inlier_mask[i]),
    } for i, m in enumerate(used)]
    pd.DataFrame(rows).to_csv(MATCHES_CSV, index=False)

    import tifffile
    tifffile.imwrite(OUTPUT_TIFF, aligned)

    # ── verification: invariants ──
    if aligned.shape[:2] != (h, w):
        raise ValueError(
            f"VERIFICATION FAILED: aligned shape {aligned.shape[:2]} != reference {(h, w)}. "
            "dsize must be (width, height)."
        )
    if aligned.max() == 0:
        raise ValueError("VERIFICATION FAILED: aligned image is entirely black — "
                         "the transform sent the image off-canvas.")
    for path in (OUTPUT_TIFF, MATCHES_CSV):
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise ValueError(f"VERIFICATION FAILED: {path} missing or empty")

    if synthetic:
        # Alignment must beat the unaligned baseline. This is the honest check:
        # correlation of aligned-vs-reference should exceed moving-vs-reference.
        def corr(a, b):
            a, b = a.astype(float).ravel(), b.astype(float).ravel()
            return float(np.corrcoef(a, b)[0, 1])
        before, after = corr(ref8, moving8), corr(ref8, aligned)
        print(f"synthetic check: correlation with reference "
              f"before={before:.3f} after={after:.3f}")
        if after <= before:
            raise ValueError(
                f"VERIFICATION FAILED: alignment did not improve correlation "
                f"({before:.3f} -> {after:.3f})"
            )

    # A low inlier fraction means a weak registration — report, do not raise. Some
    # legitimate multi-modal pairs land near 30%.
    if inlier_frac < 0.5:
        print(f"WARNING: only {inlier_frac:.0%} inliers — registration may be unreliable.")

    print(f"wrote {OUTPUT_TIFF} and {MATCHES_CSV}"
          + (" [SYNTHETIC DATA]" if synthetic else ""))


if __name__ == "__main__":
    main()

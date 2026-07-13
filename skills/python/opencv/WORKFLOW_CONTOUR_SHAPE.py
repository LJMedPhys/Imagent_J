"""
WORKFLOW: binary/label mask -> per-object contour shape descriptors CSV (OpenCV).

Runs in the MAIN env. Use this when you need contour-polygon descriptors that
skimage does not provide: minAreaRect, convexHull solidity, approxPolyDP vertex
counts, minEnclosingCircle.

TWO THINGS OPENCV WILL NOT TELL YOU:
  1. cv2.contourArea is the polygon area through pixel CENTRES. A solid 16x16 square
     has 256 pixels but contourArea 225. True pixel areas come from
     connectedComponentsWithStats, which is what this script uses for `area_px`.
  2. findContours returns contours bottom-up, NOT in label order. This script matches
     each contour back to its component by centroid.

Verified end-to-end. Run untouched to measure synthetic objects.
"""
import os

import cv2
import numpy as np
import pandas as pd

# ─────────────────────────── CONFIG ───────────────────────────
MASK_PATH = "/app/data/labels.tif"   # label image OR binary mask
OUTPUT_CSV = "Shape_Descriptors.csv"
PIXEL_SIZE_UM = None                 # e.g. 0.325 from PROJECT STATE; None = report px
CONNECTIVITY = 8                     # 4 or 8
POLY_EPSILON_FRAC = 0.02             # approxPolyDP tolerance, as a fraction of perimeter
# ──────────────────────────────────────────────────────────────


def load_mask():
    if os.path.exists(MASK_PATH):
        import tifffile
        return tifffile.imread(MASK_PATH), False

    print("WARNING: configured input not found — running on synthetic data.")
    mask = np.zeros((160, 160), dtype=np.uint8)
    mask[10:26, 10:26] = 1                       # square, 256 px
    cv2.circle(mask, (100, 40), 15, 2, -1)       # circle
    cv2.ellipse(mask, (60, 120), (30, 12), 30, 0, 360, 3, -1)   # rotated ellipse
    return mask, True


def main():
    mask, synthetic = load_mask()
    print(f"mask {mask.shape} {mask.dtype}, {len(np.unique(mask)) - 1} object(s)")

    # cv2 wants uint8. A label image is binarised here on purpose: we re-derive the
    # objects with connectedComponents so that areas are TRUE pixel counts.
    binary = (mask > 0).astype(np.uint8) * 255

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=CONNECTIVITY
    )
    n_objects = n_labels - 1          # label 0 is background
    print(f"connected components: {n_objects}")
    if n_objects == 0:
        raise ValueError("VERIFICATION FAILED: mask contains no objects.")

    # findContours needs uint8/int32; uint16 raises cv2.error. Returns 2 values in cv2>=4.
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"contours found: {len(contours)}")

    # Contour order != label order. Match each contour to its component by centroid.
    def nearest_label(contour):
        M = cv2.moments(contour)
        if M["m00"] == 0:
            return None
        cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
        d = np.hypot(centroids[1:, 0] - cx, centroids[1:, 1] - cy)
        return int(np.argmin(d)) + 1

    rows = []
    for contour in contours:
        lbl = nearest_label(contour)
        if lbl is None:
            continue

        perim = cv2.arcLength(contour, closed=True)
        poly_area = cv2.contourArea(contour)          # polygon area, undercounts
        true_area = float(stats[lbl, cv2.CC_STAT_AREA])   # exact pixel count

        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        solidity = poly_area / hull_area if hull_area > 0 else np.nan
        circularity = 4 * np.pi * poly_area / (perim ** 2) if perim > 0 else np.nan

        (_, _), (w, h), angle = cv2.minAreaRect(contour)
        (_, _), radius = cv2.minEnclosingCircle(contour)
        approx = cv2.approxPolyDP(contour, POLY_EPSILON_FRAC * perim, closed=True)

        # fitEllipse needs >= 5 points. CHAIN_APPROX_SIMPLE compresses a rectangle to
        # exactly 4, so squares land here as NaN. Switch to CHAIN_APPROX_NONE if you
        # need ellipse fits on polygonal objects.
        if len(contour) >= 5:
            (_, _), (ell_minor, ell_major), ell_angle = cv2.fitEllipse(contour)
        else:
            ell_minor = ell_major = ell_angle = np.nan

        rows.append({
            "label": lbl,
            "area_px": true_area,               # from connectedComponents (exact)
            "contour_polygon_area": poly_area,  # from contourArea (undercounts)
            "perimeter_px": perim,
            "circularity": circularity,
            "solidity": solidity,
            "rect_major_px": max(w, h),
            "rect_minor_px": min(w, h),
            "rect_angle_deg": angle,
            "enclosing_radius_px": radius,
            "n_polygon_vertices": len(approx),
            "ellipse_major_px": ell_major,
            "ellipse_minor_px": ell_minor,
            "ellipse_angle_deg": ell_angle,
            "centroid_x": centroids[lbl, 0],
            "centroid_y": centroids[lbl, 1],
        })

    df = pd.DataFrame(rows).sort_values("label").reset_index(drop=True)

    if PIXEL_SIZE_UM is not None:
        df["area_um2"] = df["area_px"] * (PIXEL_SIZE_UM ** 2)
        for col in ("perimeter_px", "rect_major_px", "rect_minor_px",
                    "enclosing_radius_px", "ellipse_major_px", "ellipse_minor_px"):
            df[col.replace("_px", "_um")] = df[col] * PIXEL_SIZE_UM
        print(f"converted to microns with pixel size {PIXEL_SIZE_UM} um/px")
    else:
        print("WARNING: PIXEL_SIZE_UM is None — all sizes reported in PIXELS.")

    df.to_csv(OUTPUT_CSV, index=False)
    for _, r in df.iterrows():
        print(f"  label {int(r['label'])}: area_px={r['area_px']:.0f} "
              f"circularity={r['circularity']:.3f} solidity={r['solidity']:.3f}")

    # ── verification: definitional invariants only ──
    if len(df) != n_objects:
        raise ValueError(f"VERIFICATION FAILED: {len(df)} rows for {n_objects} objects")
    if df["label"].duplicated().any():
        raise ValueError("VERIFICATION FAILED: two contours mapped to the same component")
    if (df["area_px"] <= 0).any():
        raise ValueError("VERIFICATION FAILED: non-positive area")
    if (df["contour_polygon_area"] > df["area_px"] + 1e-6).any():
        raise ValueError("VERIFICATION FAILED: polygon area exceeds true pixel area")
    sol = df["solidity"].to_numpy()
    sol = sol[np.isfinite(sol)]
    if sol.size and (sol.min() < -1e-6 or sol.max() > 1.0000001):
        raise ValueError(f"VERIFICATION FAILED: solidity outside [0,1]: {sol}")
    if not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0:
        raise ValueError(f"VERIFICATION FAILED: {OUTPUT_CSV} missing or empty")

    n_unfittable = int(df["ellipse_major_px"].isna().sum())
    if n_unfittable:
        print(f"WARNING: {n_unfittable} object(s) have < 5 contour points, so ellipse_* is "
              f"NaN. CHAIN_APPROX_SIMPLE compresses rectangles to 4 points; use "
              f"CHAIN_APPROX_NONE if you need those fits.")

    print(f"wrote {OUTPUT_CSV}: {len(df)} objects"
          + (" [SYNTHETIC DATA]" if synthetic else ""))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Give a benchmark's input images opaque names, and keep the key for scoring.

WHY THIS EXISTS
---------------
BBBC005 filenames state the answer:

    SIMCEPImages_A03_C10_F1_s01_w1.TIF
                     ^^^^ the true cell count

In a five-repeat study of task 2, FIVE OF FIFTEEN runs reported RMSE of exactly
0.000 over 500 images. One of them had a mean Dice of 0.53 — genuinely poor
masks beside flawless counts, which is only possible if the counts did not come
from the masks. The agent read the filename. That is not cheating so much as
the obvious thing to do when the answer is written on the tin, and it silently
destroys the measurement: a third of the runs were scoring the parser, not the
segmentation.

So the input filenames must carry no information. This copies a dataset to new
names, records the mapping, and leaves the originals untouched.

TWO DETAILS THAT MATTER
-----------------------
* The order is SHUFFLED before numbering. Numbering the files in sorted order
  would preserve the original ordering, and in BBBC005 that ordering is by cell
  count — so img_0001 … img_0500 would still be a monotonic ladder of the
  answer. The shuffle seed is recorded so the mapping is reproducible.

* The mapping is written OUTSIDE the directory that gets mounted into the
  container. Putting it in the input folder would hand back exactly what was
  just removed.

The TIFF tags were checked for BBBC005 and carry no filename (no
ImageDescription, no PageName), so copying the bytes is enough. For a dataset
that does embed one, strip it before mounting — this script warns when it finds
one rather than silently copying it through.

Usage
-----
    scripts/anonymize_inputs.py --src ./BBBC005_500 --dst ./task2_inputs \
                                --mapping ./task2_mapping.csv
    # then point the study at --input-dir ./task2_inputs
    # and the analysis at --mapping ./task2_mapping.csv
"""

import argparse
import csv
import hashlib
import os
import random
import re
import shutil
import sys

# Metadata this dataset writes into its filenames, recovered into the mapping so
# scoring still has it. C = true cell count, F = focus blur level.
BBBC005 = re.compile(r"_C(\d+)_F(\d+)_s(\d+)_w(\d+)", re.I)

IMG_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg")


def has_embedded_name(path):
    """True if the TIFF carries a filename-ish tag that would leak anyway."""
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            for page in tf.pages[:1]:
                for tag in page.tags.values():
                    if tag.name in ("ImageDescription", "PageName", "DocumentName"):
                        if str(tag.value).strip():
                            return tag.name, str(tag.value)[:60]
    except Exception:
        pass
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", required=True, help="the original input images")
    p.add_argument("--dst", required=True, help="where to write the renamed copies")
    p.add_argument("--mapping", required=True, help="CSV key; keep it OUT of --dst")
    p.add_argument("--prefix", default="img", help="new filename prefix (default: img)")
    p.add_argument("--seed", type=int, default=20260923,
                   help="shuffle seed, recorded in the mapping for reproducibility")
    p.add_argument("--link", action="store_true",
                   help="hard-link instead of copying (same filesystem only)")
    args = p.parse_args()

    src, dst = os.path.abspath(args.src), os.path.abspath(args.dst)
    if os.path.abspath(args.mapping).startswith(dst + os.sep):
        sys.exit("--mapping must NOT live inside --dst: that directory is mounted "
                 "into the container, and the key would hand back what was removed.")
    files = sorted(f for f in os.listdir(src)
                   if f.lower().endswith(IMG_EXT) and os.path.isfile(os.path.join(src, f)))
    if not files:
        sys.exit(f"no images under {src}")

    # Shuffle before numbering: sorted order would preserve the original ordering,
    # which in BBBC005 is itself a ladder of the answer.
    order = list(files)
    random.Random(args.seed).shuffle(order)

    os.makedirs(dst, exist_ok=True)
    width = max(4, len(str(len(order))))
    rows, warned = [], 0
    for i, original in enumerate(order, start=1):
        ext = os.path.splitext(original)[1].lower()
        ext = ".tif" if ext in (".tif", ".tiff") else ext
        new = f"{args.prefix}_{i:0{width}d}{ext}"
        s, d = os.path.join(src, original), os.path.join(dst, new)
        if args.link:
            if os.path.exists(d):
                os.unlink(d)
            os.link(s, d)
        else:
            shutil.copy2(s, d)

        leak = has_embedded_name(s)
        if leak:
            warned += 1
            if warned <= 3:
                print(f"  !! {original}: TIFF tag {leak[0]} = {leak[1]!r} — this "
                      f"travels with the pixels; strip it before mounting")

        m = BBBC005.search(original)
        rows.append({
            "new_name": new,
            "original_name": original,
            "true_count": int(m.group(1)) if m else "",
            "focus": int(m.group(2)) if m else "",
            "sample": int(m.group(3)) if m else "",
            "channel": int(m.group(4)) if m else "",
            "sha1": hashlib.sha1(open(s, "rb").read()).hexdigest()[:12],
        })

    with open(args.mapping, "w", newline="") as fh:
        fh.write(f"# anonymised from {src}\n")
        fh.write(f"# shuffle seed {args.seed}; {len(rows)} images\n")
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    parsed = sum(1 for r in rows if r["true_count"] != "")
    print(f"\n{len(rows)} image(s) -> {dst}")
    print(f"mapping -> {args.mapping}   ({parsed} with a recovered true count)")
    if warned:
        print(f"!! {warned} file(s) carry a filename in their TIFF tags — the rename "
              f"alone does not hide those")
    print(f"\nmount {dst} as the study input; keep {args.mapping} out of the container.")


if __name__ == "__main__":
    main()

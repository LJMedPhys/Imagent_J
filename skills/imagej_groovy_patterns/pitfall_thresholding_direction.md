# `IJ.setAutoThreshold` direction — never hardcode `" dark"`

**Symptom:** mask is inverted; downstream measurements report 0 objects or
the mask fills the entire frame.

**Cause:** `IJ.setAutoThreshold(imp, "Otsu dark")` and
`IJ.setAutoThreshold(imp, "Otsu")` produce **opposite** masks. The `" dark"`
suffix means "background is dark" → foreground = bright pixels above the
threshold. Without it, foreground = dark pixels below the threshold.

| Image type | Suffix |
|------------|--------|
| Fluorescence (bright signal on black BG) | `"Otsu dark"` |
| Brightfield / H&E / phase-contrast (dark cells on bright BG) | `"Otsu"` |

**Fix — pick the suffix at runtime from image stats:**

```groovy
import ij.measure.Measurements
// MEDIAN must be requested: plain imp.getStatistics() leaves s.median = 0,
// which makes the test below always pick " dark".
def s = imp.getStatistics(Measurements.MEDIAN | Measurements.MIN_MAX)
boolean brightObjects = s.median <= (s.min + s.max) / 2.0   // in PIXEL values
// " dark" refers to the DISPLAYED image, so an inverting LUT flips it.
boolean darkSuffix = brightObjects ^ imp.isInvertedLut()
IJ.setAutoThreshold(imp, "Otsu" + (darkSuffix ? " dark" : ""))
IJ.run(imp, "Convert to Mask", "")
```

Verified 2026-11-04 (Fiji 2.16.0/1.54p): blobs.gif (inverting LUT, high-valued
blobs) needs `"Otsu"` → 62 blobs; `"Otsu dark"` gives 1 object covering 66 % of
the frame. A normal-LUT fluorescence frame needs `"Otsu dark"`. The previous
version of this rule (no MEDIAN flag, no LUT flip) returned `" dark"` for both.

If PROJECT STATE includes `background_mode` (`"dark"` / `"bright"`), use it in
place of `brightObjects` — it was computed from the full image, not the active
slice — but keep the inverted-LUT flip: it is measured on pixel values too.

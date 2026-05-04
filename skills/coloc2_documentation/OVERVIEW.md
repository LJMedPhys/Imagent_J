# Coloc 2 Overview

Coloc 2 performs pixel-intensity correlation analysis between two 2D or 3D images. It replaces the deprecated "Colocalization Threshold" and "Colocalization Test" plugins.

### Mathematical Foundations
1. **Pearson’s (PCC):** Measures linear correlation of intensities. Range: -1 (perfect inverse) to 1 (perfect colocalization). 0 is random.
2. **Manders’ (M1/M2):** Measures the fraction of total intensity in channel A that overlaps with channel B. Unlike Pearson, it is sensitive to absolute intensity and requires thresholding.
3. **Costes’ Significance Test:** Determines if the measured PCC is significantly better than a PCC derived from randomized versions of the same images. A **P-Value > 0.95** is considered statistically significant.
4. **Li's ICQ:** Dependent on whether intensities vary together from the mean. Range: -0.5 to +0.5.

### Input Constraints
- **Geometry:** Images must have identical X, Y, and Z dimensions.
- **Preprocessing:** Background subtraction is highly recommended before running Coloc 2 to avoid inflated correlation values.
- **ROI:** Supports 2D and 3D ROIs. If an ROI is active, only pixels within the ROI are used.
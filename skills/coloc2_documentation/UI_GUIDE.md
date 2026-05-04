# Coloc 2 UI Guide

### Launching the Plugin
Navigate to **Analyze > Colocalization > Coloc 2**.

### GUI Field Explanations
- **Image 1/2:** Dropdown menus to select open images.
- **ROI or Mask:** Allows limiting analysis to a specific organelle or cell region.
- **Threshold Regression:**
  - **Costes:** Automatically finds the threshold below which correlation is no longer positive.
- **PSF Width:** Crucial for the Costes Significance test. It defines the size of the blocks used for image randomization.
- **Number of Iterations:** Number of times the image is randomized. Higher numbers (100+) provide more accurate P-values but take longer.

### Output Windows
- **Log:** Contains text-based results (PCC, Manders, Costes P-Value).
- **Result Analysis:** A large image panel containing the 2D scatterplot, the Costes mask, and linear regression plots (only if `display_images` is checked).
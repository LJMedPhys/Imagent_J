<!--r:72890e84 seen:1 lang:Python chash:2d2900fb kw:big-fish,bigfish,bigfish.detection,bigfish.stack,dapi preview,radius sweep,elbow threshold,nearest-neighbor diagnostics-->
- Big-FISH DAPI preview with radius sweep QC  [inputs: Validated DAPI MIP TIFF path, output directory, pixel size in microns, crop size, target crop levels]
  Stage 0 Big-FISH DAPI preview on deterministic 1024 px low/medium/high crops from a validated MIP. The script performs in-memory Gaussian background flattening, estimates dot radius from the data, runs a compact radius sweep with automatic elbow thresholds, and writes QC overlays plus nearest-neighbor diagnostics and a provisional radius recommendation without full-image counting.
  SCRIPT: /app/data/learned/recipes/code/big_fish_dapi_preview_with_radius_sweep_qc.py
<!--r:c5d347b8 seen:1 lang:Python chash:fca51f66 kw:labkit dapi mask validation,mask polarity check,foreground background intensity comparison,connected components diagnostics,8-connectivity,area quantiles,dapi qc overlays,skimage measure segmentation-->
- Labkit DAPI mask polarity validation and component QC  [inputs: Labkit DAPI mask TIFF, raw DAPI MIP TIFF, output directory]
  Validates Labkit-generated DAPI mask polarity by comparing raw-intensity foreground/background means, then computes 8-connectivity component diagnostics with area quantiles, single-pixel and border fractions. Saves per-component and summary CSVs plus sparse/typical/dense QC overlays and a full-resolution boundary overlay.
  SCRIPT: /app/data/learned/recipes/code/labkit_dapi_mask_polarity_validation_and_component.py
<!--r:3a451d53 seen:1 lang:Python chash:30ad1b51 kw:labkit mask polarity,647 mask validation,connected component qc,raw intensity comparison,macrophage segmentation,tifffile,skimage.measure,skimage.segmentation-->
- Labkit 647 mask polarity validation and component QC  [inputs: Labkit macrophage_647 mask TIFF and corresponding raw 647 MIP TIFF; outputs a validation QC folder with per-component CSV, summary CSV, and overlay images.]
  Validates Labkit-generated macrophage 647 mask polarity by comparing mask coverage against raw 647 intensity, reports 8-connected component diagnostics in pixels and µm², and saves deterministic QC overlays without modifying the mask.
  SCRIPT: /app/data/learned/recipes/code/labkit_647_mask_polarity_validation_and_component_.py
<!--r:3ec2b5bb seen:1 lang:Python chash:983a7c95 kw:labkit merge preview,morphological closing,binary mask qc,macrophage 647,component merging,mask cleanup,overlay comparison,closing radius-->
- Labkit 647 merge preview with conservative closing QC  [inputs: Approved binary Labkit macrophage-647 mask TIFF, raw 647 MIP TIFF, output directory]
  Stage-0 preview for a Labkit macrophage-647 binary mask: generate conservative closing candidates at 1 and 2 px, preserve the original mask, quantify foreground/component-merging changes, and export sparse/typical/dense side-by-side QC overlays plus a comparison CSV.
  SCRIPT: /app/data/learned/recipes/code/labkit_647_merge_preview_with_conservative_closing.py
<!--r:fc1b0cf8 seen:1 lang:Python chash:6ad43a38 kw:tiff stack verification,maximum intensity projection check,mip validation,raw-to-projection comparison,multipage tiff plane reading,tifffile memmap,pixelwise validation-->
- Validate raw TIFF stacks against supplied MIPs  [inputs: 15-plane raw TIFF stack and corresponding MIP TIFF for each channel; output data directory]
  Checks ch00/ch01 raw TIFF stacks against supplied 2D maximum-intensity projections using sequential plane reads or a read-only memory map where supported. Computes exact pixel-comparison metrics in bounded chunks and saves data/MIP_Validation.csv without modifying source images.
  SCRIPT: /app/data/learned/recipes/code/validate_raw_tiff_stacks_against_supplied_mips.py

<!--r:8fb9648b seen:1 lang:Python chash:3f1b400b kw:representative microscopy crops,paired channel mip sampling,signal quantile crop selection,labkit training review tiles,deterministic nonoverlapping patches,tifffile uint16 export,sample crop manifest,maximum intensity projection subimages-->
- Deterministic paired MIP sample crops for Labkit review  [inputs: Paired ch00/ch01 MIP TIFFs; configurable crop size, crop count, pixel size, output directory, and source paths.]
  Selects four deterministic, non-overlapping 512×512 paired maximum-intensity-projection crops spanning signal-score quantiles. Exports unchanged calibrated uint16 TIFFs and a CSV manifest with crop origins for Labkit review; performs no segmentation or quantification.
  SCRIPT: /app/data/learned/recipes/code/deterministic_paired_mip_sample_crops_for_labkit_r.py
<!--r:23216356 seen:2 lang:Python chash:1c99ba0d kw:tiff maximum projection validation,compare mip to raw stack,plane-wise z projection,paired microscopy review crops,native-resolution crop export,calibrated projection preview,tifffile stack verification-->
- Verify TIFF MIPs and prepare paired review crops  [inputs: Source directory with two 15-plane uint16 TIFF stacks and corresponding supplied MIPs; project/output directory and configured pixel size.]
  Recomputes two raw uint16 TIFF maximum projections plane-by-plane, exact-compares supplied MIPs, and exports calibrated projections, RGB QC previews, paired native-resolution crops, verification and crop manifests, and an I/O report. This is a preprocessing/review workflow only; it does not segment or quantify objects.
  SCRIPT: /app/data/learned/recipes/code/verify_tiff_mips_and_prepare_paired_review_crops.py


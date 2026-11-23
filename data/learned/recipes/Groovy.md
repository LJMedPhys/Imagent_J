<!--r:7758e5ac seen:1 lang:Groovy chash:02846ea0 kw:tiffdecoder,fileinfo,tiff metadata check,open one slice,downsample preview,large stack,imagej opener,paired channels-->
- Validate paired TIFF metadata with TiffDecoder and preview one slice  [inputs: Two TIFF file paths; optional downsample factor for the representative slice.]
  Validate paired TIFF metadata without loading full stacks by reading FileInfo with TiffDecoder, then open only one representative slice for a downsampled preview. Useful when checking matched channels or large volumes that would otherwise exhaust memory.
  SCRIPT: /app/data/learned/recipes/code/validate_paired_tiff_metadata_with_tiffdecoder_and.groovy
<!--r:a7fe8981 seen:1 lang:Groovy chash:c25e297b kw:stardist,stardist2d,ij.getimage,imageplus conversion,dataset wrap,batch-safe,headless,imagejfunctions-->
- StarDist preview batch-safe label conversion  [inputs: StarDist label output from StarDist2D predict workflow; crop/sample identifier for naming the converted image]
  Makes a StarDist preview script safe for batch/headless runs by avoiding IJ.getImage/UI dependencies and converting StarDist label output directly into an ImagePlus. Useful when the plugin returns either an ImagePlus or a Dataset.
  SCRIPT: /app/data/learned/recipes/code/stardist_preview_batch_safe_label_conversion.groovy
<!--r:3109be74 seen:1 lang:Groovy chash:cd29069d kw:compare tiff metadata,inspect mip images,paired image compatibility,pixel calibration check,image dimensions report,tiffdecoder opener,imagej tiff readability-->
- Compare MIP TIFF metadata and report  [inputs: Two MIP TIFF paths, output directory, calibration tolerance.]
  Performs a read-only check of two existing MIP TIFFs for readability, XY dimensions, bit depth, C/Z/T dimensions, and pixel calibration, then displays both originals and writes a text report. Matching metadata does not establish biological registration.
  SCRIPT: /app/data/learned/recipes/code/compare_mip_tiff_metadata_and_report.groovy
<!--r:a9718ea3 seen:1 lang:Groovy chash:e482e0d6 kw:paired image crops,pilot crop selection,spatially separated rois,channel crop matching,review montage,crop manifest csv,fiji groovy-->
- Prepare paired pilot crops and montage  [inputs: Two paired MIP TIFF paths, output directory, crop layout/size and separation settings configured in the script.]
  Creates spatially separated paired crops from two MIP channels and exports a review montage with a crop manifest. Intended for preparing a small, reviewable pilot set from matched images.
  SCRIPT: /app/data/learned/recipes/code/prepare_paired_pilot_crops_and_montage.groovy


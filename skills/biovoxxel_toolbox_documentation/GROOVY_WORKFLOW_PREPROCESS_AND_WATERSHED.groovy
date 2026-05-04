#@ File (label = "Input image", value = "/data/example_1.tif") inputFile
#@ File (label = "Output directory", style = "directory", value = "/data/biovoxxel_validation/workflow_output") outputDir
#@ Double (label = "Threshold blur sigma", value = 2.0, min = 0.0) thresholdBlurSigma
#@ String (label = "Auto-threshold method", choices = {"Default", "Otsu", "Huang", "IsoData", "Li", "MaxEntropy", "Mean", "MinError", "Minimum", "Moments", "Percentile", "RenyiEntropy", "Shanbhag", "Triangle", "Yen"}, value = "Otsu") thresholdMethod
#@ Boolean (label = "Fill holes after threshold", value = true) fillHoles
#@ String (label = "EDM binary operation", choices = {"open", "close", "erode", "dilate"}, value = "open") edmOperation
#@ Integer (label = "EDM iterations", value = 1, min = 1) edmIterations
#@ Boolean (label = "Quit Fiji when done", value = false) quitWhenDone

import ij.IJ
import ij.ImagePlus

/*
 * BioVoxxel Toolbox - Preprocess and watershed workflow
 *
 * PURPOSE:
 *   1. Open one grayscale image from disk
 *   2. Threshold the image to a binary mask
 *   3. Clean the mask with BioVoxxel EDM Binary Operations
 *   4. Separate touching objects with BioVoxxel Watershed Irregular Features
 *   5. Save the intermediate and final TIFF outputs
 *
 * REQUIRED INPUTS:
 *   inputFile             - grayscale image to process
 *   outputDir             - directory for TIFF outputs
 *   thresholdBlurSigma    - additional Gaussian blur before thresholding
 *   thresholdMethod       - ImageJ auto-threshold algorithm (applied with "dark" background)
 *   fillHoles             - run Fill Holes after thresholding (default true; disable if hollow interiors are meaningful)
 *   edmOperation          - one of open, close, erode, or dilate
 *   edmIterations         - number of EDM morphology iterations
 *
 * IMPORTANT:
 *   - BioVoxxel Toolbox must already be installed in Fiji.
 *   - Use a fresh or empty output directory, or at least a path where these files do not already exist.
 *   - This validated path assumes bright objects on a dark background.
 */

String stem(String filename) {
    int dot = filename.lastIndexOf(".")
    return dot > 0 ? filename.substring(0, dot) : filename
}

void ensureTargetDoesNotExist(File file) {
    if (file.exists()) {
        throw new IllegalArgumentException("Output file already exists: " + file.absolutePath)
    }
}

void saveImage(ImagePlus imp, File outputFile) {
    ensureTargetDoesNotExist(outputFile)
    IJ.saveAsTiff(imp, outputFile.absolutePath)
    if (!outputFile.exists() || outputFile.length() == 0) {
        throw new IllegalStateException("Failed to write TIFF: " + outputFile.absolutePath)
    }
}

void closeImageIfOpen(ImagePlus imp) {
    if (imp != null) {
        imp.changes = false
        imp.close()
    }
}

if (!inputFile.exists()) {
    throw new IllegalArgumentException("Input image not found: " + inputFile.absolutePath)
}
if (outputDir == null) {
    throw new IllegalArgumentException("Output directory must be provided")
}
outputDir.mkdirs()
if (!outputDir.isDirectory()) {
    throw new IllegalArgumentException("Could not create output directory: " + outputDir.absolutePath)
}

String baseName = stem(inputFile.getName())
ImagePlus sourceImp = null
ImagePlus maskImp = null
ImagePlus edmImp = null
ImagePlus watershedImp = null

try {
    sourceImp = IJ.openImage(inputFile.absolutePath)
    if (sourceImp == null) {
        throw new IllegalStateException("Could not open input image: " + inputFile.absolutePath)
    }

    maskImp = sourceImp.duplicate()
    maskImp.setTitle(baseName + "_binary_mask")
    if (maskImp.getBitDepth() != 8) {
        IJ.run(maskImp, "8-bit", "")
    }
    if (thresholdBlurSigma > 0) {
        IJ.run(maskImp, "Gaussian Blur...", "sigma=" + thresholdBlurSigma)
    }
    IJ.setAutoThreshold(maskImp, thresholdMethod + " dark")
    IJ.run(maskImp, "Convert to Mask", "")
    if (fillHoles) {
        IJ.run(maskImp, "Fill Holes", "")
    }
    saveImage(maskImp, new File(outputDir, baseName + "_binary_mask.tif"))

    edmImp = maskImp.duplicate()
    edmImp.setTitle(baseName + "_edm_mask")
    IJ.run(edmImp, "EDM Binary Operations",
        "iterations=" + edmIterations + " operation=" + edmOperation)
    saveImage(edmImp, new File(outputDir, baseName + "_edm_mask.tif"))

    watershedImp = edmImp.duplicate()
    watershedImp.setTitle(baseName + "_watershed_mask")
    IJ.run(watershedImp, "Watershed Irregular Features",
        "erosion=1 convexity_threshold=0 separator_size=0-Infinity")
    saveImage(watershedImp, new File(outputDir, baseName + "_watershed_mask.tif"))
}
finally {
    closeImageIfOpen(watershedImp)
    closeImageIfOpen(edmImp)
    closeImageIfOpen(maskImp)
    closeImageIfOpen(sourceImp)
}

if (quitWhenDone) {
    System.exit(0)
}

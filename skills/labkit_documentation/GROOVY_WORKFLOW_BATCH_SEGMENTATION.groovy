// These #@ lines inject Fiji services; they must stay at the top of the file.
#@ CommandService command

import ij.IJ
import ij.ImagePlus
import java.io.File
import sc.fiji.labkit.ui.plugin.SegmentImageWithLabkitIJ1Plugin

/*
 * Labkit — Batch segmentation with a saved classifier
 *
 * PURPOSE:
 *   1. Open an image from disk
 *   2. Apply a previously saved Labkit classifier
 *   3. Save the segmentation result as TIFF
 *   4. Close the image windows created by the workflow
 *
 * REQUIRED INPUTS:
 *   INPUT_IMAGE     - absolute path to the image to segment
 *   CLASSIFIER_FILE - absolute path to a Labkit .classifier file created in the GUI
 *   OUTPUT_TIFF     - absolute path to the TIFF that will be written
 *
 * GROOVY CALL USED IN THIS SCRIPT:
 *   command.run(SegmentImageWithLabkitIJ1Plugin, true,
 *       "input",          imp,
 *       "segmenter_file", new File(CLASSIFIER_FILE),
 *       "use_gpu",        false
 *   ).get()
 *
 * IMPORTANT:
 *   - This workflow intentionally uses a classifier path without spaces.
 *   - The classifier must already exist. This script does not train one.
 *   - This script uses the Groovy plugin call documented in GROOVY_API.md.
 */

String INPUT_IMAGE     = "/data/example_1.tif"
String CLASSIFIER_FILE = "/data/labkit_validation/example_1.classifier"
String OUTPUT_TIFF     = "/data/labkit_validation/example_1-segmentation.tif"

void closeImageIfOpen(ImagePlus imp) {
    if (imp != null) {
        imp.changes = false
        imp.close()
    }
}

File inputFile = new File(INPUT_IMAGE)
File classifierFile = new File(CLASSIFIER_FILE)
File outputFile = new File(OUTPUT_TIFF)

if (!inputFile.exists()) {
    IJ.error("Labkit Workflow", "Input image not found:\n" + INPUT_IMAGE)
    return
}
if (!classifierFile.exists()) {
    IJ.error("Labkit Workflow", "Classifier file not found:\n" + CLASSIFIER_FILE)
    return
}
if (CLASSIFIER_FILE.contains(" ")) {
    IJ.error("Labkit Workflow",
        "Classifier path contains spaces.\n" +
        "This workflow requires a classifier path without spaces.")
    return
}
outputFile.getParentFile()?.mkdirs()

IJ.log("Labkit batch segmentation")
IJ.log("Input      : " + INPUT_IMAGE)
IJ.log("Classifier : " + CLASSIFIER_FILE)
IJ.log("Output     : " + OUTPUT_TIFF)

ImagePlus sourceImp = IJ.openImage(INPUT_IMAGE)
if (sourceImp == null) {
    IJ.error("Labkit Workflow", "Could not open input image:\n" + INPUT_IMAGE)
    return
}
sourceImp.show()

def module = command.run(SegmentImageWithLabkitIJ1Plugin, true,
    "input",          sourceImp,
    "segmenter_file", classifierFile,
    "use_gpu",        false
).get()

ImagePlus resultImp = module.getOutput("output")
if (resultImp == null) {
    closeImageIfOpen(sourceImp)
    IJ.error("Labkit Workflow",
        "Labkit returned no output image.")
    return
}

IJ.saveAs(resultImp, "Tiff", OUTPUT_TIFF)
IJ.log("Saved segmentation: " + OUTPUT_TIFF)

closeImageIfOpen(resultImp)
closeImageIfOpen(sourceImp)

IJ.log("Labkit workflow complete")

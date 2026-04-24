/**
 * DeepImageJ - brightfield_nuclei segmentation workflow
 *
 * Run this in the Fiji Script Editor with Language: Groovy.
 *
 * PURPOSE:
 *   1. Run the local DeepImageJ model `brightfield_nuclei` on the active image
 *   2. Capture the main prediction window opened by DeepImageJ
 *   3. Save the prediction as a TIFF
 *
 * INPUT:
 *   - An open active image compatible with the model
 *   - If no image is open, the script falls back to the packaged sample image:
 *       /opt/Fiji.app/models/brightfield_nuclei/sample_input_0.tif
 *
 * OUTPUT:
 *   - <input-title>-deepimagej-instance.tif
 *
 * REQUIREMENTS:
 *   - Fiji with DeepImageJ installed
 *   - Local model bundle at /opt/Fiji.app/models/brightfield_nuclei
 */

import ij.IJ
import ij.ImagePlus
import ij.WindowManager

// ---------------------------- PARAMETERS -----------------------------------
String MODEL_NAME = "brightfield_nuclei"
String MODEL_DIR = "/opt/Fiji.app/models"
String FORMAT = "pytorch"
String PREPROCESSING = "instanseg_preprocess.ijm"
String POSTPROCESSING = "instanseg_postprocess.ijm"
String AXES = "C,Y,X"
String TILE = "3,256,256"
String LOGGING = "debug"
String FALLBACK_SAMPLE_INPUT = MODEL_DIR + "/" + MODEL_NAME + "/sample_input_0.tif"

// Leave empty to save next to the input image when possible.
String OUTPUT_DIR = ""
// ---------------------------------------------------------------------------

ImagePlus input = WindowManager.getCurrentImage()
if (input == null) {
    File fallbackInput = new File(FALLBACK_SAMPLE_INPUT)
    if (!fallbackInput.isFile()) {
        IJ.error("No image is open.\nOpen an image before running this workflow.")
        return
    }
    IJ.log("No active image found. Opening packaged sample input: " + FALLBACK_SAMPLE_INPUT)
    input = IJ.openImage(FALLBACK_SAMPLE_INPUT)
    if (input == null) {
        IJ.error("Could not open fallback sample input:\n" + FALLBACK_SAMPLE_INPUT)
        return
    }
    input.show()
}

String baseTitle = input.getTitle().replaceAll(/\.[^.]+$/, "")
String resolvedOutputDir = OUTPUT_DIR?.trim()
if (!resolvedOutputDir) {
    resolvedOutputDir = input.getOriginalFileInfo()?.directory
}
if (!resolvedOutputDir) {
    resolvedOutputDir = IJ.getDirectory("imagej")
}

File outputFolder = new File(resolvedOutputDir)
if (!outputFolder.exists()) {
    outputFolder.mkdirs()
}

def beforeIds = (WindowManager.getIDList() ?: new int[0]) as List

String args =
    "model=${MODEL_NAME} " +
    "format=${FORMAT} " +
    "preprocessing=${PREPROCESSING} " +
    "postprocessing=${POSTPROCESSING} " +
    "axes=${AXES} " +
    "tile=${TILE} " +
    "logging=${LOGGING} " +
    "model_dir=${MODEL_DIR}"

IJ.log("Running DeepImageJ model: " + MODEL_NAME)
IJ.log("Arguments: " + args)
IJ.run("DeepImageJ Run", args)

def afterIds = (WindowManager.getIDList() ?: new int[0]) as List
def newIds = afterIds.findAll { !beforeIds.contains(it) }
def outputs = newIds.collect { WindowManager.getImage(it) }.findAll { it != null }

if (outputs.isEmpty()) {
    IJ.error("DeepImageJ did not open any new output windows.")
    return
}

ImagePlus output = outputs.find { it.getTitle().contains("_instance_") }
if (output == null) {
    output = outputs.find { !it.getTitle().equalsIgnoreCase("Visited") }
}
if (output == null) {
    output = outputs[0]
}

String outputPath = new File(outputFolder, baseTitle + "-deepimagej-instance.tif").absolutePath
IJ.saveAsTiff(output, outputPath)

IJ.log("Saved DeepImageJ output: " + outputPath)
IJ.log("Primary output window: " + output.getTitle())

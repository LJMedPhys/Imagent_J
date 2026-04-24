// Register a 2D source image to a 2D target image with bUnwarpJ, save the direct result,
// export elastic transformation files, and optionally save inverse outputs and a re-applied source copy.
#@ File (label = "Target image", value = "/data/example_1.tif") targetFile
#@ File (label = "Source image", value = "/data/example_1.tif") sourceFile
#@ String (choices = {"Accurate", "Fast", "Mono"}, label = "Registration mode", value = "Accurate") registrationMode
#@ Integer (label = "Image subsample factor", min = "0", max = "7", value = 0) imageSubsampleFactor
#@ String (choices = {"Very Coarse", "Coarse", "Fine", "Very Fine"}, label = "Initial deformation", value = "Coarse") initialDeformation
#@ String (choices = {"Very Coarse", "Coarse", "Fine", "Very Fine", "Super Fine"}, label = "Final deformation", value = "Very Fine") finalDeformation
#@ Double (label = "Divergence weight", value = 0.0) divergenceWeight
#@ Double (label = "Curl weight", value = 0.0) curlWeight
#@ Double (label = "Landmark weight", value = 0.0) landmarkWeight
#@ Double (label = "Image weight", value = 1.0) imageWeight
#@ Double (label = "Consistency weight", value = 10.0) consistencyWeight
#@ Double (label = "Stop threshold", value = 0.01) stopThreshold
#@ File (label = "Registered source output", style = "save", value = "/data/bunwarpj_validation/registered_source.tif") registeredSourceOutputFile
#@ File (label = "Direct elastic transform output", style = "save", value = "/data/bunwarpj_validation/direct_transform.txt") directTransformOutputFile
#@ Boolean (label = "Save inverse outputs for bidirectional modes", value = true) saveInverseOutputs
#@ File (label = "Registered target output", style = "save", value = "/data/bunwarpj_validation/registered_target.tif") registeredTargetOutputFile
#@ File (label = "Inverse elastic transform output", style = "save", value = "/data/bunwarpj_validation/inverse_transform.txt") inverseTransformOutputFile
#@ Boolean (label = "Save a re-applied source copy from the direct transform", value = true) saveReappliedSourceCopy
#@ File (label = "Re-applied source output", style = "save", value = "/data/bunwarpj_validation/reapplied_source.tif") reappliedSourceOutputFile

import bunwarpj.Param
import bunwarpj.bUnwarpJ_
import ij.IJ
import ij.ImagePlus
import ij.plugin.Duplicator

final Map<String, Integer> MODE_CODES = [
    "Fast": 0,
    "Accurate": 1,
    "Mono": 2
]

final Map<String, Integer> SCALE_CODES = [
    "Very Coarse": 0,
    "Coarse": 1,
    "Fine": 2,
    "Very Fine": 3,
    "Super Fine": 4
]

void requireFreshOutput(File file, String label) {
    if (file == null) {
        throw new IllegalArgumentException(label + " must be provided")
    }
    file.parentFile?.mkdirs()
    if (file.exists()) {
        throw new IllegalArgumentException(label + " already exists: " + file.absolutePath)
    }
}

void verifySavedFile(File file, String label) {
    if (file == null || !file.exists() || file.length() == 0L) {
        throw new IllegalStateException(label + " was not created: " + file)
    }
}

ImagePlus openSinglePlaneImage(File file, String label) {
    if (file == null || !file.exists() || !file.isFile()) {
        throw new IllegalArgumentException(label + " not found: " + file)
    }
    def imp = IJ.openImage(file.absolutePath)
    if (imp == null) {
        throw new IllegalStateException("Could not open " + label + ": " + file.absolutePath)
    }
    if (imp.getNSlices() != 1) {
        throw new IllegalArgumentException(
            label + " must be a single-plane 2D image for this workflow. " +
            "Use the GUI if you need image-plus-mask stacks."
        )
    }
    return imp
}

int modeCode = MODE_CODES[registrationMode]
if (modeCode == null) {
    throw new IllegalArgumentException("Unsupported registration mode: " + registrationMode)
}

int minScaleCode = SCALE_CODES[initialDeformation]
int maxScaleCode = SCALE_CODES[finalDeformation]
if (minScaleCode == null || maxScaleCode == null) {
    throw new IllegalArgumentException("Unsupported deformation scale choice")
}
if (maxScaleCode < minScaleCode) {
    throw new IllegalArgumentException("Final deformation must be at least as fine as the initial deformation")
}
if (imageSubsampleFactor < 0 || imageSubsampleFactor > 7) {
    throw new IllegalArgumentException("Image subsample factor must be between 0 and 7")
}

requireFreshOutput(registeredSourceOutputFile, "Registered source output")
requireFreshOutput(directTransformOutputFile, "Direct elastic transform output")

if (saveInverseOutputs && modeCode != 2) {
    requireFreshOutput(registeredTargetOutputFile, "Registered target output")
    requireFreshOutput(inverseTransformOutputFile, "Inverse elastic transform output")
}
if (saveReappliedSourceCopy) {
    requireFreshOutput(reappliedSourceOutputFile, "Re-applied source output")
}

def targetImp = openSinglePlaneImage(targetFile, "Target image")
def sourceImp = openSinglePlaneImage(sourceFile, "Source image")

println("bUnwarpJ pairwise registration")
println("Target image              : " + targetFile.absolutePath)
println("Source image              : " + sourceFile.absolutePath)
println("Registration mode         : " + registrationMode)
println("Image subsample factor    : " + imageSubsampleFactor)
println("Initial deformation       : " + initialDeformation)
println("Final deformation         : " + finalDeformation)
println("Direct result output      : " + registeredSourceOutputFile.absolutePath)
println("Direct transform output   : " + directTransformOutputFile.absolutePath)

if (modeCode == 2 && consistencyWeight != 0.0d) {
    println("Consistency weight is ignored in Mono mode.")
}

def params = new Param(
    modeCode,
    imageSubsampleFactor,
    minScaleCode,
    maxScaleCode,
    divergenceWeight,
    curlWeight,
    landmarkWeight,
    imageWeight,
    consistencyWeight,
    stopThreshold
)

def transform = bUnwarpJ_.computeTransformationBatch(targetImp, sourceImp, null, null, params)

def directResult = transform.getDirectResults()
if (directResult == null) {
    throw new IllegalStateException("bUnwarpJ did not return a direct registered result")
}

IJ.saveAsTiff(directResult, registeredSourceOutputFile.absolutePath)
verifySavedFile(registeredSourceOutputFile, "Registered source output")

transform.saveDirectTransformation(directTransformOutputFile.absolutePath)
verifySavedFile(directTransformOutputFile, "Direct elastic transform output")

if (saveInverseOutputs && modeCode != 2) {
    def inverseResult = transform.getInverseResults()
    if (inverseResult == null) {
        throw new IllegalStateException("Bidirectional mode did not return an inverse registered result")
    }
    IJ.saveAsTiff(inverseResult, registeredTargetOutputFile.absolutePath)
    verifySavedFile(registeredTargetOutputFile, "Registered target output")

    transform.saveInverseTransformation(inverseTransformOutputFile.absolutePath)
    verifySavedFile(inverseTransformOutputFile, "Inverse elastic transform output")
}

if (saveReappliedSourceCopy) {
    def reapplied = new Duplicator().run(sourceImp)
    bUnwarpJ_.applyTransformToSource(directTransformOutputFile.absolutePath, targetImp, reapplied)
    IJ.saveAsTiff(reapplied, reappliedSourceOutputFile.absolutePath)
    verifySavedFile(reappliedSourceOutputFile, "Re-applied source output")
}

println("Registered source saved   : " + registeredSourceOutputFile.absolutePath)
println("Direct transform saved    : " + directTransformOutputFile.absolutePath)
if (saveInverseOutputs && modeCode != 2) {
    println("Registered target saved   : " + registeredTargetOutputFile.absolutePath)
    println("Inverse transform saved   : " + inverseTransformOutputFile.absolutePath)
}
if (saveReappliedSourceCopy) {
    println("Re-applied source saved   : " + reappliedSourceOutputFile.absolutePath)
}
println("bUnwarpJ pairwise registration complete")

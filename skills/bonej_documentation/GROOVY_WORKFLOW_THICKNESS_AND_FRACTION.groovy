// These #@ lines inject Fiji script parameters and must stay at the top.
#@ File (label = "Input image", value = "/data/example_1.tif") inputFile
#@ File (label = "Output directory", style = "directory", value = "/data/bonej_validation") outputDir
#@ Integer (label = "Duplicate single slice count", value = 6, min = 1) duplicateSingleSliceCount
#@ Boolean (label = "Threshold input to binary", value = true) thresholdToBinary
#@ Boolean (label = "Run Connectivity (Modern)", value = true) runConnectivity
#@ CommandService command
#@ ConvertService convertService

import ij.IJ
import ij.ImagePlus
import ij.ImageStack
import net.imagej.ImgPlus
import org.bonej.wrapperPlugins.ConnectivityWrapper
import org.bonej.wrapperPlugins.ElementFractionWrapper
import org.bonej.wrapperPlugins.ThicknessWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner
import org.scijava.table.Table

/*
 * BoneJ — Thickness, Area/Volume fraction, and optional Connectivity
 *
 * PURPOSE:
 *   1. Open an input image from disk
 *   2. Duplicate a single 2D slice into a small stack when needed
 *   3. Threshold to an 8-bit binary mask when requested
 *   4. Clear the shared BoneJ results table
 *   5. Run Thickness and Area/Volume fraction
 *   6. Optionally run Connectivity (Modern)
 *   7. Save a binary stack, Thickness maps, and a CSV summary
 *
 * REQUIRED INPUTS:
 *   inputFile                 - source image
 *   outputDir                 - directory for TIFF and CSV outputs
 *   duplicateSingleSliceCount - used only when the input has one slice
 *   thresholdToBinary         - converts a non-binary image with Default threshold
 *   runConnectivity           - appends connectivity columns to the CSV summary
 *
 * IMPORTANT:
 *   - Adjust the default paths for your own images and output directory.
 *   - BoneJ measurements assume foreground voxels represent the structure of interest.
 *   - Choose a fresh output directory or remove old outputs before rerunning.
 */

void closeImageIfOpen(ImagePlus imp) {
    if (imp != null) {
        imp.changes = false
        imp.close()
    }
}

String baseName(File file) {
    def name = file.name
    name = name.replaceFirst(/(?i)\.ome\.tiff?$/, "")
    name = name.replaceFirst(/(?i)\.tiff?$/, "")
    return name
}

String escapeCsvValue(Object value) {
    def text = value == null ? "" : value.toString()
    if (text.contains("\"")) {
        text = text.replace("\"", "\"\"")
    }
    if (text.contains(",") || text.contains("\"") || text.contains("\n")) {
        return "\"${text}\""
    }
    return text
}

void writeTableCsv(Table table, File outputFile) {
    outputFile.withWriter("UTF-8") { writer ->
        def headers = (0..<table.getColumnCount()).collect { columnIndex ->
            def header = table.getColumnHeader(columnIndex)
            escapeCsvValue(header ?: "Column${columnIndex + 1}")
        }
        writer.println(headers.join(","))

        for (int row = 0; row < table.getRowCount(); row++) {
            def values = (0..<table.getColumnCount()).collect { columnIndex ->
                escapeCsvValue(table.get(columnIndex, row))
            }
            writer.println(values.join(","))
        }
    }
}

boolean isBinary8Bit(ImagePlus imp) {
    if (imp == null || imp.getBitDepth() != 8) {
        return false
    }
    for (int sliceIndex = 1; sliceIndex <= imp.getNSlices(); sliceIndex++) {
        def histogram = imp.getStack().getProcessor(sliceIndex).getHistogram()
        for (int bin = 1; bin < 255; bin++) {
            if (histogram[bin] != 0) {
                return false
            }
        }
    }
    return true
}

ImagePlus duplicateSingleSliceToStack(ImagePlus source, int copies) {
    ImageStack stack = new ImageStack(source.getWidth(), source.getHeight())
    for (int i = 0; i < copies; i++) {
        stack.addSlice(source.getProcessor().duplicate())
    }
    ImagePlus duplicated = new ImagePlus(source.getTitle() + "-stack", stack)
    duplicated.setCalibration(source.getCalibration())
    return duplicated
}

void requireFreshOutput(File file) {
    if (file.exists()) {
        throw new IllegalArgumentException("Output file already exists: " + file.absolutePath)
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

def stem = baseName(inputFile)
File binaryOutputFile = new File(outputDir, stem + "-binary.tif")
File trabecularMapFile = new File(outputDir, stem + "-trabecular-thickness.tif")
File separationMapFile = new File(outputDir, stem + "-trabecular-separation.tif")
File summaryCsvFile = new File(outputDir, stem + "-bonej-summary.csv")

[binaryOutputFile, trabecularMapFile, separationMapFile, summaryCsvFile].each { requireFreshOutput(it) }

ImagePlus sourceImp = null
ImagePlus workingImp = null
ImagePlus trabecularMap = null
ImagePlus separationMap = null

try {
    sourceImp = IJ.openImage(inputFile.absolutePath)
    if (sourceImp == null) {
        throw new IllegalStateException("Could not open input image: " + inputFile.absolutePath)
    }

    if (sourceImp.getNSlices() == 1) {
        if (duplicateSingleSliceCount < 2) {
            throw new IllegalArgumentException("BoneJ Thickness requires a 3D stack. Use duplicateSingleSliceCount >= 2 for a single-slice input.")
        }
        workingImp = duplicateSingleSliceToStack(sourceImp, duplicateSingleSliceCount)
    }
    else {
        workingImp = sourceImp.duplicate()
        workingImp.setTitle(sourceImp.getTitle() + "-copy")
        workingImp.setCalibration(sourceImp.getCalibration())
    }

    if (thresholdToBinary) {
        if (workingImp.getBitDepth() != 8) {
            IJ.run(workingImp, "8-bit", "")
        }
        IJ.setAutoThreshold(workingImp, "Default dark")
        def maskArgs = workingImp.getNSlices() > 1 ?
            "method=Default background=Dark black stack" :
            "method=Default background=Dark black"
        IJ.run(workingImp, "Convert to Mask", maskArgs)
    }

    if (!isBinary8Bit(workingImp)) {
        throw new IllegalArgumentException("BoneJ requires an 8-bit binary image with only 0 and 255 voxels.")
    }
    if (workingImp.getNSlices() < 2) {
        throw new IllegalArgumentException("BoneJ Thickness requires a 3D stack.")
    }

    IJ.saveAsTiff(workingImp, binaryOutputFile.absolutePath)
    if (!binaryOutputFile.exists() || binaryOutputFile.length() == 0) {
        throw new IllegalStateException("Could not save binary stack: " + binaryOutputFile.absolutePath)
    }

    command.run(SharedTableCleaner, true).get()

    def thicknessModule = command.run(ThicknessWrapper, true,
        "inputImage",    workingImp,
        "mapChoice",     "Both",
        "showMaps",      true,
        "maskArtefacts", true
    ).get()

    trabecularMap = thicknessModule.getOutput("trabecularMap")
    separationMap = thicknessModule.getOutput("separationMap")
    if (trabecularMap == null || separationMap == null) {
        throw new IllegalStateException("BoneJ Thickness did not return both thickness maps.")
    }

    IJ.saveAsTiff(trabecularMap, trabecularMapFile.absolutePath)
    IJ.saveAsTiff(separationMap, separationMapFile.absolutePath)
    if (!trabecularMapFile.exists() || trabecularMapFile.length() == 0) {
        throw new IllegalStateException("Could not save trabecular thickness map: " + trabecularMapFile.absolutePath)
    }
    if (!separationMapFile.exists() || separationMapFile.length() == 0) {
        throw new IllegalStateException("Could not save trabecular separation map: " + separationMapFile.absolutePath)
    }

    ImgPlus binaryImgPlus = convertService.convert(workingImp, ImgPlus.class)
    if (binaryImgPlus == null) {
        throw new IllegalStateException("Could not convert ImagePlus to ImgPlus for BoneJ fraction/connectivity.")
    }

    def fractionModule = command.run(ElementFractionWrapper, true,
        "inputImage", binaryImgPlus
    ).get()

    Table summaryTable = fractionModule.getOutput("resultsTable")
    if (summaryTable == null) {
        throw new IllegalStateException("BoneJ Area/Volume fraction returned no results table.")
    }

    if (runConnectivity) {
        def connectivityModule = command.run(ConnectivityWrapper, true,
            "inputImage", binaryImgPlus
        ).get()

        summaryTable = connectivityModule.getOutput("resultsTable")
        if (summaryTable == null) {
            throw new IllegalStateException("BoneJ Connectivity returned no results table.")
        }
    }

    writeTableCsv(summaryTable, summaryCsvFile)
    if (!summaryCsvFile.exists() || summaryCsvFile.length() == 0) {
        throw new IllegalStateException("Could not save BoneJ summary CSV: " + summaryCsvFile.absolutePath)
    }

    IJ.log("BoneJ workflow complete")
    IJ.log("Binary stack        : " + binaryOutputFile.absolutePath)
    IJ.log("Trabecular map      : " + trabecularMapFile.absolutePath)
    IJ.log("Separation map      : " + separationMapFile.absolutePath)
    IJ.log("Summary CSV         : " + summaryCsvFile.absolutePath)
}
finally {
    closeImageIfOpen(trabecularMap)
    closeImageIfOpen(separationMap)
    closeImageIfOpen(workingImp)
    closeImageIfOpen(sourceImp)
}

// These #@ lines inject Fiji script parameters and must stay at the top.
#@ File (label = "Input 3D image", value = "/data/input_stack.tif") inputFile
#@ File (label = "Output directory", style = "directory", value = "/data/bonej_output") outputDir
#@ Boolean (label = "Threshold input to binary", value = true) thresholdToBinary
#@ Boolean (label = "Run Connectivity", value = true) runConnectivity
#@ Boolean (label = "Purify (keep largest particle) before Connectivity", value = false) purifyBeforeConnectivity
#@ CommandService command
#@ ConvertService convertService

import ij.IJ
import ij.ImagePlus
import ij.process.StackStatistics
import net.imagej.Dataset
import net.imagej.axis.CalibratedAxis
import org.bonej.plugins.Connectivity
import org.bonej.plugins.Purify
import org.bonej.wrapperPlugins.ElementFractionWrapper
import org.bonej.wrapperPlugins.ThicknessWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner
import org.scijava.table.Table

/*
 * BoneJ — Thickness, Area/Volume fraction, and optional Connectivity
 *
 * PURPOSE:
 *   1. Open a 3D stack from disk
 *   2. Threshold it to an 8-bit 0/255 mask when requested
 *   3. Clear the shared BoneJ results table
 *   4. Run Thickness (Tb.Th + Tb.Sp) and Area/Volume fraction (BV/TV)
 *   5. Optionally run Connectivity (optionally on the purified largest particle)
 *   6. Save the binary stack, both thickness maps, and a CSV summary
 *      (one row per image name: the input, plus the purified copy when purifying)
 *
 * REQUIRED INPUTS:
 *   inputFile                - 3D stack (grayscale if thresholdToBinary, else 8-bit 0/255)
 *   outputDir                - directory for TIFF and CSV outputs
 *   thresholdToBinary        - Default/dark threshold computed on the whole stack histogram
 *   runConnectivity          - appends Euler ch. / Connectivity / Conn.D columns
 *   purifyBeforeConnectivity - Connectivity assumes ONE particle; purify keeps the largest
 *
 * IMPORTANT:
 *   - BoneJ wrappers take `inputDataset` (net.imagej.Dataset), never `inputImage`.
 *   - A µm calibration is rewritten to "um" on the Dataset axes; BoneJ's unit parser rejects "µ".
 *   - Check the voxel size: a TIFF with only a 72-dpi tag opens in inches and BoneJ will report inches.
 *   - Choose a fresh output directory; existing outputs are never overwritten.
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
        // The shared BoneJ table keys each row by image name; keep it as the first column
        def headers = ["Image"] + (0..<table.getColumnCount()).collect { columnIndex ->
            escapeCsvValue(table.getColumnHeader(columnIndex) ?: "Column${columnIndex + 1}")
        }
        writer.println(headers.join(","))
        for (int row = 0; row < table.getRowCount(); row++) {
            def values = [escapeCsvValue(table.getRowHeader(row))] + (0..<table.getColumnCount()).collect { columnIndex ->
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
    def histogram = new StackStatistics(imp).histogram
    return (1..254).every { histogram[it] == 0 }
}

// ImagePlus -> Dataset with BoneJ-parsable axis units ("µm" -> "um")
Dataset toBoneJDataset(ImagePlus imp) {
    Dataset ds = convertService.convert(imp, Dataset.class)
    if (ds == null) {
        throw new IllegalStateException("Could not convert ImagePlus to Dataset for BoneJ.")
    }
    for (int d = 0; d < ds.numDimensions(); d++) {
        def axis = (CalibratedAxis) ds.axis(d)
        def unit = axis.unit()
        if (unit != null) {
            axis.setUnit(unit.replace('µ', 'u').replace('μ', 'u'))
        }
    }
    return ds
}

// BoneJ cancels (rather than throws) on bad input; surface that as an error
def runBoneJ(Class commandClass, String label, Object... args) {
    def module = command.run(commandClass, true, args).get()
    if (module.isCanceled()) {
        throw new IllegalStateException(label + " canceled: " + module.getCancelReason())
    }
    return module
}

void requireFreshOutput(File file) {
    if (file.exists()) {
        throw new IllegalArgumentException("Output file already exists: " + file.absolutePath)
    }
}

void saveTiff(ImagePlus imp, File file, String label) {
    IJ.saveAsTiff(imp, file.absolutePath)
    if (!file.exists() || file.length() == 0) {
        throw new IllegalStateException("Could not save " + label + ": " + file.absolutePath)
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
    if (sourceImp.getNChannels() > 1 || sourceImp.getNFrames() > 1) {
        throw new IllegalArgumentException("BoneJ needs a single-channel, single-timepoint 3D stack (no hyperstack).")
    }
    if (sourceImp.getNSlices() < 2) {
        throw new IllegalArgumentException("BoneJ Thickness needs a 3D stack; the input has a single slice.")
    }

    workingImp = sourceImp.duplicate()
    workingImp.setTitle(stem)
    workingImp.setCalibration(sourceImp.getCalibration())

    if (thresholdToBinary && !isBinary8Bit(workingImp)) {
        if (workingImp.getBitDepth() != 8) {
            IJ.run(workingImp, "8-bit", "")
        }
        IJ.setAutoThreshold(workingImp, "Default dark stack")
        IJ.run(workingImp, "Convert to Mask", "method=Default background=Dark black stack")
    }
    if (!isBinary8Bit(workingImp)) {
        throw new IllegalArgumentException("BoneJ requires an 8-bit binary image with only 0 and 255 voxels.")
    }

    def cal = workingImp.getCalibration()
    IJ.log("Voxel size: " + cal.pixelWidth + " x " + cal.pixelHeight + " x " + cal.pixelDepth + " " + cal.getUnit())
    if (cal.getUnit() in ["inch", "inches"]) {
        IJ.log("WARNING: calibration is in inches (often a default 72-dpi TIFF tag). Results will be in inches.")
    }

    saveTiff(workingImp, binaryOutputFile, "binary stack")

    Dataset binaryDataset = toBoneJDataset(workingImp)

    command.run(SharedTableCleaner, true).get()

    def thicknessModule = runBoneJ(ThicknessWrapper, "Thickness",
        "inputDataset",  binaryDataset,
        "mapChoice",     "Both",
        "showMaps",      true,
        "maskArtefacts", true
    )
    trabecularMap = convertService.convert(thicknessModule.getOutput("trabecularMap"), ImagePlus.class)
    separationMap = convertService.convert(thicknessModule.getOutput("separationMap"), ImagePlus.class)
    if (trabecularMap == null || separationMap == null) {
        throw new IllegalStateException("BoneJ Thickness did not return both thickness maps.")
    }
    saveTiff(trabecularMap, trabecularMapFile, "trabecular thickness map")
    saveTiff(separationMap, separationMapFile, "trabecular separation map")

    def fractionModule = runBoneJ(ElementFractionWrapper, "Area/Volume fraction",
        "inputDataset", binaryDataset
    )
    Table summaryTable = fractionModule.getOutput("resultsTable")

    if (runConnectivity) {
        Dataset connectivityInput = binaryDataset
        if (purifyBeforeConnectivity) {
            def purifyModule = runBoneJ(Purify, "Purify",
                "inputDataset",    binaryDataset,
                "showPerformance", false,
                "makeCopy",        true
            )
            connectivityInput = purifyModule.getOutput("outputDataset")
        }
        def connectivityModule = runBoneJ(Connectivity, "Connectivity",
            "inputDataset", connectivityInput
        )
        summaryTable = connectivityModule.getOutput("resultsTable")
    }

    // One row for the input image; Purify adds a second row for the purified copy,
    // because the shared BoneJ table keys rows by image name.
    if (summaryTable == null || summaryTable.getRowCount() == 0) {
        throw new IllegalStateException("BoneJ returned an empty results table.")
    }
    writeTableCsv(summaryTable, summaryCsvFile)
    if (!summaryCsvFile.exists() || summaryCsvFile.length() == 0) {
        throw new IllegalStateException("Could not save BoneJ summary CSV: " + summaryCsvFile.absolutePath)
    }

    IJ.log("BoneJ workflow complete")
    IJ.log("Binary stack   : " + binaryOutputFile.absolutePath)
    IJ.log("Thickness map  : " + trabecularMapFile.absolutePath)
    IJ.log("Separation map : " + separationMapFile.absolutePath)
    IJ.log("Summary CSV    : " + summaryCsvFile.absolutePath)
}
finally {
    closeImageIfOpen(trabecularMap)
    closeImageIfOpen(separationMap)
    closeImageIfOpen(workingImp)
    closeImageIfOpen(sourceImp)
}

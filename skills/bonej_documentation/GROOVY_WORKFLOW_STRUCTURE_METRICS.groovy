// These #@ lines inject Fiji script parameters and must stay at the top.
#@ File (label = "Input 3D image", value = "/data/input_stack.tif") inputFile
#@ File (label = "Output CSV", style = "save", value = "/data/bonej_output/structure-metrics.csv") outputCsvFile
#@ Boolean (label = "Threshold input to binary", value = true) thresholdToBinary
#@ Boolean (label = "Run anisotropy", value = true) runAnisotropy
#@ Boolean (label = "Use automatic fractal parameters", value = true) fractalAutoParam
#@ Integer (label = "Anisotropy directions", value = 2000, min = 9) anisotropyDirections
#@ Integer (label = "Anisotropy lines per direction", value = 10000, min = 1) anisotropyLines
#@ Double (label = "Anisotropy sampling increment", value = 2.0, min = 1.001) anisotropySamplingIncrement
#@ Boolean (label = "Record anisotropy radii", value = true) anisotropyPrintRadii
#@ CommandService command
#@ ConvertService convertService

import ij.IJ
import ij.ImagePlus
import ij.process.StackStatistics
import net.imagej.Dataset
import net.imagej.axis.CalibratedAxis
import org.bonej.wrapperPlugins.AnisotropyWrapper
import org.bonej.wrapperPlugins.FractalDimensionWrapper
import org.bonej.wrapperPlugins.SurfaceAreaWrapper
import org.bonej.wrapperPlugins.SurfaceFractionWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner
import org.scijava.table.Table

/*
 * BoneJ — Structure metrics workflow
 *
 * PURPOSE:
 *   1. Open a 3D stack from disk
 *   2. Threshold it to an 8-bit 0/255 mask when requested
 *   3. Run Surface fraction, Surface area, and Fractal dimension
 *   4. Optionally run Anisotropy (DA + ellipsoid radii)
 *   5. Save every metric as one row of one CSV file
 *
 * REQUIRED INPUTS:
 *   inputFile                   - 3D stack (grayscale if thresholdToBinary, else 8-bit 0/255)
 *   outputCsvFile               - CSV that will be written (must not exist yet)
 *   thresholdToBinary           - Default/dark threshold computed on the whole stack histogram
 *   runAnisotropy               - enables BoneJ anisotropy metrics
 *   fractalAutoParam            - lets BoneJ choose the box sizes
 *   anisotropyDirections        - probe directions (BoneJ default 2000)
 *   anisotropyLines             - lines sampled per direction (BoneJ default 10000)
 *   anisotropySamplingIncrement - sampling increment along each line
 *   anisotropyPrintRadii        - include fitted ellipsoid radii
 *
 * IMPORTANT:
 *   - BoneJ wrappers take `inputDataset` (net.imagej.Dataset), never `inputImage`.
 *   - A µm calibration is rewritten to "um" on the Dataset axes; BoneJ's unit parser rejects "µ".
 *   - SurfaceAreaWrapper always needs `stlDirectory`, otherwise a modal directory chooser opens.
 *   - Anisotropy needs a genuinely 3D structure; ellipsoid fitting fails on degenerate volumes.
 */

void closeImageIfOpen(ImagePlus imp) {
    if (imp != null) {
        imp.changes = false
        imp.close()
    }
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

void writeMetricsCsv(Map<String, Object> metrics, File outputFile) {
    outputFile.withWriter("UTF-8") { writer ->
        writer.println(metrics.keySet().collect { escapeCsvValue(it) }.join(","))
        writer.println(metrics.values().collect { escapeCsvValue(it) }.join(","))
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

// Each command is run on a cleared shared table, so its table holds only its own columns
void addSingleRowTable(Map<String, Object> metrics, Table table, String label) {
    if (table == null) {
        throw new IllegalStateException(label + " returned no results table.")
    }
    if (table.getRowCount() != 1) {
        throw new IllegalStateException(label + " returned " + table.getRowCount() + " rows. This workflow expects one 3D image.")
    }
    for (int columnIndex = 0; columnIndex < table.getColumnCount(); columnIndex++) {
        def header = table.getColumnHeader(columnIndex) ?: "Column${columnIndex + 1}"
        def key = header.toString()
        if (metrics.containsKey(key)) {
            key = label + " " + key   // Surface fraction BV/TV vs other BV/TV, etc.
        }
        metrics.put(key, table.get(columnIndex, 0))
    }
}

if (!inputFile.exists()) {
    throw new IllegalArgumentException("Input image not found: " + inputFile.absolutePath)
}
if (outputCsvFile == null) {
    throw new IllegalArgumentException("Output CSV must be provided")
}
File outputDir = outputCsvFile.getAbsoluteFile().getParentFile()
outputDir.mkdirs()
if (outputCsvFile.exists()) {
    throw new IllegalArgumentException("Output CSV already exists: " + outputCsvFile.absolutePath)
}

ImagePlus sourceImp = null
ImagePlus workingImp = null

try {
    sourceImp = IJ.openImage(inputFile.absolutePath)
    if (sourceImp == null) {
        throw new IllegalStateException("Could not open input image: " + inputFile.absolutePath)
    }
    if (sourceImp.getNChannels() > 1 || sourceImp.getNFrames() > 1) {
        throw new IllegalArgumentException("BoneJ needs a single-channel, single-timepoint 3D stack (no hyperstack).")
    }
    if (sourceImp.getNSlices() < 2) {
        throw new IllegalArgumentException("This workflow needs a 3D stack; the input has a single slice.")
    }

    workingImp = sourceImp.duplicate()
    workingImp.setTitle(sourceImp.getShortTitle())
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

    Dataset binaryDataset = toBoneJDataset(workingImp)
    LinkedHashMap<String, Object> metrics = new LinkedHashMap<>()

    command.run(SharedTableCleaner, true).get()
    def surfaceFractionModule = runBoneJ(SurfaceFractionWrapper, "Surface fraction",
        "inputDataset", binaryDataset
    )
    addSingleRowTable(metrics, surfaceFractionModule.getOutput("resultsTable"), "Surface fraction")

    command.run(SharedTableCleaner, true).get()
    def surfaceAreaModule = runBoneJ(SurfaceAreaWrapper, "Surface area",
        "inputDataset", binaryDataset,
        "exportSTL",    false,
        "stlDirectory", outputDir
    )
    addSingleRowTable(metrics, surfaceAreaModule.getOutput("resultsTable"), "Surface area")

    command.run(SharedTableCleaner, true).get()
    def fractalModule = runBoneJ(FractalDimensionWrapper, "Fractal dimension",
        "inputDataset",    binaryDataset,
        "autoParam",       fractalAutoParam,
        "showPoints",      false,
        "translations",    0L,
        "startBoxSize",    48L,
        "smallestBoxSize", 6L,
        "scaleFactor",     1.2d
    )
    addSingleRowTable(metrics, fractalModule.getOutput("resultsTable"), "Fractal dimension")

    if (runAnisotropy) {
        command.run(SharedTableCleaner, true).get()
        def anisotropyModule = runBoneJ(AnisotropyWrapper, "Anisotropy",
            "inputDataset",           binaryDataset,
            "directions",             anisotropyDirections,
            "lines",                  anisotropyLines,
            "samplingIncrement",      anisotropySamplingIncrement as Double,
            "recommendedMin",         false,
            "printRadii",             anisotropyPrintRadii,
            "printEigens",            false,
            "displayMILVectors",      false,
            "printMILVectorsToTable", false
        )
        addSingleRowTable(metrics, anisotropyModule.getOutput("resultsTable"), "Anisotropy")
    }

    writeMetricsCsv(metrics, outputCsvFile)
    if (!outputCsvFile.exists() || outputCsvFile.length() == 0) {
        throw new IllegalStateException("Could not save structure metrics CSV: " + outputCsvFile.absolutePath)
    }

    IJ.log("BoneJ structure metrics workflow complete")
    IJ.log("Output CSV: " + outputCsvFile.absolutePath)
}
finally {
    closeImageIfOpen(workingImp)
    closeImageIfOpen(sourceImp)
}

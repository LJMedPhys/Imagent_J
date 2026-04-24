// These #@ lines inject Fiji script parameters and must stay at the top.
#@ File (label = "Input image", value = "/data/example_1.tif") inputFile
#@ File (label = "Output CSV", style = "save", value = "/data/bonej_validation/example_1-structure-metrics.csv") outputCsvFile
#@ Boolean (label = "Threshold input to binary", value = true) thresholdToBinary
#@ Boolean (label = "Run anisotropy", value = false) runAnisotropy
#@ Boolean (label = "Use automatic fractal parameters", value = true) fractalAutoParam
#@ Integer (label = "Anisotropy directions", value = 200, min = 9) anisotropyDirections
#@ Integer (label = "Anisotropy lines per direction", value = 400, min = 1) anisotropyLines
#@ Double (label = "Anisotropy sampling increment", value = 2.0, min = 1.001) anisotropySamplingIncrement
#@ Boolean (label = "Record anisotropy radii", value = true) anisotropyPrintRadii
#@ CommandService command
#@ ConvertService convertService
#@ OpService opService

import ij.IJ
import ij.ImagePlus
import net.imagej.ImgPlus
import net.imagej.mesh.Mesh
import net.imagej.mesh.naive.NaiveFloatMesh
import net.imagej.ops.Ops.Geometric.BoundarySize
import net.imagej.ops.Ops.Geometric.MarchingCubes
import net.imagej.ops.special.function.Functions
import net.imglib2.type.numeric.real.DoubleType
import org.bonej.wrapperPlugins.AnisotropyWrapper
import org.bonej.wrapperPlugins.FractalDimensionWrapper
import org.bonej.wrapperPlugins.SurfaceFractionWrapper
import org.bonej.wrapperPlugins.tableTools.SharedTableCleaner
import org.scijava.table.Table

/*
 * BoneJ — Structure metrics workflow
 *
 * PURPOSE:
 *   1. Open an input image from disk
 *   2. Threshold it to an 8-bit binary stack when requested
 *   3. Run Surface fraction and Fractal dimension
 *   4. Optionally run Anisotropy on a suitable 3D structure
 *   5. Compute Surface area through the validated marching-cubes + boundary-size path
 *   6. Save the combined metrics to one CSV file
 *
 * REQUIRED INPUTS:
 *   inputFile                   - source image
 *   outputCsvFile               - CSV that will be written
 *   thresholdToBinary           - converts a non-binary image with Default threshold
 *   runAnisotropy               - enables BoneJ anisotropy metrics
 *   fractalAutoParam            - uses BoneJ's automatic fractal parameters
 *   anisotropyDirections        - probe directions for anisotropy
 *   anisotropyLines             - lines sampled per direction
 *   anisotropySamplingIncrement - sampling increment along each line
 *   anisotropyPrintRadii        - include fitted ellipsoid radii in anisotropy output
 *
 * IMPORTANT:
 *   - Adjust the default paths for your own images and output location.
 *   - Anisotropy needs a representative 3D structure. Degenerate or slice-duplicated volumes can fail ellipsoid fitting.
 *   - Surface area uses the validated lower-level ops path because SurfaceAreaWrapper canceled in this Fiji runtime.
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

void requireSingleRow(Table table, String label) {
    if (table == null) {
        throw new IllegalStateException(label + " returned no results table.")
    }
    if (table.getRowCount() != 1) {
        throw new IllegalStateException(label + " returned " + table.getRowCount() + " rows. This workflow expects one 3D subspace.")
    }
}

void addTableRow(Map<String, Object> metrics, Table table) {
    for (int columnIndex = 0; columnIndex < table.getColumnCount(); columnIndex++) {
        def header = table.getColumnHeader(columnIndex) ?: "Column${columnIndex + 1}"
        metrics.put(header.toString(), table.get(columnIndex, 0))
    }
}

double calculateSurfaceArea(ImgPlus binaryImgPlus) {
    def bitImg = opService.convert().bit(binaryImgPlus)
    ImgPlus bitImgPlus = new ImgPlus(bitImg, binaryImgPlus)
    def marchingCubesOp = Functions.unary(opService, MarchingCubes.class, Mesh.class, bitImgPlus)
    Mesh mesh = marchingCubesOp.calculate(bitImgPlus)
    def areaOp = Functions.unary(opService, BoundarySize.class, DoubleType.class, new NaiveFloatMesh())
    return areaOp.calculate(mesh).get()
}

if (!inputFile.exists()) {
    throw new IllegalArgumentException("Input image not found: " + inputFile.absolutePath)
}
if (outputCsvFile == null) {
    throw new IllegalArgumentException("Output CSV must be provided")
}
outputCsvFile.getParentFile()?.mkdirs()
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

    workingImp = sourceImp.duplicate()
    workingImp.setTitle(sourceImp.getTitle() + "-copy")
    workingImp.setCalibration(sourceImp.getCalibration())

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
        throw new IllegalArgumentException("This workflow expects a 3D stack.")
    }

    ImgPlus binaryImgPlus = convertService.convert(workingImp, ImgPlus.class)
    if (binaryImgPlus == null) {
        throw new IllegalStateException("Could not convert ImagePlus to ImgPlus for BoneJ.")
    }

    LinkedHashMap<String, Object> metrics = new LinkedHashMap<>()

    command.run(SharedTableCleaner, true).get()

    def fractionModule = command.run(SurfaceFractionWrapper, true,
        "inputImage", binaryImgPlus
    ).get()
    if (fractionModule.isCanceled()) {
        throw new IllegalStateException("Surface fraction canceled: " + fractionModule.getCancelReason())
    }
    def fractionTable = fractionModule.getOutput("resultsTable")
    requireSingleRow(fractionTable, "Surface fraction")
    addTableRow(metrics, fractionTable)

    def fractalModule = command.run(FractalDimensionWrapper, true,
        "inputImage",      binaryImgPlus,
        "autoParam",       fractalAutoParam,
        "showPoints",      false,
        "translations",    0L,
        "startBoxSize",    48L,
        "smallestBoxSize", 6L,
        "scaleFactor",     1.2d
    ).get()
    if (fractalModule.isCanceled()) {
        throw new IllegalStateException("Fractal dimension canceled: " + fractalModule.getCancelReason())
    }
    def fractalTable = fractalModule.getOutput("resultsTable")
    requireSingleRow(fractalTable, "Fractal dimension")
    addTableRow(metrics, fractalTable)

    if (runAnisotropy) {
        def anisotropyModule = command.run(AnisotropyWrapper, true,
            "inputImage",             binaryImgPlus,
            "directions",             anisotropyDirections,
            "lines",                  anisotropyLines,
            "samplingIncrement",      anisotropySamplingIncrement,
            "recommendedMin",         false,
            "printRadii",             anisotropyPrintRadii,
            "printEigens",            false,
            "displayMILVectors",      false,
            "printMILVectorsToTable", false
        ).get()
        if (anisotropyModule.isCanceled()) {
            throw new IllegalStateException("Anisotropy canceled: " + anisotropyModule.getCancelReason())
        }
        def anisotropyTable = anisotropyModule.getOutput("resultsTable")
        requireSingleRow(anisotropyTable, "Anisotropy")
        addTableRow(metrics, anisotropyTable)
    }

    metrics.put("Surface area (pixel^2)", calculateSurfaceArea(binaryImgPlus))

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

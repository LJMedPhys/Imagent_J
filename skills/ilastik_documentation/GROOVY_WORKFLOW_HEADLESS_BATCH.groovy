// These #@ lines inject Fiji parameters; they must stay at the top of the file.
#@ String (label = "Ilastik executable path (empty = ILASTIK_EXECUTABLE)", value = "") executablePath
#@ File (label = "Trained ilastik project (.ilp)", value = "/data/ilastik_validation/pixel_class_2d_cells_apoptotic.ilp") projectFile
#@ File (label = "Input folder", style = "directory", value = "/data/ilastik_validation/batch_in") inputDir
#@ String (label = "File pattern (glob)", value = "*.tif") filePattern
#@ File (label = "Output folder", style = "directory", value = "/data/ilastik_validation/batch_out") outputDir
#@ String (label = "Export source", value = "Simple Segmentation") exportSource
#@ String (label = "Output format", choices = {"tiff", "hdf5"}, value = "tiff") outputFormat
#@ String (label = "Input axes (empty = let ilastik infer; e.g. yx, yxc, zyx, tyx)", value = "") inputAxes
#@ String (label = "Second input role", choices = {"none", "prediction_maps", "segmentation_image", "label_image"}, value = "none") secondInputRole
#@ String (label = "Second input folder (same file stem + suffix)", value = "") secondInputDir
#@ String (label = "Second input suffix", value = "") secondInputSuffix
#@ String (label = "Object feature table CSV (object classification / tracking; empty = none)", value = "") tableFilename
#@ Integer (label = "Threads (-1 for all)", value = -1) numThreads
#@ Integer (label = "Max RAM (MiB)", value = 4096) maxRamMb

import ij.IJ
import java.nio.file.FileSystems
import java.util.concurrent.TimeUnit

/*
 * ilastik — batch-apply a trained project to a folder, calling ilastik headless directly
 *
 * WHY THIS ROUTE
 *   The Fiji wrapper commands (GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy etc.) process ONE open
 *   image per call and copy it through a temporary HDF5 file. For a folder, one ilastik call over
 *   all files is faster (the project and classifier are loaded once), reads TIFF/PNG/HDF5 directly,
 *   and supports what the wrappers cannot:
 *     - "Object Classification [Inputs: Raw Data, Label Image]" projects (ilastik >= 1.4.2;
 *       e.g. classify Cellpose/StarDist instances): secondInputRole = label_image
 *     - every export source of the workflow (e.g. "Uncertainty", "Object Identities")
 *     - the per-object feature table (--table_filename) for object classification / tracking
 *
 * EXPORT SOURCE (exact names, case-sensitive)
 *   Pixel Classification / Autocontext : Probabilities | Simple Segmentation | Uncertainty | Features | Labels
 *   Object Classification              : Object Predictions | Object Probabilities | Object Identities
 *   Tracking                           : Tracking-Result | Object-Identities | Merger-Result
 *   Multicut                           : Multicut Segmentation
 *
 * SECOND INPUT (object classification, tracking, multicut)
 *   prediction_maps    -> project type "[Inputs: Raw Data, Pixel Prediction Map]"
 *   segmentation_image -> project type "[Inputs: Raw Data, Segmentation]" (binary mask)
 *   label_image        -> project type "[Inputs: Raw Data, Label Image]"   (instance labels)
 *   Each raw file <stem>.<ext> is paired with <secondInputDir>/<stem><secondInputSuffix>.<any ext>.
 *   The role must match the project type, otherwise ilastik exits with
 *   "You can only have trailing file paths if no other role was set by name".
 *
 * OUTPUT
 *   <outputDir>/<stem>_<export_source>.tiff (or .h5; spaces in the export source become "_",
 *   e.g. img_0_Simple_Segmentation.tiff); "Simple Segmentation" is a class-index image
 *   (1..N, one value per label class, no 0 background); "Probabilities" has one channel per class.
 *   The script prints ILASTIK_BATCH_OK <n files> or throws with the tail of the ilastik log.
 *
 * INPUT AXES
 *   ilastik re-uses the axis order stored in the project when it cannot read one from the file.
 *   Projects trained on HDF5 exported from Fiji (ilastik4ij) store 5-D "tzyxc", so a plain 2-D TIFF
 *   then fails with "UnsuitedAxistagsException ... No data for some axes". Set inputAxes to the
 *   file's real order (2-D grey TIFF: yx; 2-D multichannel: yxc; z-stack: zyx; movie: tyx).
 *
 * FEATURE TABLE
 *   --table_filename only works when the project's object table export was configured once in the
 *   ilastik GUI (Object Information Export > Configure Feature Table Export); otherwise ilastik stops
 *   with "You can't export the CSV object table unless you configure it in the GUI first".
 *
 * REQUIREMENTS
 *   - Same dimensionality, channel count and channel order as the training data.
 *   - The .ilp must not be open in the ilastik GUI (it is opened read-only, but the GUI may lock it).
 *   - Choose an empty output folder: existing files with the same name are overwritten.
 */

String exe = executablePath?.trim() ?: (System.getenv("ILASTIK_EXECUTABLE") ?: "")
if (!exe || !new File(exe).canExecute()) {
    throw new IllegalArgumentException("ilastik executable not found: '" + exe + "' (set executablePath or ILASTIK_EXECUTABLE)")
}
if (projectFile == null || !projectFile.isFile()) throw new IllegalArgumentException("Project not found: " + projectFile)
if (inputDir == null || !inputDir.isDirectory()) throw new IllegalArgumentException("Input folder not found: " + inputDir)
outputDir.mkdirs()

def matcher = FileSystems.getDefault().getPathMatcher("glob:" + filePattern)
List<File> rawFiles = (inputDir.listFiles() ?: [] as File[]).findAll { it.isFile() && matcher.matches(it.toPath().getFileName()) }.sort { it.name }
if (rawFiles.isEmpty()) throw new IllegalArgumentException("No files matching '" + filePattern + "' in " + inputDir)

def stemOf = { File f -> String n = f.name; int i = n.indexOf('.'); i > 0 ? n.substring(0, i) : n }

List<String> cmd = [exe, "--headless",
                    "--project=" + projectFile.absolutePath,
                    "--readonly=1",
                    "--export_source=" + exportSource,
                    "--output_format=" + outputFormat,
                    "--output_filename_format=" + new File(outputDir, "{nickname}_{result_type}").absolutePath +
                            (outputFormat == "hdf5" ? ".h5" : ".tif")]
if (inputAxes?.trim()) cmd << "--input_axes=" + inputAxes.trim()
if (tableFilename?.trim()) cmd << "--table_filename=" + tableFilename.trim()

cmd << "--raw_data"
cmd.addAll(rawFiles*.absolutePath)
if (secondInputRole != "none") {
    File secDir = new File(secondInputDir?.trim() ?: "")
    if (!secDir.isDirectory()) throw new IllegalArgumentException("Second input folder not found: " + secDir)
    List<String> second = rawFiles.collect { File raw ->
        String prefix = stemOf(raw) + (secondInputSuffix ?: "") + "."
        File match = (secDir.listFiles() ?: [] as File[]).find { it.isFile() && it.name.startsWith(prefix) }
        if (match == null) throw new IllegalArgumentException("No second input '" + prefix + "*' in " + secDir + " for " + raw.name)
        match.absolutePath
    }
    cmd << "--" + secondInputRole
    cmd.addAll(second)
}

IJ.log("[ilastik] " + rawFiles.size() + " file(s), export source '" + exportSource + "', project " + projectFile.name)
def pb = new ProcessBuilder(cmd)
def env = pb.environment()
if (numThreads >= 0) env.put("LAZYFLOW_THREADS", String.valueOf(numThreads))
env.put("LAZYFLOW_TOTAL_RAM_MB", String.valueOf(maxRamMb))
env.remove("PYTHONPATH"); env.remove("PYTHONHOME")   // ilastik ships its own Python
File logFile = new File(outputDir, "ilastik_batch.log")
pb.redirectErrorStream(true).redirectOutput(logFile)
long t0 = System.currentTimeMillis()
def proc = pb.start()
if (!proc.waitFor(6, TimeUnit.HOURS)) { proc.destroyForcibly(); throw new RuntimeException("ilastik timed out; log: " + logFile) }
int rc = proc.exitValue()
def tail = logFile.readLines().findAll { !it.startsWith("DEBUG") }.takeRight(15).join("\n")
if (rc != 0) {
    String hint = ""
    if (tail.contains("UnsuitedAxistagsException")) hint = "\nHINT: set inputAxes to the file's axis order (e.g. yx for a 2-D grey TIFF)."
    if (tail.contains("configure it in the GUI first")) hint = "\nHINT: leave tableFilename empty, or configure the table export once in the ilastik GUI and save the project."
    if (tail.contains("trailing file paths")) hint = "\nHINT: secondInputRole does not match the project type (prediction_maps / segmentation_image / label_image)."
    throw new RuntimeException("ilastik exited with code " + rc + " — log " + logFile + ":\n" + tail + hint)
}

def produced = (outputDir.listFiles() ?: [] as File[]).findAll { it.name != logFile.name && it.lastModified() >= t0 - 2000 }.collect { File f ->
    // ilastik puts the export source verbatim into {result_type} ("Simple Segmentation"); drop the spaces
    if (!f.name.contains(" ")) return f
    File g = new File(f.parentFile, f.name.replace(' ', '_')); f.renameTo(g) ? g : f
}.sort { it.name }
IJ.log("[ilastik] finished in " + ((System.currentTimeMillis() - t0) / 1000.0) + " s; wrote " + produced.size() + " file(s) to " + outputDir)
produced.take(10).each { IJ.log("  " + it.name) }
if (produced.isEmpty()) throw new RuntimeException("ilastik reported success but wrote no files — log " + logFile + ":\n" + tail)
println("ILASTIK_BATCH_OK " + produced.size())

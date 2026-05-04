// Load an SWC reconstruction and export Sholl single-value metrics as CSV.
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ File (label = "Output Sholl metrics CSV", style = "save", value = "/data/snt_validation/demo_tree_sholl_metrics_out.csv") shollCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.ShollAnalyzer
import sc.fiji.snt.analysis.TreeStatistics

/*
 * SNT - Export Sholl summary metrics from an SWC reconstruction
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Compute TreeStatistics for context
 *   3. Compute Sholl single-value metrics
 *   4. Save the metrics as a two-column CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   shollCsvFile - new CSV path for the Sholl metrics table
 *
 * IMPORTANT:
 *   - Provide an input SWC explicitly, or generate one first with
 *     GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy.
 *   - This workflow is validated for SWC inputs.
 *   - Choose a fresh output path instead of overwriting an existing file.
 */

void requireReadableSwc(File file) {
    if (file == null || !file.exists() || !file.isFile()) {
        throw new IllegalArgumentException("Input SWC file not found: " + file)
    }
    if (!file.name.toLowerCase().endsWith(".swc")) {
        throw new IllegalArgumentException("This workflow is validated for SWC inputs only: " + file.absolutePath)
    }
}

void requireFreshCsv(File file) {
    if (file == null) {
        throw new IllegalArgumentException("Output Sholl CSV must be provided")
    }
    file.parentFile?.mkdirs()
    if (file.exists()) {
        throw new IllegalArgumentException("Output Sholl CSV already exists: " + file.absolutePath)
    }
}

String csvEscape(Object value) {
    return (value == null ? "" : value.toString()).replace("\"", "\"\"")
}

requireReadableSwc(inputSwcFile)
requireFreshCsv(shollCsvFile)

println("SNT Sholl metrics export")
println("Input SWC         : " + inputSwcFile.absolutePath)
println("Sholl metrics CSV : " + shollCsvFile.absolutePath)

def tree = new Tree(inputSwcFile.absolutePath)
int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0) {
    throw new IllegalStateException("SNT loaded zero SWC nodes from: " + inputSwcFile.absolutePath)
}

def stats = new TreeStatistics(tree)
stats.summarize(false)

def sholl = new ShollAnalyzer(tree, stats)
Map shollMetrics = sholl.getSingleValueMetrics()
if (shollMetrics == null || shollMetrics.isEmpty()) {
    throw new IllegalStateException("ShollAnalyzer returned no metrics for: " + inputSwcFile.absolutePath)
}

shollCsvFile.withWriter("UTF-8") { writer ->
    writer.println("metric,value")
    shollMetrics.each { key, value ->
        writer.println("\"" + csvEscape(key) + "\",\"" + csvEscape(value) + "\"")
    }
}

if (!shollCsvFile.exists() || shollCsvFile.length() == 0) {
    throw new IllegalStateException("Could not save Sholl metrics CSV: " + shollCsvFile.absolutePath)
}

println("Loaded SWC nodes : " + nodeCount)
println("Sholl metrics    : " + shollMetrics.keySet().join(", "))
println("SNT Sholl metrics export complete")

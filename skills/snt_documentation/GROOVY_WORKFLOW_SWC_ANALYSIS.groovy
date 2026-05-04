// Analyze an SWC reconstruction with SNT and export morphometry plus Sholl metrics.
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ File (label = "Output morphometry CSV", style = "save", value = "/data/snt_validation/demo_tree_stats_out.csv") statsCsvFile
#@ File (label = "Output Sholl metrics CSV", style = "save", value = "/data/snt_validation/demo_tree_sholl_metrics_out.csv") shollCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.ShollAnalyzer
import sc.fiji.snt.analysis.SNTTable
import sc.fiji.snt.analysis.TreeStatistics

/*
 * SNT - Analyze an SWC reconstruction
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Compute tree-level morphometry using TreeStatistics
 *   3. Save the morphometry table as CSV
 *   4. Save Sholl single-value metrics as CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   statsCsvFile - new CSV path for the TreeStatistics table
 *   shollCsvFile - new CSV path for the Sholl metrics table
 *
 * IMPORTANT:
 *   - Provide an input SWC explicitly, or generate one first with
 *     GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy.
 *   - This workflow is validated for SWC inputs.
 *   - Choose fresh output paths instead of overwriting existing files.
 */

void requireReadableSwc(File file) {
    if (file == null || !file.exists() || !file.isFile()) {
        throw new IllegalArgumentException("Input SWC file not found: " + file)
    }
    if (!file.name.toLowerCase().endsWith(".swc")) {
        throw new IllegalArgumentException("This workflow is validated for SWC inputs only: " + file.absolutePath)
    }
}

void requireFreshOutput(File file, String label) {
    if (file == null) {
        throw new IllegalArgumentException(label + " must be provided")
    }
    file.parentFile?.mkdirs()
    if (file.exists()) {
        throw new IllegalArgumentException(label + " already exists: " + file.absolutePath)
    }
}

String csvEscape(Object value) {
    return (value == null ? "" : value.toString()).replace("\"", "\"\"")
}

requireReadableSwc(inputSwcFile)
requireFreshOutput(statsCsvFile, "Morphometry CSV")
requireFreshOutput(shollCsvFile, "Sholl metrics CSV")

println("SNT SWC analysis")
println("Input SWC         : " + inputSwcFile.absolutePath)
println("Morphometry CSV   : " + statsCsvFile.absolutePath)
println("Sholl metrics CSV : " + shollCsvFile.absolutePath)

def tree = new Tree(inputSwcFile.absolutePath)
int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0) {
    throw new IllegalStateException("SNT loaded zero SWC nodes from: " + inputSwcFile.absolutePath)
}

def stats = new TreeStatistics(tree)
stats.summarize(false)
def table = stats.getTable()
if (table == null || table.rowCount == 0 || table.columnCount == 0) {
    throw new IllegalStateException("TreeStatistics returned no morphometry table for: " + inputSwcFile.absolutePath)
}

def statsTable = SNTTable.fromGenericTable(table)
boolean savedStats = statsTable.save(statsCsvFile.absolutePath)
if (!savedStats || !statsCsvFile.exists() || statsCsvFile.length() == 0) {
    throw new IllegalStateException("Could not save morphometry CSV: " + statsCsvFile.absolutePath)
}

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

println("Loaded SWC nodes  : " + nodeCount)
println("Stats table shape : " + table.rowCount + " row(s), " + table.columnCount + " column(s)")
println("Sholl metrics     : " + shollMetrics.keySet().join(", "))
println("SNT SWC analysis complete")

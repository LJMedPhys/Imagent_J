// Load an SWC reconstruction and export the TreeStatistics morphometry table as CSV.
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ File (label = "Output morphometry CSV", style = "save", value = "/data/snt_validation/demo_tree_stats_out.csv") statsCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.SNTTable
import sc.fiji.snt.analysis.TreeStatistics

/*
 * SNT - Export TreeStatistics morphometry from an SWC reconstruction
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Compute tree-level morphometry using TreeStatistics
 *   3. Save the resulting table as CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   statsCsvFile - new CSV path for the TreeStatistics table
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

void requireFreshCsv(File file, String label) {
    if (file == null) {
        throw new IllegalArgumentException(label + " must be provided")
    }
    file.parentFile?.mkdirs()
    if (file.exists()) {
        throw new IllegalArgumentException(label + " already exists: " + file.absolutePath)
    }
}

requireReadableSwc(inputSwcFile)
requireFreshCsv(statsCsvFile, "Morphometry CSV")

println("SNT tree statistics export")
println("Input SWC       : " + inputSwcFile.absolutePath)
println("Morphometry CSV : " + statsCsvFile.absolutePath)

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
boolean saved = statsTable.save(statsCsvFile.absolutePath)
if (!saved || !statsCsvFile.exists() || statsCsvFile.length() == 0) {
    throw new IllegalStateException("Could not save morphometry CSV: " + statsCsvFile.absolutePath)
}

println("Loaded SWC nodes : " + nodeCount)
println("Stats table shape: " + table.rowCount + " row(s), " + table.columnCount + " column(s)")
println("SNT tree statistics export complete")

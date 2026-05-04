// Batch morphometry and Sholl summary export for all SWC reconstructions in a directory.
// Reference: official SNT script templates Measure_Multiple_Files_(With_Options).groovy,
// Sholl_Bulk_Analysis_(From_Reconstructions).groovy
#@ File (label = "Input directory of SWC reconstructions", style = "directory") inputDir
#@ String (label = "Consider only filenames containing", value = "") nameFilter
#@ File (label = "Output morphometry CSV", style = "save", value = "/data/snt_output/batch_tree_statistics.csv") statsCsvFile
#@ File (label = "Output Sholl metrics CSV", style = "save", value = "/data/snt_output/batch_sholl_metrics.csv") shollCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.ShollAnalyzer
import sc.fiji.snt.analysis.TreeStatistics

/*
 * SNT - Batch SWC analysis
 *
 * PURPOSE:
 *   1. Discover all SWC reconstructions in a directory
 *   2. Compute TreeStatistics morphometry for each reconstruction
 *   3. Compute Sholl single-value metrics for each reconstruction
 *   4. Save one row per reconstruction to two CSV files
 *
 * REQUIRED INPUTS:
 *   inputDir     - directory containing SWC files
 *   nameFilter   - optional filename substring filter
 *   statsCsvFile - new CSV path for morphometry rows
 *   shollCsvFile - new CSV path for Sholl summary rows
 *
 * IMPORTANT:
 *   - This workflow is validated for SWC inputs discovered from a directory.
 *   - It provides a headless batch export path derived from SNT's official
 *     batch templates, which otherwise open interactive measurement dialogs.
 *   - Choose fresh output paths instead of overwriting existing files.
 */

void requireReadableDirectory(File dir) {
    if (dir == null || !dir.exists() || !dir.isDirectory()) {
        throw new IllegalArgumentException("Input directory not found: " + dir)
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

String csvCell(Object value) {
    return "\"" + csvEscape(value) + "\""
}

List<File> listSwcFiles(File dir, String filterText) {
    String normalizedFilter = filterText == null ? "" : filterText
    return (dir.listFiles()?.findAll { file ->
        file.isFile() &&
            file.name.toLowerCase().endsWith(".swc") &&
            (normalizedFilter.isEmpty() || file.name.contains(normalizedFilter))
    }?.sort { a, b -> a.name <=> b.name }) ?: []
}

Map<String, Object> extractSingleRow(def table) {
    if (table == null || table.getRowCount() <= 0 || table.getColumnCount() <= 0) {
        throw new IllegalStateException("TreeStatistics returned an empty summary table")
    }
    Map<String, Object> row = new LinkedHashMap<>()
    for (int col = 0; col < table.getColumnCount(); col++) {
        row.put(table.getColumnHeader(col), table.get(col, 0))
    }
    return row
}

void writeCsv(File file, List<String> headers, List<Map<String, Object>> rows) {
    file.withWriter("UTF-8") { writer ->
        writer.println(headers.collect { header -> csvCell(header) }.join(","))
        rows.each { row ->
            writer.println(headers.collect { header -> csvCell(row.get(header)) }.join(","))
        }
    }
}

requireReadableDirectory(inputDir)
requireFreshOutput(statsCsvFile, "Morphometry CSV")
requireFreshOutput(shollCsvFile, "Sholl metrics CSV")

List<File> swcFiles = listSwcFiles(inputDir, nameFilter)
if (swcFiles.isEmpty()) {
    throw new IllegalArgumentException("No SWC files matched in directory: " + inputDir.absolutePath)
}

println("SNT batch SWC analysis")
println("Input directory   : " + inputDir.absolutePath)
println("Filename filter   : " + (nameFilter?.trim() ? nameFilter : "(none)"))
println("Morphometry CSV   : " + statsCsvFile.absolutePath)
println("Sholl metrics CSV : " + shollCsvFile.absolutePath)
println("Matched SWC files : " + swcFiles.size())

List<Map<String, Object>> statsRows = []
List<Map<String, Object>> shollRows = []
LinkedHashSet<String> statsHeaders = new LinkedHashSet<>(["source_file", "source_path", "tree_label", "node_count"])
LinkedHashSet<String> shollHeaders = new LinkedHashSet<>(["source_file", "source_path", "tree_label", "node_count"])

swcFiles.each { swcFile ->
    def tree = new Tree(swcFile.absolutePath)
    int nodeCount = tree.getNodesAsSWCPoints().size()
    if (nodeCount <= 0) {
        throw new IllegalStateException("SNT loaded zero SWC nodes from: " + swcFile.absolutePath)
    }

    def stats = new TreeStatistics(tree)
    stats.summarize(false)
    Map<String, Object> statsRow = new LinkedHashMap<>()
    statsRow.put("source_file", swcFile.name)
    statsRow.put("source_path", swcFile.absolutePath)
    statsRow.put("tree_label", tree.getLabel())
    statsRow.put("node_count", nodeCount)
    extractSingleRow(stats.getTable()).each { key, value ->
        statsRow.put(key, value)
    }
    statsHeaders.addAll(statsRow.keySet())
    statsRows.add(statsRow)

    def sholl = new ShollAnalyzer(tree, stats)
    Map<String, Object> shollMetrics = new LinkedHashMap<>()
    shollMetrics.putAll(sholl.getSingleValueMetrics())
    if (shollMetrics.isEmpty()) {
        throw new IllegalStateException("ShollAnalyzer returned no metrics for: " + swcFile.absolutePath)
    }

    Map<String, Object> shollRow = new LinkedHashMap<>()
    shollRow.put("source_file", swcFile.name)
    shollRow.put("source_path", swcFile.absolutePath)
    shollRow.put("tree_label", tree.getLabel())
    shollRow.put("node_count", nodeCount)
    shollMetrics.each { key, value ->
        shollRow.put(key, value)
    }
    shollHeaders.addAll(shollRow.keySet())
    shollRows.add(shollRow)

    println("Processed         : " + swcFile.name + " (" + nodeCount + " nodes)")
}

writeCsv(statsCsvFile, new ArrayList<>(statsHeaders), statsRows)
writeCsv(shollCsvFile, new ArrayList<>(shollHeaders), shollRows)

if (!statsCsvFile.exists() || statsCsvFile.length() == 0) {
    throw new IllegalStateException("Could not save morphometry CSV: " + statsCsvFile.absolutePath)
}
if (!shollCsvFile.exists() || shollCsvFile.length() == 0) {
    throw new IllegalStateException("Could not save Sholl metrics CSV: " + shollCsvFile.absolutePath)
}

println("Rows written (stats) : " + statsRows.size())
println("Rows written (Sholl) : " + shollRows.size())
println("SNT batch SWC analysis complete")

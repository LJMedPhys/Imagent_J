// Compartment-specific morphometry with volume and bounding box measurements.
// Reference: official SNT script templates Analysis_Demo.py, Strahler_Analysis.py
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ String (label = "Compartment", choices = {"all", "axon", "dendrites"}, value = "all") compartment
#@ File (label = "Output morphometry CSV", style = "save", value = "/data/snt_output/subtree_metrics.csv") statsCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.SNTTable
import sc.fiji.snt.analysis.TreeStatistics

/*
 * SNT - Compartment-specific morphometry
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Extract a compartment subtree (axon, dendrites, or all)
 *   3. Compute tree-level morphometry via TreeStatistics
 *   4. Report additional geometric measurements (volume, bounding box)
 *   5. Save the morphometry table as CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   compartment  - "all", "axon", or "dendrites"
 *   statsCsvFile - new CSV path for the morphometry table
 *
 * IMPORTANT:
 *   - Provide an input SWC explicitly, or generate one first with
 *     GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy.
 *   - tree.subTree("axon") / tree.subTree("dendrites") extracts the compartment.
 *   - The SWC file must contain appropriate SWC type labels for compartment
 *     extraction to work (type 2 = axon, type 3/4 = dendrite).
 *   - tree.getApproximatedVolume() estimates volume from path radii.
 *   - tree.getBoundingBox().getDimensions() reports spatial extent.
 */

void requireReadableSwc(File file) {
    if (file == null || !file.exists() || !file.isFile())
        throw new IllegalArgumentException("Input SWC file not found: " + file)
    if (!file.name.toLowerCase().endsWith(".swc"))
        throw new IllegalArgumentException("This workflow is validated for SWC inputs only: " + file.absolutePath)
}

void requireFreshOutput(File file, String label) {
    if (file == null) throw new IllegalArgumentException(label + " must be provided")
    file.parentFile?.mkdirs()
    if (file.exists()) throw new IllegalArgumentException(label + " already exists: " + file.absolutePath)
}

requireReadableSwc(inputSwcFile)
requireFreshOutput(statsCsvFile, "Morphometry CSV")

println("SNT subtree metrics")
println("Input SWC   : " + inputSwcFile.absolutePath)
println("Compartment : " + compartment)
println("Output CSV  : " + statsCsvFile.absolutePath)

def tree = new Tree(inputSwcFile.absolutePath)
int totalNodes = tree.getNodesAsSWCPoints().size()
if (totalNodes <= 0)
    throw new IllegalStateException("SNT loaded zero SWC nodes from: " + inputSwcFile.absolutePath)

// Extract compartment subtree if requested
def analysisTree = tree
if (compartment != "all") {
    analysisTree = tree.subTree(compartment)
    if (analysisTree == null || analysisTree.isEmpty())
        throw new IllegalStateException("No '" + compartment + "' compartment found in: " + inputSwcFile.absolutePath)
}

// Standard morphometry table
def stats = new TreeStatistics(analysisTree)
stats.summarize(false)
def table = stats.getTable()
if (table == null || table.rowCount == 0 || table.columnCount == 0)
    throw new IllegalStateException("TreeStatistics returned no morphometry data for: " + compartment)

def csvTable = SNTTable.fromGenericTable(table)
boolean saved = csvTable.save(statsCsvFile.absolutePath)
if (!saved || !statsCsvFile.exists() || statsCsvFile.length() == 0)
    throw new IllegalStateException("Could not save morphometry CSV: " + statsCsvFile.absolutePath)

// Additional geometric measurements
double volume = analysisTree.getApproximatedVolume()
def bb = analysisTree.getBoundingBox()
def dims = bb.getDimensions()

println("Total SWC nodes     : " + totalNodes)
println("Subtree nodes       : " + analysisTree.getNodesAsSWCPoints().size())
println("Approx. volume      : " + volume + " cubic units")
println("Bounding box (WxHxD): " + dims[0] + " x " + dims[1] + " x " + dims[2])
println("Table shape         : " + table.rowCount + " row(s), " + table.columnCount + " column(s)")
println("SNT subtree metrics complete")

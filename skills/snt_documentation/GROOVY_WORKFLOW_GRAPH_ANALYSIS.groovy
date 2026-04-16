// Graph theory analysis of a neuronal reconstruction.
// Reference: official SNT script template Graph_Analysis_Demo.py
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ File (label = "Output graph metrics CSV", style = "save", value = "/data/snt_output/graph_metrics.csv") metricsCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.graph.DirectedWeightedGraph

/*
 * SNT - Graph theory analysis
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Build a directed weighted graph (edge weights = Euclidean distances)
 *   3. Compute graph metrics: vertex/edge counts, tips, graph diameter
 *   4. Also compute the longest directed root-to-tip geodesic
 *   5. Compute metrics on the simplified (branch-point-only) graph
 *   6. Save all metrics as CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   metricsCsvFile - new CSV path for graph metrics
 *
 * IMPORTANT:
 *   - Provide an input SWC explicitly, or generate one first with
 *     GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy.
 *   - tree.getGraph() returns a DirectedWeightedGraph extending JGraphT.
 *   - graph.getLongestPath(false) computes the undirected graph diameter:
 *     the longest shortest path between any two nodes.
 *   - The boolean controls directedness:
 *       true  = directed (root → tips, always includes root)
 *       false = undirected (may occur between any pair of tips)
 *   - graph.getSimplifiedGraph() retains only root, branch points, and tips
 *     while preserving global topology.
 *   - graph.getShortestPath(v1, v2) computes arbitrary shortest paths.
 *   - JGraphT algorithms (e.g. DijkstraShortestPath) can be used directly on
 *     the graph object.
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

String csvEscape(Object value) {
    return (value == null ? "" : value.toString()).replace("\"", "\"\"")
}

requireReadableSwc(inputSwcFile)
requireFreshOutput(metricsCsvFile, "Graph metrics CSV")

println("SNT graph analysis")
println("Input SWC  : " + inputSwcFile.absolutePath)
println("Output CSV : " + metricsCsvFile.absolutePath)

def tree = new Tree(inputSwcFile.absolutePath)
int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0)
    throw new IllegalStateException("SNT loaded zero SWC nodes from: " + inputSwcFile.absolutePath)

// Build directed weighted graph from tree nodes
def graph = tree.getGraph()
def simplified = graph.getSimplifiedGraph()
def root = graph.getRoot()
def tips = graph.getTips()

// Compute both the undirected graph diameter and the directed root-to-tip path.
def undirectedLongestPath = graph.getLongestPath(false)
double graphDiameter = undirectedLongestPath.getLength()
int graphDiameterNodes = undirectedLongestPath.size()

def directedLongestPath = graph.getLongestPath(true)
double rootToTipLongestPath = directedLongestPath.getLength()
int rootToTipLongestPathNodes = directedLongestPath.size()

// Write metrics CSV
metricsCsvFile.withWriter("UTF-8") { writer ->
    writer.println("metric,value")
    writer.println("\"vertex_count\"," + graph.vertexSet().size())
    writer.println("\"edge_count\"," + graph.edgeSet().size())
    writer.println("\"simplified_vertex_count\"," + simplified.vertexSet().size())
    writer.println("\"simplified_edge_count\"," + simplified.edgeSet().size())
    writer.println("\"tip_count\"," + tips.size())
    writer.println("\"graph_diameter\"," + graphDiameter)
    writer.println("\"graph_diameter_nodes\"," + graphDiameterNodes)
    writer.println("\"root_to_tip_longest_path\"," + rootToTipLongestPath)
    writer.println("\"root_to_tip_longest_path_nodes\"," + rootToTipLongestPathNodes)
}

if (!metricsCsvFile.exists() || metricsCsvFile.length() == 0)
    throw new IllegalStateException("Could not save graph metrics CSV: " + metricsCsvFile.absolutePath)

println("Vertices          : " + graph.vertexSet().size())
println("Edges             : " + graph.edgeSet().size())
println("Simplified verts  : " + simplified.vertexSet().size())
println("Simplified edges  : " + simplified.edgeSet().size())
println("Tips              : " + tips.size())
println("Graph diameter    : " + graphDiameter)
println("Diameter nodes     : " + graphDiameterNodes)
println("Root->tip path    : " + rootToTipLongestPath)
println("Root->tip nodes   : " + rootToTipLongestPathNodes)
println("SNT graph analysis complete")

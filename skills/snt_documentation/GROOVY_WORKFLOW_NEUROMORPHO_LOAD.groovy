// Download a neuronal reconstruction from NeuroMorpho.org and save as SWC.
// Reference: official SNT script templates Analysis_Demo.py, Branch_Angles_vs_Distance_To_Soma.py
#@ String (label = "NeuroMorpho cell name", value = "Adol-20100419cell1") cellName
#@ File (label = "Output SWC file", style = "save", value = "/data/snt_output/neuromorpho_cell.swc") outputSwcFile

import sc.fiji.snt.Tree
import sc.fiji.snt.io.NeuroMorphoLoader

/*
 * SNT - Download reconstruction from NeuroMorpho.org
 *
 * PURPOSE:
 *   1. Connect to the NeuroMorpho.org database
 *   2. Download the specified neuron reconstruction
 *   3. Save it as a local SWC file
 *
 * REQUIRED INPUTS:
 *   cellName      - NeuroMorpho.org cell name (e.g. "Adol-20100419cell1")
 *   outputSwcFile - new SWC path for the downloaded reconstruction
 *
 * IMPORTANT:
 *   - Requires internet connection.
 *   - Cell names can be found at http://neuromorpho.org by browsing or searching.
 *   - Two loader patterns are available:
 *       Instance: new NeuroMorphoLoader() → loader.getTree("cellName")
 *       Static:   NeuroMorphoLoader.get("cellName") → Tree directly
 *   - The downloaded Tree can be analyzed with TreeStatistics, ShollAnalyzer,
 *     or any other SNT analysis tool, and further decomposed with
 *     tree.subTree("axon") / tree.subTree("dendrites").
 */

void requireFreshSwc(File file) {
    if (file == null) throw new IllegalArgumentException("Output SWC path must be provided")
    file.parentFile?.mkdirs()
    if (file.exists()) throw new IllegalArgumentException("Output SWC already exists: " + file.absolutePath)
    if (!file.name.toLowerCase().endsWith(".swc"))
        throw new IllegalArgumentException("Output file must use the .swc extension: " + file.absolutePath)
}

requireFreshSwc(outputSwcFile)

println("SNT NeuroMorpho.org download")
println("Cell name  : " + cellName)
println("Output SWC : " + outputSwcFile.absolutePath)

// Check database availability
def loader = new NeuroMorphoLoader()
if (!loader.isDatabaseAvailable())
    throw new IllegalStateException("Cannot connect to NeuroMorpho.org. Check internet connection.")

// Download reconstruction
def tree = loader.getTree(cellName)
if (tree == null || tree.isEmpty())
    throw new IllegalStateException("No reconstruction found for cell: " + cellName)

int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0)
    throw new IllegalStateException("Downloaded tree has zero nodes for cell: " + cellName)

// Save as SWC
boolean saved = tree.saveAsSWC(outputSwcFile.absolutePath)
if (!saved || !outputSwcFile.exists() || outputSwcFile.length() == 0)
    throw new IllegalStateException("Could not save SWC file: " + outputSwcFile.absolutePath)

println("Downloaded nodes : " + nodeCount)
println("Label            : " + tree.getLabel())
println("SNT NeuroMorpho.org download complete")

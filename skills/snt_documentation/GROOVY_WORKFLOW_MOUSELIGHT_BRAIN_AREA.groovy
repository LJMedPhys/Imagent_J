// Download a MouseLight neuron and analyze its brain area projections.
// Reference: official SNT script templates Analysis_Demo.py, Brain_Compartment_Analysis_Demo.py
#@ String (label = "MouseLight cell ID", value = "AA0788") cellId
#@ String (label = "Compartment", choices = {"axon", "dendrites"}, value = "axon") compartment
#@ Integer (label = "Max ontology depth", value = 6) maxOntologyDepth
#@ File (label = "Output SWC file", style = "save", value = "/data/snt_output/mouselight_neuron.swc") outputSwcFile
#@ File (label = "Output morphometry CSV", style = "save", value = "/data/snt_output/mouselight_stats.csv") statsCsvFile
#@ File (label = "Output brain area CSV", style = "save", value = "/data/snt_output/mouselight_brain_areas.csv") areaCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.NodeStatistics
import sc.fiji.snt.analysis.SNTTable
import sc.fiji.snt.analysis.TreeStatistics
import sc.fiji.snt.annotation.AllenUtils
import sc.fiji.snt.io.MouseLightLoader

/*
 * SNT - Download MouseLight neuron and analyze brain area projections
 *
 * PURPOSE:
 *   1. Download a neuron from the MouseLight database
 *   2. Save the reconstruction as SWC
 *   3. Compute morphometry (TreeStatistics)
 *   4. Report soma location and brain compartment
 *   5. Analyze terminal projections across Allen CCF brain areas
 *   6. Save brain area distribution as CSV
 *
 * REQUIRED INPUTS:
 *   cellId           - MouseLight cell ID (e.g. "AA0788", "AA0100", "AA0012")
 *   compartment      - "axon" or "dendrites"
 *   maxOntologyDepth - Allen CCF ontology depth for grouping (e.g. 6 for mid-level)
 *   outputSwcFile    - new SWC path for the downloaded reconstruction
 *   statsCsvFile     - new CSV path for morphometry table
 *   areaCsvFile      - new CSV path for brain area distribution
 *
 * IMPORTANT:
 *   - Requires internet connection.
 *   - MouseLight neurons are registered to the Allen CCF (Common Coordinate Framework).
 *     Each node carries brain area annotation accessible via node.getAnnotation().
 *   - loader.getSomaLocation() returns the soma position in CCF coordinates.
 *   - loader.getSomaCompartment() returns the annotated brain area of the soma.
 *   - Compartment.getOntologyDepth() and .getAncestor(delta) navigate the brain
 *     ontology hierarchy. Negative delta goes toward the root of the ontology.
 *   - AllenUtils.brainCenter() returns the CCF midline coordinate, useful for
 *     ipsilateral vs contralateral analysis.
 *   - For GUI-based visualization (histograms, charts), use:
 *       NodeStatistics(tips).getAnnotatedHistogram(depth).show()
 *       TreeStatistics.getAnnotatedLengthHistogram(depth).show()
 *       TreeStatistics.getAnnotatedLengthHistogram(depth, "ratio").show()
 */

void requireFreshOutput(File file, String label) {
    if (file == null) throw new IllegalArgumentException(label + " must be provided")
    file.parentFile?.mkdirs()
    if (file.exists()) throw new IllegalArgumentException(label + " already exists: " + file.absolutePath)
}

String csvEscape(Object value) {
    return (value == null ? "" : value.toString()).replace("\"", "\"\"")
}

requireFreshOutput(outputSwcFile, "Output SWC")
requireFreshOutput(statsCsvFile, "Morphometry CSV")
requireFreshOutput(areaCsvFile, "Brain area CSV")

println("SNT MouseLight brain area analysis")
println("Cell ID          : " + cellId)
println("Compartment      : " + compartment)
println("Ontology depth   : " + maxOntologyDepth)

// Connect and download
def loader = new MouseLightLoader(cellId)
if (!loader.isDatabaseAvailable())
    throw new IllegalStateException("Cannot connect to MouseLight database. Check internet connection.")
if (!loader.idExists())
    throw new IllegalStateException("Cell ID not found in MouseLight database: " + cellId)

def tree = loader.getTree(compartment)
if (tree == null || tree.isEmpty())
    throw new IllegalStateException("No " + compartment + " data for cell: " + cellId)

// Save as SWC
boolean savedSwc = tree.saveAsSWC(outputSwcFile.absolutePath)
if (!savedSwc || !outputSwcFile.exists() || outputSwcFile.length() == 0)
    throw new IllegalStateException("Could not save SWC: " + outputSwcFile.absolutePath)

// Report soma info
def somaLoc = loader.getSomaLocation()
def somaCpt = loader.getSomaCompartment()
def somaArea = somaCpt
if (somaCpt.getOntologyDepth() > maxOntologyDepth) {
    somaArea = somaCpt.getAncestor(maxOntologyDepth - somaCpt.getOntologyDepth())
}

println("Soma location    : " + somaLoc)
println("Soma compartment : " + somaCpt.name() + " (" + somaCpt.acronym() + ")")
println("Soma area (depth " + maxOntologyDepth + "): " + somaArea.name() + " (" + somaArea.acronym() + ")")

// Compute morphometry
def tStats = new TreeStatistics(tree)
tStats.summarize(false)
def table = tStats.getTable()
if (table != null && table.rowCount > 0) {
    def csvTable = SNTTable.fromGenericTable(table)
    csvTable.save(statsCsvFile.absolutePath)
}

// Analyze terminal projections across brain areas
def tips = tStats.getTips()
def areaCounts = [:] as LinkedHashMap
int annotatedTips = 0
int unannotatedTips = 0

tips.each { tip ->
    def annotation = tip.getAnnotation()
    if (annotation != null) {
        // Navigate to the desired ontology depth
        def area = annotation
        if (area.getOntologyDepth() > maxOntologyDepth) {
            area = area.getAncestor(maxOntologyDepth - area.getOntologyDepth())
        }
        if (area != null) {
            String areaName = area.name() + " (" + area.acronym() + ")"
            areaCounts[areaName] = (areaCounts[areaName] ?: 0) + 1
            annotatedTips++
        } else {
            unannotatedTips++
        }
    } else {
        unannotatedTips++
    }
}

// Check for contralateral projections
def midlineX = AllenUtils.brainCenter().getX()
def somaX = somaLoc.getX()
int ipsiCount = 0
int contraCount = 0
boolean somaIsLeft = (somaX < midlineX)

tips.each { tip ->
    double tipX = tip.getX()
    boolean tipIsLeft = (tipX < midlineX)
    if (tipIsLeft == somaIsLeft) {
        ipsiCount++
    } else {
        contraCount++
    }
}

// Write brain area distribution CSV
areaCsvFile.withWriter("UTF-8") { writer ->
    writer.println("brain_area,tip_count")
    // Sort by count descending
    areaCounts.sort { -it.value }.each { area, count ->
        writer.println("\"" + csvEscape(area) + "\"," + count)
    }
    writer.println("\"(unannotated)\"," + unannotatedTips)
    writer.println("")
    writer.println("laterality,tip_count")
    writer.println("\"ipsilateral\"," + ipsiCount)
    writer.println("\"contralateral\"," + contraCount)
}

if (!areaCsvFile.exists() || areaCsvFile.length() == 0)
    throw new IllegalStateException("Could not save brain area CSV: " + areaCsvFile.absolutePath)

println("Total tips       : " + tips.size())
println("Annotated tips   : " + annotatedTips)
println("Brain areas hit  : " + areaCounts.size())
println("Ipsilateral      : " + ipsiCount)
println("Contralateral    : " + contraCount)
println("SNT MouseLight brain area analysis complete")

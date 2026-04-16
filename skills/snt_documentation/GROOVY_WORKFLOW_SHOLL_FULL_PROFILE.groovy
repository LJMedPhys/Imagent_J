// Full Sholl profile analysis with polynomial fitting and extensive statistics.
// Reference: official SNT script template Sholl_Extensive_Stats_Demo.groovy
#@ File (label = "Input SWC reconstruction") inputSwcFile
#@ Double (label = "Sholl step size (0 = auto)", value = 0) stepSize
#@ File (label = "Output Sholl stats CSV", style = "save", value = "/data/snt_output/sholl_full_stats.csv") statsCsvFile

import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.sholl.*
import sc.fiji.snt.analysis.sholl.math.*
import sc.fiji.snt.analysis.sholl.parsers.*

/*
 * SNT - Full Sholl profile analysis with polynomial fitting
 *
 * PURPOSE:
 *   1. Load an SWC reconstruction from disk
 *   2. Parse into a Sholl profile using TreeParser
 *   3. Determine the best polynomial fit (degree 2–30)
 *   4. Compute extensive Sholl statistics for both sampled and fitted data
 *   5. Compute normalized Sholl decay and determination ratio
 *   6. Save all metrics as CSV
 *
 * REQUIRED INPUTS:
 *   inputSwcFile - existing SWC reconstruction
 *   stepSize     - sampling step in physical units (0 for automatic)
 *   statsCsvFile - new CSV path for the Sholl statistics
 *
 * IMPORTANT:
 *   - Provide an input SWC explicitly, or generate one first with
 *     GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy.
 *   - TreeParser converts a Tree into a Sholl Profile (radius → intersection count).
 *   - This workflow uses tree.getRoot() as the analysis center because generic SWC
 *     files do not reliably carry the morphology tags needed by ROOT_NODES_DENDRITE.
 *   - LinearProfileStats provides all standard Sholl metrics for both sampled and
 *     polynomial-fitted data. Methods accept a boolean: false = sampled, true = fitted.
 *   - NormalizedProfileStats computes Sholl decay using semi-log or log-log regression,
 *     with the method chosen automatically.
 *   - findBestFit(minDeg, maxDeg, rSqThreshold, pValue) iteratively tests polynomial
 *     degrees and returns the degree with the highest adjusted R² that passes a
 *     Kolmogorov–Smirnov goodness-of-fit test.
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
requireFreshOutput(statsCsvFile, "Sholl stats CSV")

println("SNT full Sholl profile analysis")
println("Input SWC       : " + inputSwcFile.absolutePath)
println("Step size       : " + (stepSize == 0 ? "auto" : stepSize))
println("Output stats CSV: " + statsCsvFile.absolutePath)

// Load tree
def tree = new Tree(inputSwcFile.absolutePath)
int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0)
    throw new IllegalStateException("SNT loaded zero SWC nodes from: " + inputSwcFile.absolutePath)

// Parse tree into a Sholl profile centered on the root node.
def parser = new TreeParser(tree)
parser.setCenter(tree.getRoot())
if (stepSize > 0)
    parser.setStepSize(stepSize)
parser.parse()
if (!parser.successful())
    throw new IllegalStateException("Sholl parsing failed for: " + inputSwcFile.absolutePath)

def profile = parser.getProfile()

// Linear profile statistics with polynomial fitting
def lStats = new LinearProfileStats(profile)

// Find best polynomial fit: degrees 2–30, adjusted R² ≥ 0.70, K-S p ≥ 0.05
int bestDegree = lStats.findBestFit(2, 30, 0.70, 0.05)
double bestRSq = lStats.getRSquaredOfFit(true)
double ksPValue = lStats.getKStestOfFit()

// Normalized profile statistics (Sholl decay)
def nStats = new NormalizedProfileStats(profile, ShollStats.AREA)

// Write all metrics to CSV
statsCsvFile.withWriter("UTF-8") { writer ->
    writer.println("metric,sampled,fitted")

    // Basic statistics (false = sampled data, true = fitted data)
    writer.println("\"min\"," + lStats.getMin(false) + "," + lStats.getMin(true))
    writer.println("\"max\"," + lStats.getMax(false) + "," + lStats.getMax(true))
    writer.println("\"mean\"," + lStats.getMean(false) + "," + lStats.getMean(true))
    writer.println("\"median\"," + lStats.getMedian(false) + "," + lStats.getMedian(true))
    writer.println("\"sum\"," + lStats.getSum(false) + "," + lStats.getSum(true))
    writer.println("\"variance\"," + lStats.getVariance(false) + "," + lStats.getVariance(true))
    writer.println("\"kurtosis\"," + lStats.getKurtosis(false) + "," + lStats.getKurtosis(true))
    writer.println("\"skewness\"," + lStats.getSkewness(false) + "," + lStats.getSkewness(true))

    // Sholl-specific metrics
    writer.println("\"ramification_index\"," + lStats.getRamificationIndex(false) + "," + lStats.getRamificationIndex(true))
    writer.println("\"enclosing_radius\"," + lStats.getEnclosingRadius(false, 1) + "," + lStats.getEnclosingRadius(true, 1))
    writer.println("\"primary_branches\"," + lStats.getPrimaryBranches(false) + "," + lStats.getPrimaryBranches(true))
    writer.println("\"intersecting_radii\"," + lStats.getIntersectingRadii(false) + "," + lStats.getIntersectingRadii(true))

    // Polynomial fit info (single-value, not sampled/fitted split)
    writer.println("\"best_fit_degree\"," + bestDegree + ",")
    writer.println("\"r_squared_adjusted\"," + bestRSq + ",")
    writer.println("\"ks_test_p_value\"," + ksPValue + ",")

    // Normalized decay statistics
    writer.println("\"normalization_method\",\"" + csvEscape(nStats.getMethodDescription()) + "\",")
    writer.println("\"sholl_decay\"," + nStats.getShollDecay() + ",")
    writer.println("\"determination_ratio\"," + nStats.getDeterminationRatio() + ",")
}

if (!statsCsvFile.exists() || statsCsvFile.length() == 0)
    throw new IllegalStateException("Could not save Sholl stats CSV: " + statsCsvFile.absolutePath)

println("Loaded SWC nodes     : " + nodeCount)
println("Best fit degree      : " + bestDegree)
println("Adjusted R²          : " + bestRSq)
println("K-S p-value          : " + ksPValue)
println("Normalization method : " + nStats.getMethodDescription())
println("Sholl decay          : " + nStats.getShollDecay())
println("Determination ratio  : " + nStats.getDeterminationRatio())
println("SNT full Sholl profile analysis complete")

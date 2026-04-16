# SNT - Script API Reference

This file documents the SNT Java API calls adopted by this skill, organized by functional domain. All API calls are sourced from the official SNT script templates and validated against their usage patterns.

---

## 1. Tree I/O — Loading and Saving Reconstructions

### 1.1 Load from local file

```groovy
import sc.fiji.snt.Tree

// Constructor with path (SWC)
def tree = new Tree("/path/to/reconstruction.swc")

// Static method (supports .swc, .traces, .json, and other formats)
def tree = Tree.fromFile("/path/to/file")

// Load multiple trees from a single file
def trees = Tree.listFromFile("/path/to/file")
```

Sanity check: `tree.getNodesAsSWCPoints().size()` should be > 0.

### 1.2 Load from online databases

```groovy
import sc.fiji.snt.io.MouseLightLoader
import sc.fiji.snt.io.NeuroMorphoLoader

// MouseLight (Allen CCF-registered, carries brain area annotations)
def loader = new MouseLightLoader("AA0788")
loader.isDatabaseAvailable()  // check connectivity
loader.idExists()              // check cell ID validity
def axon = loader.getTree("axon")
def dend = loader.getTree("dendrites")
def somaLoc = loader.getSomaLocation()      // PointInImage
def somaCpt = loader.getSomaCompartment()    // BrainAnnotation

// NeuroMorpho.org
def nmLoader = new NeuroMorphoLoader()
nmLoader.isDatabaseAvailable()
def tree = nmLoader.getTree("Adol-20100419cell1")

// Static alternative
def tree = NeuroMorphoLoader.get("cellName")
```

Both loaders require internet. MouseLight trees carry Allen CCF brain area annotations on every node; NeuroMorpho trees may carry node radii.

### 1.3 Create demo trees

```groovy
#@ SNTService snt

def tree = snt.demoTree()             // default demo
def tree = snt.demoTree("pyramidal")  // specific type
def trees = snt.demoTrees()           // collection of demo trees
```

### 1.4 Save as SWC

```groovy
boolean ok = tree.saveAsSWC("/path/to/output.swc")
```

### 1.5 Compartment subtree extraction

```groovy
def axon = tree.subTree("axon")
def dend = tree.subTree("dendrites")
// SWC type mapping: 2 = axon, 3 = basal dendrite, 4 = apical dendrite
// tree.isEmpty() checks if the subtree has nodes
```

This is used in `GROOVY_WORKFLOW_SUBTREE_METRICS.groovy`.

### 1.6 Workflow bootstrap

The SNT skill does not ship a bundled SWC sample.

- Provide your own `inputSwcFile` for all analysis workflows.
- Or run `GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy` first to generate
  `/data/snt_validation/demo_tree_from_service.swc`.

### 1.7 Load multiple reconstructions from a directory

```groovy
import sc.fiji.snt.Tree

def trees = Tree.listFromDir("/path/to/reconstructions")
def filteredTrees = Tree.listFromDir("/path/to/reconstructions", "substring-filter")
```

`Tree.listFromDir()` is the official batch entry point used by SNT's bundled
batch scripts. For headless batch exports, iterate explicit SWC files and reuse
`TreeStatistics` plus `ShollAnalyzer` so you can preserve source filenames in
your output tables.

---

## 2. Tree Morphometry — TreeStatistics

### 2.1 Basic morphometry table

```groovy
import sc.fiji.snt.analysis.TreeStatistics
import sc.fiji.snt.analysis.SNTTable

def stats = new TreeStatistics(tree)
stats.summarize(false)            // populate the summary table
def table = stats.getTable()      // DefaultGenericTable with one row per tree

// Save as CSV
def csvTable = SNTTable.fromGenericTable(table)
csvTable.save("/path/to/stats.csv")
```

Table columns include: cable length, branch counts, tip counts, path radius summary, Horton-Strahler root number, path order summary.

### 2.2 Named metric queries

```groovy
// Get summary statistics for a specific metric
def summary = stats.getSummaryStats("inter-node distance")
summary.getMean()
summary.getMin()
summary.getMax()

// Known metric strings (same as TreeStatistics constants):
//   "inter-node distance"  (TreeStatistics.INTER_NODE_DISTANCE)
//   "Path mean radius"     (TreeStatistics.PATH_MEAN_RADIUS)
```

### 2.3 Histogram generation (requires display)

```groovy
def hist = stats.getHistogram("inter-node distance")
hist.show()  // opens a chart window
```

### 2.4 Geometric measurements

```groovy
// Approximate volume from path radii
double volume = tree.getApproximatedVolume()

// Minimum bounding box
def bb = tree.getBoundingBox()
def dims = bb.getDimensions()  // [width, height, depth] in calibrated units
```

### 2.5 Branch points and tips

```groovy
def tips = stats.getTips()           // collection of tip nodes
def bps = stats.getBranchPoints()    // collection of branch point nodes

// Bifurcation angles at branch points
def angles = stats.getRemoteBifAngles()  // List<Double> of angles in degrees
```

### 2.6 Multi-tree statistics

```groovy
// Compute statistics across a collection of trees for a given metric
def collectionStats = TreeStatistics.fromCollection(trees, metric)
```

### 2.7 Path-level iteration

```groovy
for (path in tree.list()) {
    double r = path.getMeanRadius()
    int order = path.getOrder()           // centrifugal path order
    double len = path.getLength()
}
```

These calls are used in `GROOVY_WORKFLOW_SWC_ANALYSIS.groovy`, `GROOVY_WORKFLOW_TREE_STATISTICS_FROM_SWC.groovy`, and `GROOVY_WORKFLOW_SUBTREE_METRICS.groovy`.

---

## 3. Sholl Analysis

### 3.1 Basic Sholl summary metrics

```groovy
import sc.fiji.snt.analysis.ShollAnalyzer

def sholl = new ShollAnalyzer(tree, stats)
Map metrics = sholl.getSingleValueMetrics()
// Keys: "Max (fitted)", "Max (fitted) radius", "Mean", "Sum",
//       "Enclosing radius", "Ramification index", "Decay", "Intercept",
//       "Degree of Polynomial fit"
```

This is used in `GROOVY_WORKFLOW_SHOLL_METRICS_FROM_SWC.groovy`.

### 3.2 Full Sholl profile via TreeParser

```groovy
import sc.fiji.snt.analysis.sholl.*
import sc.fiji.snt.analysis.sholl.math.*
import sc.fiji.snt.analysis.sholl.parsers.*

// Parse tree into a Sholl profile (radius -> intersection count)
def parser = new TreeParser(tree)
parser.setCenter(tree.getRoot())  // robust default for generic SWC input
parser.setStepSize(10)  // sampling step in physical units (e.g. microns)
parser.parse()

if (parser.successful()) {
    def profile = parser.getProfile()
    // Profile represents the sampled radius-vs-intersection-count data
}
```

### 3.3 Linear profile statistics and polynomial fitting

```groovy
def lStats = new LinearProfileStats(profile)

// Automatic best-fit determination
int bestDeg = lStats.findBestFit(
    2,     // lowest polynomial degree
    30,    // highest polynomial degree
    0.70,  // minimum adjusted R²
    0.05   // K-S test p-value threshold
)

// Manual polynomial fit
lStats.fitPolynomial(degree)
double pValue = lStats.getKStestOfFit()       // K-S goodness-of-fit p-value
double rSq    = lStats.getRSquaredOfFit(true)  // adjusted R²

// All metric getters accept boolean: false = sampled data, true = fitted data
lStats.getMin(false)
lStats.getMax(false)
lStats.getMean(false)
lStats.getMedian(false)
lStats.getSum(false)
lStats.getVariance(false)
lStats.getSumSq(false)
lStats.getKurtosis(false)
lStats.getSkewness(false)
lStats.getRamificationIndex(false)
lStats.getEnclosingRadius(false, 1)
lStats.getPrimaryBranches(false)
lStats.getIntersectingRadii(false)
lStats.getCentroid(false)
lStats.getPolygonCentroid(false)
lStats.getMaxima(false)
lStats.getCenteredMaximum(false)
```

### 3.4 Normalized profile statistics (Sholl decay)

```groovy
// Automatically selects semi-log or log-log regression
def nStats = new NormalizedProfileStats(profile, ShollStats.AREA)
nStats.getMethodDescription()    // "Semi-log" or "Log-log"
nStats.getShollDecay()
nStats.getDeterminationRatio()

// Restrict regression to a percentile range
nStats.restrictRegToPercentile(10, 90)
nStats.getRSquaredOfFit()
nStats.resetRegression()
```

### 3.5 Image-based Sholl (requires image; GUI for display)

```groovy
import sc.fiji.snt.analysis.sholl.parsers.ImageParser2D
import sc.fiji.snt.analysis.sholl.parsers.ImageParser3D

// 2D image
def parser2d = new ImageParser2D(imp)
parser2d.setThreshold(lower, upper)
parser2d.setCenterPx(x, y)
parser2d.setRadiiSpan(...)
parser2d.setHemiShells(true)
parser2d.parse()
def profile = parser2d.getProfile()
profile.trimZeroCounts()

// 3D image
def parser3d = new ImageParser3D(imp)
parser3d.setCenter(x, y, z)
parser3d.parse()
```

### 3.6 Tabular data Sholl

```groovy
import sc.fiji.snt.analysis.sholl.parsers.TabularParser

def table = ShollUtils.csvSample()  // built-in demo data
def parser = new TabularParser(table, "radii_um", "counts")
parser.parse()
def profile = parser.getProfile()
```

These calls are used in `GROOVY_WORKFLOW_SHOLL_FULL_PROFILE.groovy`.

---

## 4. Graph Theory Analysis

### 4.1 Build graph from tree

```groovy
import sc.fiji.snt.analysis.graph.DirectedWeightedGraph

// Edge weights = Euclidean distances between adjacent nodes
def graph = tree.getGraph()

// Simplified graph: retains only root, branch points, and terminals
def simplified = graph.getSimplifiedGraph()
```

### 4.2 Graph queries

```groovy
def root = graph.getRoot()    // singular node with in-degree 0
def tips = graph.getTips()    // set of nodes with out-degree 0

graph.vertexSet().size()
graph.edgeSet().size()
```

### 4.3 Graph diameter and shortest paths

```groovy
// Undirected graph diameter = longest shortest path between any two nodes.
def diameterPath = graph.getLongestPath(false)
diameterPath.getLength()  // physical distance
diameterPath.size()       // node count

// Directed longest path keeps root->tip direction.
def rootToTipPath = graph.getLongestPath(true)
rootToTipPath.getLength()
rootToTipPath.size()

// Arbitrary shortest path between two vertices
def path = graph.getShortestPath(vertex1, vertex2)
```

### 4.4 Branch point queries via graph

```groovy
// Get all branch points
def bps = graph.getBPs()

// Distance from each branch point to root (soma)
bps.each { bp ->
    double dist = bp.distanceTo(root)
}
```

### 4.5 JGraphT interoperability

```groovy
import org.jgrapht.alg.shortestpath.DijkstraShortestPath

// Use JGraphT algorithms directly on SNT graphs
def dsp = new DijkstraShortestPath(graph)
def jgPath = dsp.getPath(root, tipNode)
double pathWeight = jgPath.getWeight()
```

These calls are used in `GROOVY_WORKFLOW_GRAPH_ANALYSIS.groovy`.

---

## 5. Allen Brain Atlas Integration

### 5.1 Brain area annotations

```groovy
import sc.fiji.snt.annotation.AllenUtils

// Brain midline coordinate
def center = AllenUtils.brainCenter()
double midlineX = center.getX()

// Get a named compartment
def compartment = AllenUtils.getCompartment("Thalamus")
def mesh = compartment.getMesh()
```

### 5.2 Soma and node annotations (MouseLight data)

```groovy
// Soma annotation
def somaCpt = loader.getSomaCompartment()   // BrainAnnotation
somaCpt.name()              // full name
somaCpt.acronym()           // abbreviation
somaCpt.getOntologyDepth()  // depth in Allen ontology hierarchy

// Navigate ontology (negative delta = toward root)
def ancestor = somaCpt.getAncestor(targetDepth - currentDepth)

// Per-node annotation
def annotation = node.getAnnotation()
annotation.name()
annotation.acronym()
annotation.getMesh()
```

### 5.3 Annotated histograms (requires display)

```groovy
import sc.fiji.snt.analysis.NodeStatistics

def tips = tStats.getTips()
def nStats = new NodeStatistics(tips)

// Tip distribution across brain areas (at specified ontology depth)
def hist = nStats.getAnnotatedHistogram(maxOntologyDepth)
hist.annotateCategory(somaCpt.acronym(), "soma", "blue")
hist.show()

// Cable length distribution across brain areas
def cableHist = tStats.getAnnotatedLengthHistogram(maxOntologyDepth)
cableHist.show()

// Ipsi/contralateral ratio histograms
def ratioHist = tStats.getAnnotatedLengthHistogram(maxOntologyDepth, "ratio")
def freqHist = nStats.getAnnotatedFrequencyHistogram(maxOntologyDepth, "ratio", tree)
```

These calls are used in `GROOVY_WORKFLOW_MOUSELIGHT_BRAIN_AREA.groovy`.

---

## 6. Angular and Directional Analysis

### 6.1 Bifurcation angles

```groovy
// Remote bifurcation angles (angle between child branches)
def angles = new TreeStatistics(tree).getRemoteBifAngles()
// Returns List<Double> of angles in degrees
```

### 6.2 Root angle analysis (requires display for plots)

```groovy
import sc.fiji.snt.analysis.RootAngleAnalyzer

def analyzer = new RootAngleAnalyzer(tree)
analyzer.balancingFactor()
analyzer.centripetalBias()
analyzer.meanDirection()
analyzer.getCramerVonMisesStatistic()

// Visualization (GUI)
analyzer.getHistogram().show()
analyzer.getDensityPlot().show()
def taggedTree = analyzer.getTaggedTree("Ice.lut")
```

### 6.3 Principal component analysis

```groovy
import sc.fiji.snt.analysis.PCAnalyzer

def pca = new PCAnalyzer(tree)
def axes = pca.getPrincipalAxes()
pca.orientTowardTips()
```

### 6.4 Path-level direction and extension angles

```groovy
path.getTangent(nodeIndex)
path.getLocalDirection()
path.getAngleWithLocalDirection()
path.getExtensionAngleFromVertical()
path.getExtensionAngles3D()
```

---

## 7. Strahler Analysis

```groovy
import sc.fiji.snt.plugin.StrahlerCmd
#@ Context context

def sa = new StrahlerCmd(tree)
sa.setContext(context)
if (sa.validInput()) {
    sa.run()  // outputs displayed in SNT UI
}
```

Note: `StrahlerCmd` is a SciJava command that produces a UI table. For headless Strahler metrics, use `TreeStatistics.summarize()` which includes the Horton-Strahler root number. Full per-order Strahler tables require the command with a display context.

---

## 8. Group Comparison (GUI only)

```groovy
import sc.fiji.snt.plugin.GroupAnalyzerCmd
import sc.fiji.snt.analysis.GroupedTreeStatistics

#@ CommandService cmd
cmd.run(GroupAnalyzerCmd.class, true)
// Opens a dialog for comparing up to 6 groups of cells
// Produces: two-sample t-tests, one-way ANOVA, color-coded montages

// For programmatic access (requires display for charts):
def gStats = new GroupedTreeStatistics()
gStats.getFlowPlot()    // Sankey diagram of brain area projections
gStats.getBoxPlot()     // comparative box plots
```

---

## 9. Visualization APIs (require display context)

### 9.1 3D Reconstruction Viewer

```groovy
import sc.fiji.snt.viewer.Viewer3D

def viewer = new Viewer3D(true)  // interactive
viewer.add(tree)
viewer.loadRefBrain("mouse")
viewer.add(meshes)
viewer.setTreeThickness(labels, thickness, null)
viewer.annotatePoints(points)
viewer.annotateLine(p1, p2)
viewer.show()
```

### 9.2 2D Viewer

```groovy
import sc.fiji.snt.viewer.Viewer2D

def viewer2d = new Viewer2D(context)
viewer2d.addPolygon(polygon)
```

### 9.3 Color mapping

```groovy
import sc.fiji.snt.viewer.TreeColorMapper
import sc.fiji.snt.util.ColorMaps

def mapper = new TreeColorMapper(context)
mapper.map(tree, metric, lut)

def colorMap = ColorMaps.get("viridis")
```

### 9.4 Charts

```groovy
import sc.fiji.snt.analysis.SNTChart

// 3D histogram (two-variable scatter density)
SNTChart.showHistogram3D(xData, yData, colorMap, axisLabels)

// Standard histogram
def chart = SNTChart.getHistogram(data)
chart.show()

// Sholl plot
def plot = new ShollPlot(lStats)
plot.show()
plot.rebuild()  // update after refitting
```

---

## 10. Specialized Analysis (require specific data/display)

### 10.1 Peripath detection (requires image)

```groovy
import sc.fiji.snt.analysis.PeripathDetector

def detector = new PeripathDetector(path, image)
path.fitRadii()
detector.detect()
detector.createTorusMask()
```

### 10.2 Convex hull

```groovy
import sc.fiji.snt.analysis.ConvexHull2D
import sc.fiji.snt.analysis.ConvexHull3D

def hull = new ConvexHull2D(points)
def centroid = ops.geom().centroid(hull)
```

### 10.3 Volumetric rendering (requires image context)

```groovy
// Path tangent vectors and disk rendering
path.getTangent(index)
path.getXUnscaled(index)
// DiskCursor3D for ImgLib2-based volumetric writing
```

---

## 11. Batch Reconstruction Analysis

```groovy
import sc.fiji.snt.Tree
import sc.fiji.snt.analysis.TreeStatistics
import sc.fiji.snt.analysis.ShollAnalyzer

def trees = Tree.listFromDir("/path/to/reconstructions", "optional filter")

trees.each { tree ->
    def stats = new TreeStatistics(tree)
    stats.summarize(false)

    def sholl = new ShollAnalyzer(tree, stats)
    Map metrics = sholl.getSingleValueMetrics()
}
```

Official script templates include a GUI batch measurement path
(`Measure_Multiple_Files_(With_Options).groovy`) and a GUI batch Sholl command
(`Sholl_Bulk_Analysis_(From_Reconstructions).groovy`). For deterministic file
outputs, this skill uses the same analysis classes directly and writes one row
per reconstruction.

These calls are used in `GROOVY_WORKFLOW_BATCH_SWC_ANALYSIS.groovy`.

---

## Checked-in Workflow Roles

| Workflow file | Role |
|---------------|------|
| `GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy` | Smoke-test SNT and generate a fresh SWC file |
| `GROOVY_WORKFLOW_TREE_STATISTICS_FROM_SWC.groovy` | Morphometry-only CSV export |
| `GROOVY_WORKFLOW_SHOLL_METRICS_FROM_SWC.groovy` | Sholl summary metrics CSV export |
| `GROOVY_WORKFLOW_SWC_ANALYSIS.groovy` | Combined morphometry + Sholl export |
| `GROOVY_WORKFLOW_BATCH_SWC_ANALYSIS.groovy` | Directory-scale morphometry + Sholl summary export |
| `GROOVY_WORKFLOW_SUBTREE_METRICS.groovy` | Compartment extraction + volume + bounding box |
| `GROOVY_WORKFLOW_GRAPH_ANALYSIS.groovy` | Graph theory metrics (vertices, edges, diameter) |
| `GROOVY_WORKFLOW_SHOLL_FULL_PROFILE.groovy` | Full Sholl profile with polynomial fitting |
| `GROOVY_WORKFLOW_NEUROMORPHO_LOAD.groovy` | Download reconstruction from NeuroMorpho.org |
| `GROOVY_WORKFLOW_MOUSELIGHT_BRAIN_AREA.groovy` | MouseLight download + brain area projection analysis |

## Automation Boundary

**Headless-safe (file in → file out):**
- All checked-in Groovy workflows above
- Batch directory analysis of SWC reconstructions
- Tree I/O, TreeStatistics, ShollAnalyzer, TreeParser, LinearProfileStats
- DirectedWeightedGraph construction and queries
- Online database loaders (MouseLightLoader, NeuroMorphoLoader)
- Brain area annotation traversal (AllenUtils, node.getAnnotation())

**Requires display context (documented but not in headless workflows):**
- `.show()` calls on histograms, charts, and plots
- Viewer3D / Viewer2D interactive rendering
- StrahlerCmd and GroupAnalyzerCmd (SciJava commands with UI output)
- PeripathDetector (requires image and ROI context)
- SNTChart.showHistogram3D() and ShollPlot

## Official-doc Scripting Entry Points

- `Scripts > New...` from the main SNT dialog opens Fiji's Script Editor.
- `Scripts > Reload...` refreshes the Fiji scripts menu.
- `Scripting > Record Script...` from Reconstruction Viewer opens the script recorder.

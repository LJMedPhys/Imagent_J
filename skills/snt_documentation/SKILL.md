---
name: snt_documentation
description: SNT is Fiji's framework for semi-automated neurite tracing, SWC reconstruction I/O, neuronal morphometry, Sholl analysis, graph theory analysis, brain atlas integration, online database access, and batch reconstruction analysis. Use this skill for manual tracing in the SNT GUI, importing or exporting SWC/TRACES files, scripting morphometry and Sholl analysis, graph-theoretic measurements, compartment-specific analysis, batch analysis of SWC directories, downloading reconstructions from NeuroMorpho.org or MouseLight, and analyzing brain area projections in the Allen CCF.
---

# SNT - Documentation Index

SNT combines interactive tracing, reconstruction import and export, morphometric analysis, Sholl analysis, graph theory, brain atlas integration, online database access, and batch reconstruction processing. The validated automation path in this repo uses the SNT Java API directly (`Tree`, `TreeStatistics`, `ShollAnalyzer`, `TreeParser`, `LinearProfileStats`, `DirectedWeightedGraph`, `MouseLightLoader`, `NeuroMorphoLoader`, `AllenUtils`, `SNTTable`) rather than dialog-driving macros.

## Files

| File | What it covers |
|------|----------------|
| **API Reference** | |
| `SCRIPT_API.md` | Comprehensive API reference: Tree I/O, morphometry, Sholl (basic + full profile + fitting), graph theory, brain atlas, angular analysis, visualization, and automation boundary |
| **Core Analysis Workflows** | |
| `GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy` | Create SNT's built-in demo tree and save as SWC |
| `GROOVY_WORKFLOW_TREE_STATISTICS_FROM_SWC.groovy` | Load SWC → morphometry table → CSV |
| `GROOVY_WORKFLOW_SHOLL_METRICS_FROM_SWC.groovy` | Load SWC → Sholl summary metrics → CSV |
| `GROOVY_WORKFLOW_SWC_ANALYSIS.groovy` | Combined morphometry + Sholl summary export |
| `GROOVY_WORKFLOW_BATCH_SWC_ANALYSIS.groovy` | Directory of SWC files → one morphometry CSV + one Sholl summary CSV |
| **Extended Analysis Workflows** | |
| `GROOVY_WORKFLOW_SUBTREE_METRICS.groovy` | Compartment extraction (axon/dendrite) + volume + bounding box + morphometry |
| `GROOVY_WORKFLOW_GRAPH_ANALYSIS.groovy` | Graph theory metrics: vertices, edges, tips, graph diameter (longest shortest path) |
| `GROOVY_WORKFLOW_SHOLL_FULL_PROFILE.groovy` | Full Sholl profile via TreeParser + polynomial fitting + extensive statistics (LinearProfileStats + NormalizedProfileStats) |
| `GROOVY_WORKFLOW_IMAGE_SHOLL_ANALYSIS.groovy` | Load segmented 2D/3D image → image-derived Sholl profile CSV + summary metrics CSV |
| **Online Database Workflows** | |
| `GROOVY_WORKFLOW_NEUROMORPHO_LOAD.groovy` | Download reconstruction from NeuroMorpho.org and save as SWC |
| `GROOVY_WORKFLOW_MOUSELIGHT_BRAIN_AREA.groovy` | Download MouseLight neuron + morphometry + brain area projection analysis (Allen CCF) |
| **GUI References** | |
| `UI_GUIDE.md` | Launch paths, dialogs, tracing controls, analysis and scripting entry points |
| `UI_WORKFLOW_SEMI_AUTOMATED_TRACING.md` | Step-by-step GUI walkthrough for tracing and exporting reconstructions |

## Functional Coverage

| Domain | Headless workflow | API documented |
|--------|:-----------------:|:--------------:|
| Load/save SWC | ✓ | ✓ |
| Demo tree generation | ✓ | ✓ |
| Basic morphometry (TreeStatistics) | ✓ | ✓ |
| Batch directory morphometry + Sholl summary | ✓ | ✓ |
| Compartment extraction (subTree) | ✓ | ✓ |
| Volume and bounding box | ✓ | ✓ |
| Sholl summary metrics | ✓ | ✓ |
| Full Sholl profile + polynomial fitting | ✓ | ✓ |
| Normalized Sholl decay | ✓ | ✓ |
| Graph theory (diameter, shortest paths) | ✓ | ✓ |
| NeuroMorpho.org download | ✓ | ✓ |
| MouseLight download | ✓ | ✓ |
| Brain area projection analysis (Allen CCF) | ✓ | ✓ |
| Bifurcation angle extraction | — | ✓ |
| Root angle analysis (von Mises) | — | ✓ |
| PCA / directional analysis | — | ✓ |
| Image-based Sholl (ImageParser) | ✓ | ✓ |
| Strahler analysis (StrahlerCmd) | — | ✓ |
| Group comparison (t-test, ANOVA) | — | ✓ |
| 3D visualization (Viewer3D) | — | ✓ |
| Color mapping / chart export | — | ✓ |
| Peripath / synapse detection | — | ✓ |

## Automation Boundary

- **Headless-safe**: all checked-in Groovy workflows produce CSV/SWC output without requiring a display.
- **GUI workflows**: interactive tracing, path editing, Sholl dialogs, 3D viewers, chart `.show()` calls, StrahlerCmd, and GroupAnalyzerCmd require a display context.
- This skill does not claim an end-to-end `IJ.run()` macro string for driving SNT tracing dialogs.

## Workflow Bootstrap

- Analysis workflows require an explicit `inputSwcFile`.
- Use your own SWC reconstruction, or first run `GROOVY_WORKFLOW_EXPORT_DEMO_TREE_AS_SWC.groovy`.
- The export workflow writes a demo reconstruction to `/data/snt_validation/demo_tree_from_service.swc` by default.

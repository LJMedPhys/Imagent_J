// Create SNT's built-in demo reconstruction and export it as SWC.
#@ String (label = "Output SWC reconstruction", value = "/data/snt_validation/demo_tree_from_service.swc") outputSwcPath
#@ SNTService snt

/*
 * SNT - Export the built-in demo tree as SWC
 *
 * PURPOSE:
 *   1. Create SNT's built-in demo tree from SNTService
 *   2. Save it as an SWC reconstruction
 *
 * REQUIRED INPUTS:
 *   outputSwcPath - new SWC path that will be written
 *
 * IMPORTANT:
 *   - Choose a fresh output path instead of overwriting an existing file.
 *   - This workflow does not require an input image or reconstruction file.
 */

void requireFreshSwc(String path) {
    if (path == null || path.trim().isEmpty()) {
        throw new IllegalArgumentException("Output SWC path must be provided")
    }
    File file = new File(path)
    file.parentFile?.mkdirs()
    if (file.exists()) {
        throw new IllegalArgumentException("Output SWC already exists: " + file.absolutePath)
    }
    if (!file.name.toLowerCase().endsWith(".swc")) {
        throw new IllegalArgumentException("Output file must use the .swc extension: " + file.absolutePath)
    }
    return
}

requireFreshSwc(outputSwcPath)
File outputSwcFile = new File(outputSwcPath)

println("SNT demo tree export")
println("Output SWC : " + outputSwcFile.absolutePath)

def tree = snt.demoTree()
int nodeCount = tree.getNodesAsSWCPoints().size()
if (nodeCount <= 0) {
    throw new IllegalStateException("SNT demoTree() returned no nodes")
}

boolean saved = tree.saveAsSWC(outputSwcFile.absolutePath)
if (!saved || !outputSwcFile.exists() || outputSwcFile.length() == 0) {
    throw new IllegalStateException("Could not export demo tree as SWC: " + outputSwcFile.absolutePath)
}

println("Loaded SWC nodes : " + nodeCount)
println("SNT demo tree export complete")

// These #@ lines inject Fiji parameters; they must stay at the top of the file.
#@ String (label = "Ilastik executable path (empty = ILASTIK_EXECUTABLE)", value = "") executablePath
#@ File (label = "Project file (.ilp) — created if it does not exist", value = "/app/data/projects/my_project/ilastik/pixel_classifier.ilp") projectFile
#@ String (label = "Workflow for a NEW project", choices = {"Pixel Classification", "Autocontext (2-stage)", "Object Classification (from prediction image)", "Object Classification (from binary image)", "Object Classification (from label image)", "Edge Training With Multicut", "Automatic Tracking Workflow (Conservation Tracking) from prediction image", "Automatic Tracking Workflow (Conservation Tracking) from binary image", "Cell Density Counting", "Carving"}, value = "Pixel Classification") workflow

import ij.IJ
import java.util.concurrent.TimeUnit

/*
 * ilastik — open the ilastik GUI on the desktop so the USER can train a project
 *
 * Training (painting labels, choosing features, checking live predictions) only exists in the
 * ilastik GUI; neither ilastik4ij nor ilastik's headless mode can train. This script starts the
 * bundled ilastik on the same desktop as Fiji (noVNC) and returns immediately.
 *
 *   - projectFile does not exist -> a NEW project of `workflow` is created and opened
 *     (`--new_project`; `workflow` is ilastik's internal workflow name).
 *   - projectFile exists         -> that project is opened (`--project`) and `workflow` is ignored.
 *
 * Images cannot be pre-loaded from the command line in GUI mode (`--raw_data` is ignored there):
 * tell the user to add them under "1. Input Data > Raw Data > Add New...".
 *
 * What to tell the user (Pixel Classification):
 *   1. Input Data: Add New... -> Add separate image(s) -> pick 1-3 representative images.
 *   2. Feature Selection: Select Features... -> tick all sigmas up to ~the object radius.
 *   3. Training: paint a few strokes per class (e.g. Label 1 = objects, Label 2 = background),
 *      toggle Live Update, add strokes where the prediction is wrong.
 *   4. Project > Save Project, then CLOSE ilastik before Fiji/the agent applies the project.
 * Then apply it with GROOVY_WORKFLOW_HEADLESS_BATCH.groovy (folders) or
 * GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy (one image).
 *
 * Prints ILASTIK_GUI_STARTED <pid> or throws if ilastik exits during start-up (log: <project>.gui.log).
 */

String exe = executablePath?.trim() ?: (System.getenv("ILASTIK_EXECUTABLE") ?: "")
if (!exe || !new File(exe).canExecute()) {
    throw new IllegalArgumentException("ilastik executable not found: '" + exe + "' (set executablePath or ILASTIK_EXECUTABLE)")
}
projectFile.parentFile?.mkdirs()
boolean isNew = !projectFile.exists()
List<String> cmd = [exe]
if (isNew) {
    cmd << "--new_project=" + projectFile.absolutePath
    cmd << "--workflow=" + workflow
} else {
    cmd << "--project=" + projectFile.absolutePath
}

def pb = new ProcessBuilder(cmd)
def env = pb.environment()
env.put("DISPLAY", System.getenv("DISPLAY") ?: ":1")
env.put("QT_QPA_PLATFORM", "xcb")
// OpenCV-based packages in the app env export a Qt plugin path that breaks ilastik's own Qt.
env.remove("QT_QPA_PLATFORM_PLUGIN_PATH")
env.remove("PYTHONPATH"); env.remove("PYTHONHOME")
File logFile = new File(projectFile.absolutePath + ".gui.log")
pb.redirectErrorStream(true).redirectOutput(logFile)
def proc = pb.start()

// ilastik needs ~20-60 s to show its window; only fail fast if it dies during start-up.
if (proc.waitFor(20, TimeUnit.SECONDS)) {
    throw new RuntimeException("ilastik exited during start-up (code " + proc.exitValue() + "):\n" +
            logFile.readLines().takeRight(15).join("\n"))
}
IJ.log("[ilastik] GUI starting (" + (isNew ? "new " + workflow + " project" : "existing project") + "): " + projectFile)
IJ.log("[ilastik] When the user has saved the project, they must CLOSE ilastik before it is applied headless.")
println("ILASTIK_GUI_STARTED " + proc.pid())

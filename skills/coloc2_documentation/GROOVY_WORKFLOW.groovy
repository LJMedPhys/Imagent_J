import ij.IJ
import ij.WindowManager

// 1. Setup Environment
def imp = IJ.getImage() // Assumes a composite or multi-channel image is active
IJ.run(imp, "Split Channels", "")

// 2. Assign Handles (Verify names in WindowManager)
def c1 = WindowManager.getImage("C1-" + imp.getTitle())
def c2 = WindowManager.getImage("C2-" + imp.getTitle())

// 3. Build Argument String
// We use Costes regression for thresholds and 100 iterations for significance
def args = [
    "channel_1=[${c1.getTitle()}]",
    "channel_2=[${c2.getTitle()}]",
    "roi_or_mask=None",
    "threshold_regression=Costes",
    "display_images=false",
    "display_results=true",
    "statistic_1=true",
    "statistic_2=true",
    "statistic_3=true",
    "number_of_iterations=100",
    "psf_width=3.0"
].join(" ")

// 4. Run Analysis
IJ.run("Coloc 2", args)

// 5. Cleanup (Optional)
// Results are sent to the "Log" window and "Coloc 2 Results" table
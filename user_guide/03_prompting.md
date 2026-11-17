# Writing Good Requests

The assistant works best when it knows enough to make decisions without asking you about every step. This page shows what helps and what to avoid.

---

## What to tell it at the start

The more you say up front, the fewer questions it needs to ask.

| What | Example |
|------|---------|
| **Goal** | "Segment nuclei and measure the area and mean brightness of each one" |
| **About the images** | "16-bit TIFFs, 3 fluorescence channels, channel 1 = DAPI, about 50 images" |
| **Where they are** | "The images are in `/data/experiment_01/`" or "the image open in Fiji" |
| **What you want back** | "A table with one row per nucleus, and a mask image for each image" |
| **How you want to work** | "Show me how to do it in the Fiji menus" or "write a script that does it" |
| **Tool (optional)** | "Use StarDist if possible" or "use napari" |
| **Comparison (optional)** | "Compare treated and control; the condition is in the file name" |

---

## Examples

**Too short (it will ask follow-up questions):**
> "Segment my cells."

**Better:**
> "Segment the DAPI-stained nuclei in the 16-bit TIFFs in `/data/batch_01/`. Use StarDist. Save a table (area, mean brightness) and a mask for each image."

**Many images at once:**
> "Run the same nuclei segmentation on all `.tif` files in `/data/`. Save one table per image, named `<image name>_results.csv`, in `/data/results/`."

**Improving a result:**
> "Touching nuclei are being merged into one. Can you separate them?"

**Teaching a model on your corrections:**
> "The segmentation keeps missing my organoids. Can I correct a few examples so the model learns what I mean?"

**Sorting objects into groups:**
> "The cells are segmented. Now sort them into infected and uninfected; I'll mark a few examples of each."

**Asking about an open window:**
> "I have the TrackMate window open. What should I set for 'Estimated object diameter' if my nuclei are about 10 µm and the pixel size is 0.2 µm?"

**Learning:**
> "Teach me how thresholding works, with an example."

---

## Tips

- **Name the plugin** if you have a preference. It saves time.
- **Give the pixel size** when real-world sizes matter (for example "0.325 µm per pixel, 1 µm between slices"), especially if the image file doesn't contain it.
- **Say which channel** to use in images with several channels ("find the objects in channel 2").
- **Ask for the script** if you want to run it again later: "Save the final working script so I can reuse it."
- **Go step by step** for complicated analyses. Get the segmentation right first, then the measurements, then run all images.
- **Look at the results yourself.** Open the overlays and figures it saves. AI can produce results that look convincing but are wrong.
- **Correct it while it works.** You can send a message while the assistant is busy (for example "use channel 2, not channel 1"), and it will read it at its next step.
- **If it fails,** ask it to try again. Sometimes it just gets confused; other times the problem needs a different approach.

---

## What to avoid

- Vague goals without details about the images ("analyse my data").
- Assuming it knows which image is open in Fiji. Give the file location.
- Asking it to install many plugins at once. Plugins can clash; install one at a time.
- Sensitive or confidential details in the chat. Everything you type is sent to the AI provider (see [Security and privacy](05_security.md)).

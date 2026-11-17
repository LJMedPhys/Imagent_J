# napari, Segmentation and Fine-Tuning

Besides Fiji, Agentic-J can use **napari**, an image viewer for Python, in the same chat. Through napari it also offers **micro-sam**, a segmentation tool based on Meta's "Segment Anything" model adapted for microscopy. With these, the assistant can:

- show images, masks and results in napari, layer by layer;
- segment objects that standard tools (StarDist, Cellpose) don't handle well;
- **learn from your corrections**: you fix a few small squares of your images, and it trains (fine-tunes) the model on them;
- **sort objects into groups** (for example infected / uninfected) after you mark a few examples.

You don't need to know how napari works. Just ask, for example "open this image in napari" or "show me the mask on top of the image".

---

## Teaching a model with your corrections (fine-tuning)

Use this when a segmentation keeps making the same mistakes on your images, for example missing cells, merging two cells into one, or outlining debris. You correct a few small squares, and the model learns from them. This works for **micro-sam** and **Cellpose**.

**What you need:**
- About **20–30 minutes** of your time to correct the squares.
- A **graphics card (GPU)** is strongly recommended. Training takes 10–20 minutes with a GPU, but hours on a CPU. The assistant tells you how long it will take before you start. See [Using a graphics card](01_getting_started.md#5-using-a-graphics-card-optional).

**Is it worth it?** The assistant first tries the model as it is and shows you the result. Standard images (for example ordinary fluorescent nuclei or common cell lines) are often already segmented well, and then fine-tuning won't help. It pays off most for unusual samples. If you want to sort objects into categories rather than fix their outlines, use [sorting objects into groups](#sorting-objects-into-groups) instead.

### Step 1: pick the squares (you, about 2–3 minutes)

A napari window opens, showing one image from each group in your experiment (for example each well or each condition), with the model's current segmentation drawn on top.

- **Click where the model gets it wrong:** missed cells, two cells merged into one, debris outlined as a cell. Also click one or two places where it is right.
- A yellow square shows the area you'll correct. The window moves to the next group by itself.
- Useful buttons: **Show me another field** (if an image is empty or blurry), **Stay on this field** (to take several squares from one image), **Back**, **Undo last square**.
- Press the green **DONE** button when you're finished.

Pick squares from every condition you want to compare (for example both treated and control), so the model doesn't learn from only one of them.

The assistant then cuts out the squares and pre-segments them, so you start from the model's guess rather than from scratch.

### Step 2: correct the squares (you, about 2–4 minutes per square)

A napari window opens with the first square and an **Annotation Helper** panel on the right.

**The rule:** inside the square, every object must be outlined, and nothing else. Leave outlines that are already right alone. You don't need to touch anything outside the square.

| Button | What it does |
|---|---|
| **➕ ADD objects** | Click the middle of a missed object, then press **S**, then **C**. |
| **✏ DRAW round objects** | Click round an object and double-click to close; then **S** and **C**. Use it when clicking keeps getting an object wrong. A rough outline is fine. |
| **☐ My drawn shape IS the outline** | Tick this if the computer keeps getting an object wrong. What you draw is then saved exactly as the outline, so trace the edge carefully. |
| **✖ DELETE objects** | Click on an outline that shouldn't be there. |
| **⌫ CLEAR my clicks & boxes** | Removes your clicks and shapes; outlines stay. |

To fix a bad outline, **delete it and add it again.**

When a square looks right, press **N** (or **TILE DONE**). **Press N on the last square too: N is what saves your work.** Press **B** to go back to the previous square. You can stop at any time; finished squares are kept, and next time you continue where you left off.

While you work, you can ask the assistant questions in the chat, such as "is a rough outline good enough?" or "can I skip this square?".

### Step 3: training and checking (the assistant, 10–20 minutes on a GPU)

The assistant trains the model on most of your squares and keeps about a quarter aside for testing. It then segments the test squares with both the **original** and the **new** model, and reports both scores. You can keep chatting while it trains.

- If the new model is clearly better, it is used from now on.
- If it isn't better, the assistant says so, and keeps the original model. Nothing breaks.
- A small improvement measured on only a few squares is uncertain. Before a large batch, correcting a few more squares makes the result more reliable.

### Step 4: using the model (the assistant)

The chosen model segments all your images. You get a mask for each image, a table of counts and overlay pictures to check. The masks can then be measured like any other segmentation.

Everything is saved in the project folder: your squares and corrections, the trained model, the scores, and the scripts for each step.

---

## Sorting objects into groups

If your objects are already segmented and you want to sort them into categories (for example live / dead, infected / uninfected), you don't need fine-tuning. Instead:

1. A napari window opens on the first image. You mark a few examples of each group.
2. Click **Train and predict**. A small classifier learns from your examples in seconds.
3. Press **N** to move through the remaining images, which are sorted automatically. Check them and correct mistakes if needed.

The classifier is saved in the project folder, so it can be reused on new images.

---

## Correcting objects by hand in Fiji

If some objects can't be separated automatically, the assistant may ask you to draw them yourself as selections (ROIs) in Fiji, and then uses your outlines in the analysis.

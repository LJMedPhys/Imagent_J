# napari, Segmentation and Fine-Tuning

Besides Fiji, Agentic-J can use **napari**, an image viewer for Python, in the same chat. With it, the assistant can:

- show images, masks and results in napari, layer by layer;
- **learn from your corrections**: you fix a few small squares of your images by drawing the right outlines, and it trains (fine-tunes) **Cellpose** on them.

You don't need to know how napari works. Just ask, for example "open this image in napari" or "show me the mask on top of the image".

---

## Teaching a model with your corrections (fine-tuning)

Use this when a segmentation keeps making the same mistakes on your images, for example missing cells, merging two cells into one, or outlining debris. You correct a few small squares, and **Cellpose** learns from them.

**What you need:**
- About **20–30 minutes** of your time to correct the squares.
- A **graphics card (GPU)** is strongly recommended. Training takes minutes with a GPU, and much longer on a CPU. The assistant tells you how long it will take before you start. See [Using a graphics card](01_getting_started.md#5-using-a-graphics-card-optional).

**Is it worth it?** The assistant first tries the model as it is and shows you the result. Standard images (for example ordinary fluorescent nuclei or common cell lines) are often already segmented well, and then fine-tuning won't help. It pays off most for unusual samples. If you want to sort objects into categories rather than fix their outlines, see [sorting objects into groups](#sorting-objects-into-groups) instead.

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

You add objects by **drawing** them: what you trace is exactly the outline that is saved.

| Button | What it does |
|---|---|
| **✏ DRAW objects** | Press, drag round a missed object and release. Draw as many as you like, then press **S** to see them as outlines and **C** to keep them. Follow the edge; roughly is fine. Press **DRAW** again to click a polygon point by point instead. |
| **✖ DELETE objects** | Click on an outline that shouldn't be there (or hover over it and press **D**). |
| **⌫ CLEAR my drawings** | Removes shapes you drew but haven't kept yet; kept outlines stay. |

To fix a bad outline, **delete it and draw it again.** A new outline never paints over an existing one.

When a square looks right, press **N** (or **TILE DONE**). **Press N on the last square too: N is what saves your work.** On a square with nothing in it, press **N** twice to save it as empty. Press **B** to go back to the previous square. You can stop at any time; finished squares are kept, and next time you continue where you left off.

While you work, you can ask the assistant questions in the chat, such as "is a rough outline good enough?" or "can I skip this square?".

### Step 3: training and checking (the assistant, a few minutes on a GPU)

The assistant trains the model on most of your squares and keeps about a quarter aside for testing. It then segments the test squares with both the **original** and the **new** model, and reports both scores. You can keep chatting while it trains.

- If the new model is clearly better, it is used from now on.
- If it isn't better, the assistant says so, and keeps the original model. Nothing breaks.
- A small improvement measured on only a few squares is uncertain. Before a large batch, correcting a few more squares makes the result more reliable.

### Step 4: using the model (the assistant)

The chosen model segments all your images. You get a mask for each image, a table of counts and overlay pictures to check. The masks can then be measured like any other segmentation.

Everything is saved in the project folder: your squares and corrections, the trained model, the scores, and the scripts for each step.

---

## Sorting objects into groups

If your objects are already segmented and you want to sort them into categories (for example live / dead, infected / uninfected), you don't need fine-tuning. Ask the assistant to measure the objects (size, shape, intensities) and classify them: it uses the measurements, and a few examples you label if needed, to sort every object, and shows you the result to check.

(The earlier interactive "click examples in napari" classifier was part of micro-sam, which is no longer included.)

---

## Correcting objects by hand in Fiji

If some objects can't be separated automatically, the assistant may ask you to draw them yourself as selections (ROIs) in Fiji, and then uses your outlines in the analysis.

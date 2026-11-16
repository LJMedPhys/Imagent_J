# ilastik — let the user train a project in the ilastik GUI

ilastik learns from a few brush strokes the user paints; that only happens in the ilastik GUI.
The agent's part: open ilastik on the desktop (same noVNC screen as Fiji), explain what to do,
wait until the user has **saved and closed** the project, then apply it headless.

## 1. Open ilastik

Run `GROOVY_LAUNCH_ILASTIK_GUI.groovy` with every parameter set explicitly:

| Parameter | Value |
|---|---|
| `executablePath` | `""` (uses `$ILASTIK_EXECUTABLE`) |
| `projectFile` | e.g. `/app/data/projects/<project>/ilastik/pixel_classifier.ilp` — created if missing |
| `workflow` | internal workflow name for a new project, e.g. `Pixel Classification`, `Object Classification (from label image)`, `Autocontext (2-stage)`, `Edge Training With Multicut`, `Automatic Tracking Workflow (Conservation Tracking) from prediction image` |

It prints `ILASTIK_GUI_STARTED <pid>`; the window appears after ~20–60 s. Verified 2026-11-16: new
Pixel Classification and "Object Classification [Inputs: Raw Data, Label Image]" projects open on
display :1. Images cannot be pre-loaded in GUI mode (`--raw_data` is ignored), so the user adds them.

Launching by hand (what the script does): `DISPLAY=:1 QT_QPA_PLATFORM=xcb` and **unset
`QT_QPA_PLATFORM_PLUGIN_PATH`** (set by OpenCV in the app environment; it breaks ilastik's Qt), then
`$ILASTIK_EXECUTABLE --new_project=<file.ilp> --workflow="Pixel Classification"` or
`$ILASTIK_EXECUTABLE --project=<file.ilp>`.

## 2. What to tell the user (Pixel Classification)

1. **1. Input Data → Raw Data → Add New… → Add separate image(s)**: 1–3 representative images
   (same channels and dimensionality as the data to process later).
2. **2. Feature Selection → Select Features…**: tick the features at all scales up to about the
   object radius (or "Select all").
3. **3. Training**: one label per class (e.g. Label 1 = objects, Label 2 = background); paint a few
   strokes per class, switch on **Live Update**, add strokes where the prediction is wrong,
   especially at object borders. Fewer, well-placed strokes beat large painted areas.
4. **Project → Save Project**, then **close ilastik** (File/Project → Quit).
5. Optional for object classification / tracking with a feature table: **4. Object Information
   Export → Configure Feature Table Export**, then save — otherwise `--table_filename` fails.

For object classification from a label image (e.g. Cellpose masks): Raw Data tab = intensity image,
Label Image tab = the instance label image; then Object Feature Selection, click objects to assign
classes in Object Classification, save, close.

## 3. Apply the trained project

- Folder → `GROOVY_WORKFLOW_HEADLESS_BATCH.groovy` (set `inputAxes` for TIFFs, e.g. `yx`).
- One image as a Fiji image → `GROOVY_WORKFLOW_PIXEL_CLASSIFICATION.groovy`.
- Check the result on an overlay of 1–2 images before running everything; if it is wrong, reopen the
  same project with the launcher (it opens the existing file) and ask the user for corrective strokes.

Never write to the `.ilp` while the GUI has it open, and never apply it headless before the user
closed ilastik — ask, do not guess.

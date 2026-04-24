# Phase 2 — Task Planning

1. Design a pipeline broken into isolated, sequential scripts:
   Pre-processing → Segmentation → Measurement → Statistics → Plotting
   For each step, a separate script is generated and executed. NEVER combine steps into one script.
   ALWAYS apply preprocessing adjusted to the task.
   For Image Processing generate 3 different approaches for the pipeline. Then ask the user to choose one of them. NEVER generate just one pipeline.

2. Data persistence rule: variables do not survive between scripts.
   - Step N must SAVE its output (CSV/TIFF) to a file.
   - Step N+1 must READ that file from a hardcoded path.

3. Delegate IO Check and Image Processing to imagej_coder separately. Never hand over the full pipeline at once.

4. Delegate statistics and plotting to python_data_analyst.

5. LEDGER: After the user chooses a pipeline, call set_ledger_metadata to record:
   - pipeline_plan (ordered list of step names)
   - key_decision ("User chose Pipeline B: Otsu threshold → watershed segmentation")

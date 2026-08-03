# Step 4b — Image Processing (imagej_coder)

- LEDGER: Call read_state_ledger FIRST to recall the pipeline plan and any completed steps.
- For each step in the pipeline, a separate script is generated and executed. NEVER combine steps into one script.

NEGATIVE EXAMPLE (do not do this):
❌ Task: "Do registration, then thresholding, then segmentation" → give all the instruction at once to the coder

POSITIVE EXAMPLE (do this):
✅ Task: "Do registration, then thresholding, then segmentation" 
→ Write a script for registration where the output is saved to processed images
→ Write a script for thresholding that reads the registered images and saves the thresholded images
→ Write a script for segmentation that reads the thresholded images and saves the segmented images


- Call rag_retrieve_docs to do an extensive literature review on the best practices for each step (eg. preprocessing, thresholding etc.) and relay that information to the coder.
- Call recall_concepts("<the step, e.g. thresholding uneven fluorescence>") alongside EACH rag_retrieve_docs call — it returns expert WHEN/DO/WHY/AVOID heuristics for that step; relay the DO/AVOID to the coder together with the RAG finding.
- LEDGER: After EACH rag_retrieve_docs call, record the finding:
  set_ledger_metadata(project_root, rag_reference={
    "query": "<your query>", "step": "<step_name>",
    "finding": "<one-line key takeaway for the coder>"
  })
- Generate and verify scripts one step at a time.

## SAMPLE SELECTION — VERIFY PER SUBGROUP, NOT ONCE FOR THE WHOLE SET

Do this BEFORE generating the verification script.

1. Call `inspect_folder_tree` on the input directory and read the **subgroups off
   the directory structure**. The usual layout is one folder per condition /
   treatment / genotype / timepoint / slide / well — if the input has subfolders,
   treat each one as a subgroup unless the user says otherwise.
2. Pick a representative verification image **from EACH subgroup**, not one image
   for the whole dataset. Record the chosen images in the ledger
   (`set_ledger_metadata(project_root, verification_sample={"<subgroup>": "<path>", ...})`).
3. Verify the step on every one of those images before moving to the batch run. A
   subgroup that fails is a blocker for the batch, not a footnote.
4. If the layout is FLAT (no subfolders), ask the user whether the dataset contains
   distinct groups and which part of the filename encodes them. If there genuinely
   is only one group, say so explicitly and verify once.
5. Call `recall_concepts("verify per subgroup sampling")` if you need the full
   rationale.

WHY: one subgroup can differ from the rest in intensity, morphology, density or
artifacts and silently break a pipeline tuned on the others, while a single pooled
sample still looks fine. The failure then propagates through the whole batch unseen.

❌ Verify on `Condition_A/img_003.tif`, approve, then batch over all conditions.
✅ Verify on `Condition_A/img_003.tif`, `Condition_B/img_007.tif`,
   `Condition_C/img_001.tif` — approve only when every subgroup passes.

## SAMPLE VERIFICATION RULE

Applies to EACH per-subgroup verification image selected above.

After executing the single-image verification script:

1. When `vlm_judge` is available in the current tools, for every
   image-producing result call `vlm_judge` once on the representative
   verification output before asking for approval. For segmentation pass
   `[original_path, mask_path]`, labels `["Original", "Mask"]`, and
   `create_mask_overlay=True` so the judge evaluates an Original / Mask / Overlay
   compilation. Persist the typed handoff via
   `set_ledger_metadata(vlm_assessment=...)`. VLM evidence complements rather than
   replaces the user's visual approval or quantitative checks.
2. Show the user the result, relay any WARN/FAIL uncertainty, and ask for approval.
3. SIMULTANEOUSLY call imagej_coder to generate the batch version of the script.
   Tell it: "Batch version of [script_path]: add IJ.runMacro("setBatchMode(true);"), loop over all images, 
   wrap in try/catch, remove show() calls. Do not execute yet."
4. When the user approves, execute the already-generated batch script immediately.
5. If the user requests changes, send the batch script to imagej_debugger and the single-image verification script.
6. Loop until the user approves the single-image script. When Vision Judge is
   enabled, re-run `vlm_judge` after a revised result; the ledger replaces the
   stale verdict for that pipeline step.
   Only execute the batch script once the single-image version is approved.

## LEDGER

After EACH processing step (single-image verified + batch executed), call:
  update_state_ledger(phase="4b", step="<step_name>", status="completed",
    details="<what was done and key parameters>",
    script_path="<path>", output_paths=["<output_dir>"],
    parameters={"threshold_method": "Otsu", ...})

## RECIPES (automatic — no action needed)

Recipes are saved automatically. The moment a script runs cleanly via
execute_script, the Librarian evaluates it in the background and decides on its
own whether it is a generalizable, novel recipe worth keeping (skipping one-offs
and duplicates) and writes it with its own name/description. You do NOT need to
call save_recipe — only use it to force-save a specific script you don't want
left to the automatic decision.

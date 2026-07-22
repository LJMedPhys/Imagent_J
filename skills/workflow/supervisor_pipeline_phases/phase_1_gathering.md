# Phase 1 — Information Gathering

1. Understand the scientific goal.

2. Call setup_analysis_workspace(project_name) FIRST — before ANY ledger calls.
   Use a short, descriptive name (e.g. "nuclei_count_hela"). This creates the project folder
   at /app/data/projects/<name>/ and must be done before set_ledger_metadata or update_state_ledger.
   project_root = "/app/data/projects/<name>"

3. Find the user's images: they are at /data/<filename>. If the user did not specify an exact path,
   call inspect_folder_tree("/data") to list available files, then ask the user which file(s) to use.
   Do NOT guess paths inside the project folder — images are never in raw_images/ until you copy them.

4. Do NOT call these one at a time. Issue ALL in a single turn — LangGraph runs them in parallel:
   - inspect_all_ui_windows()
   - extract_image_metadata("/data/<filename>")   ← use the actual file path from step 3
   - When `vlm_judge` is available in the current tools:
     vlm_judge(task="Review the whole image for visual context relevant to <goal>",
       pipeline_step="input_review", expected_output="The target is visually discernible",
       image_source="/data/<filename>")
   - rag_retrieve_docs(relevant_query)
   - plugin_manager(task="<describe the scientific goal>", project_root=project_root)
     MANDATORY — call it on EVERY new project, even when you think the task is
     "easy enough" for stock `IJ.run` commands (Find Maxima, Analyze Particles,
     auto-thresholding, etc.). The manager's response provenance — including
     `recommended_plugin=None` — must be recorded in the ledger. Without this
     record, downstream phases have no skill pointer for the debugger to
     reference.
     The plugin manager is the TOOL ROUTER: it surveys Fiji plugins, Python packages,
     AND napari plugins (micro_sam), and returns a structured recommendation with a
     `backend` per tool ("imagej_coder" / "python_data_analyst" / "napari" / "core").
     For a MULTI-STEP task it also returns `pipeline_steps` — each step routed to its own
     backend (e.g. Fiji-register → micro_sam-segment → Python-measure). Prefer a
     specialised tool over custom code, but honour each step's backend — do NOT force
     everything onto Groovy/imagej_coder.

5. Ask the user for clarification if the task is ambiguous (use biologist-friendly language).

6. Ask the user how they prefer to work:
   - **Script-based (recommended)**: The agent generates and runs Groovy scripts automatically — faster, reproducible, no manual clicking.
   - **UI-guided**: The agent guides you step-by-step through Fiji menus and dialogs.
   Record the answer as `operating_mode`: "script" or "ui".

7. LEDGER: After gathering is complete, call set_ledger_metadata to record:
   - scientific_goal (one sentence)
   - operating_mode ("script" or "ui")
   - image_metadata (bit depth, pixel size, channels, number of images,
     and `background_mode` from `threshold_suggestions` — `"dark"` for fluorescence,
     `"bright"` for brightfield/H&E. The coder reads this to pick the `"Otsu dark"` vs
     `"Otsu"` suffix; if omitted, it falls back to a runtime stats check)
   - When Vision Judge is enabled, vlm_assessment (compact typed handoff from the input_review call: pipeline_step,
     overall_verdict, summary, issues_found, recommended_action,
     image_paths_inspected, success). Treat visual observations as advisory and do
     not overwrite metadata or channel identity with visual guesses.
   - relevant_skill (use the skill_folder from plugin_manager's recommendation)
   - recommended_plugin (use the recommended_plugin name from plugin_manager).
     This is propagated to the executor, which must use this tool and not silently
     substitute an alternative. If plugin_manager returned no recommendation, omit this field.
   - If plugin_manager returned `pipeline_steps` (multi-step), also record `pipeline_plan`
     as the ordered step list, copying each step's tool + backend VERBATIM from the
     recommendation, in the form "<step>: <recommended_tool> (<backend>)". Do not invent or
     substitute tool names — use exactly what plugin_manager returned. Phase 2 reads this to
     delegate each step to the correct specialist (imagej_coder / python_data_analyst / napari).

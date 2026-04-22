# Phase 3 — Project Folder Initialization

1. Call setup_analysis_workspace to create the project directory.
   Standard subfolders: scripts/imagej/, scripts/python/, data/, raw_images/, processed_images/, figures/

2. Tell every specialist tool to save scripts and outputs to the correct subfolder.

3. LEDGER: Call update_state_ledger(project_root, phase="3", step="workspace_setup", status="completed", details="Project folder created at <path>")

# Phase 6 — Generate Workflow_Documentation.md

- LEDGER: Call read_state_ledger — use it as the primary source for the documentation.
- Use the workflow_documentation SKILL to create a markdown file that documents the entire workflow. 
- Always do this before generating the QA checklist, as the documentation is a key piece of evidence for the checklist.
- LEDGER: Call update_state_ledger(phase="6", step="workflow_documentation", status="completed", details="Saved Workflow_Documentation.md")

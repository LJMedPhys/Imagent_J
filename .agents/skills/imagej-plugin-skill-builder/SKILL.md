---
name: imagej-plugin-skill-builder
description: Create or update ImageJ/Fiji plugin documentation skills for this repo's agent system. Use when Codex needs to turn a Fiji/ImageJ plugin into a repo skill under `skills/`, author concise SKILL/API/UI/workflow files, verify commands in the Fiji container on a real image, and document gaps instead of inventing commands.
---

Create repo-local plugin skills that are concise, source-grounded, and
container-validated.

## Core Rules

- Start from the current `skills/` inventory and avoid plugins that are already implemented.
- Prefer official plugin sources first: imagej.net, plugin GitHub/docs, and plugin source code.
- Keep `SKILL.md` as an overview only. Push syntax, workflows, and checklists into companion files.
- Keep checked-in skill files formal and declarative. Do not write process narration or date-stamped validation wording such as "Validated on ..." in `SKILL.md`, API files, UI guides, or workflow files.
- Separate each claim into one of three buckets:
  - official-doc claim
  - container-validated claim
  - explicitly unverified / excluded
- Never invent commands, parameter keys, pretrained models, or file outputs.
- If the official macro string and the repo's Groovy execution behavior diverge, document both and prefer the container-validated execution path in workflow scripts.

## Open These Files

| File | Use |
|------|-----|
| `AUTHORING_WORKFLOW.md` | Use for end-to-end source gathering, skill package structure, and report expectations. |
| `FILE_BLUEPRINTS.md` | Use for the default file set, naming patterns, and what each file should contain. |
| `VALIDATION_CHECKLIST.md` | Use for container verification, discrepancy handling, model/classifier checks, and output sanity checks. |

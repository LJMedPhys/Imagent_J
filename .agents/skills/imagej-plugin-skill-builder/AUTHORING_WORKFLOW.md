# ImageJ Plugin Skill Authoring Workflow

## 1. Gather Primary Sources

Collect only the sources needed to support the skill.

Preferred order:

1. official plugin page on imagej.net
2. official plugin documentation pages
3. official plugin GitHub/docs
4. plugin source code when syntax or outputs need verification
5. image.sc only when primary docs are incomplete

Also inspect local repo context when needed:

- `./skills` for style and file patterns
- `./src/imagentj/prompts.py` and `./src/imagentj/agents.py` only if skill discovery or agent wiring is unclear

Record every source URL you rely on in the external report if the task asks for one.

## 2. Build the Skill Package

Default target location:

- `skills/<plugin>_documentation/` when following this repo's existing plugin-skill pattern

Default deliverables:

- `SKILL.md`
- one API reference file: `GROOVY_API.md`, `GROOVY_SCRIPT_API.md`, or `SCRIPT_API.md`
- one runnable workflow: `GROOVY_WORKFLOW_*.groovy` or `COMMANDLINE_WORKFLOW_*.py`
- `UI_GUIDE.md`
- one step-by-step UI workflow: `UI_WORKFLOW_*.md`

Optional deliverables:

- `OVERVIEW.md` only when the task explicitly wants it or the plugin needs extra background beyond `SKILL.md`
- `../docs/plugin_skills/<plugin>_documentation_report.md` when the task asks for an external report

## 4. Write Each File for LLM Use

### `SKILL.md`

- Keep it short and navigational.
- State the plugin purpose, the verified automation boundary, and where to look next.
- Do not duplicate long syntax tables from the API file.

### API file

- Document only verified commands or class calls.
- Separate standard ImageJ helper calls from plugin-specific automation.
- Use neutral wording. Keep only the final adopted syntax and caveats in the file itself.
- Do not write dated or process-oriented phrases such as:
  - `Validated on April 15, 2026 ...`
  - `In this run we found ...`
  - `The first attempt failed, so ...`

### Workflow file

- Make it runnable with explicit input/output paths or clearly marked variables.
- Explain required inputs at the top.
- Prefer the execution path that was validated in this repo's container.
- Keep comments procedural, not historical. Explain what the script needs and does, not how validation unfolded.

### UI files

- Use only verified menu paths, actions, and shortcuts.
- Keep the guide broad and the workflow narrow.

## 5. Write Down Exclusions

Explicitly list what you are not claiming:

- unverified commands
- guessed parameter keys
- undocumented quoting rules
- undocumented pretrained models or built-in classifiers
- internal APIs you used only for validation and do not want the skill to rely on

## 6. Finish With a Validation-Focused Report

If the task asks for a report, include:

- why the plugin was chosen
- source inventory with URLs
- verified commands and UI paths
- excluded / unverified items
- validation steps and outcomes
- remaining gaps

If validation uncovered a mismatch between official docs and runtime behavior,
state that clearly and say which path the checked-in workflow uses.

Put validation chronology, dates, fallback containers, and debugging history in
the external report only. Do not copy that wording into the checked-in skill
files.

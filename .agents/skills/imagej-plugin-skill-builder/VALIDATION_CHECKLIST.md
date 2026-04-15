# Validation Checklist for ImageJ Plugin Skills

## Use a Real Artifact

- Validate on a real local image, stack, project file, or sample dataset.
- Prefer `./data/` if the repo already contains suitable test data.
- Do not mark a workflow as verified if you only checked syntax by reading docs.

## Confirm the Plugin Is Actually Installed

Check Fiji before assuming the plugin is present.

Useful places:

- `/opt/Fiji.app/plugins`
- `/opt/Fiji.app/jars`

If needed, inspect jar names or class names before writing the final workflow.

## Validation Ladder

Run validation from least invasive to most definitive:

1. Confirm the official documented UI path.
2. Confirm the official documented macro / scripting syntax.
3. Run the documented path in the container.
4. If that path executes but does not expose usable outputs in this repo's execution context:
   - inspect plugin classes or source
   - identify the real input/output fields
   - validate a direct class or `CommandService` path
5. Use the validated path in the checked-in workflow and document the discrepancy.

## Output Sanity Checks

For segmentation or transformation plugins, confirm the output is not silently identical to the input.

Examples:

- compare shape and dtype
- compare min/max or unique values
- compare whether arrays are exactly equal
- record output title or output file path

## Model / Classifier Checks

If the plugin can load models or classifiers:

- search the install for bundled assets before claiming there is a pretrained model
- check for files like `*.classifier`, `*.model`, or `*pretrain*`
- if none are present, say no bundled pretrained asset was found

If you create a temporary classifier or model for validation:

- say that it was generated for validation
- do not present it as a shipped pretrained model
- do not treat same-image train/test success as proof of scientific quality

## Container Caveats

If a fresh `docker compose up -d` fails because of local network or mount issues:

- reuse the already running workspace container if it mounts the same repo and data
- document that fallback in the report

## Final Documentation Rules

- Mark official-doc-only behavior as such.
- Mark container-validated behavior as such.
- List excluded or unresolved items explicitly.
- Never smooth over a discrepancy with a guessed command string.
- In checked-in skill files, express the result as final project guidance rather
  than validation narrative.
- Keep phrases like `Validated on ...`, `during this run`, or container fallback
  history out of `SKILL.md`, API files, UI guides, and workflow files.
- If that context matters, put it in the external report instead.

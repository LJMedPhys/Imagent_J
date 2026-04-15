# File Blueprints for Repo Plugin Skills

## Default Plugin Skill Layout

```text
skills/<plugin>_documentation/
├── SKILL.md
├── <API file>
├── <workflow file>
├── UI_GUIDE.md
└── UI_WORKFLOW_<topic>.md
```

Optional:

```text
skills/<plugin>_documentation/
├── OVERVIEW.md
```

External report when requested:

```text
../docs/plugin_skills/<plugin>_documentation_report.md
```

## File Naming Patterns

Use the pattern that matches the plugin's real automation surface.

| Situation | Preferred file |
|----------|-----------------|
| Fiji macro / `IJ.run()` plugin | `GROOVY_API.md` or `GROOVY_SCRIPT_API.md` |
| Java/SciJava API-heavy plugin | `SCRIPT_API.md` or a focused API file |
| Headless CLI or JAR workflow | `COMMANDLINE_WORKFLOW_*.py` |
| Runnable Fiji script | `GROOVY_WORKFLOW_*.groovy` |

## What Each File Should Do

| File | Role |
|------|------|
| `SKILL.md` | Triggering description plus quick overview and file index |
| API file | Verified syntax, parameter rules, and caveats |
| Workflow file | Minimal runnable example for the validated path |
| `UI_GUIDE.md` | Reference of verified menus, controls, and shortcuts |
| `UI_WORKFLOW_*.md` | Short end-to-end manual walkthrough |

## Wording Style

Use formal project wording in checked-in skill files.

- Prefer: `Use this plugin call ...`
- Prefer: `Required inputs are ...`
- Prefer: `This workflow saves ...`
- Avoid: `Validated on ...`
- Avoid: `During testing we found ...`
- Avoid: `The first path failed, so we switched ...`

Historical validation details belong in the external report, not in the skill
files themselves.

## What to Avoid

- Do not create extra README-style files.
- Do not split content into many tiny files with overlapping purpose.
- Do not put long background explanations into `SKILL.md`.
- Do not let the workflow file become a second API reference.
- Do not put validation dates, debugging narrative, or container-history notes
  into API or workflow files.

## Decision Rules

- If the task explicitly says "SKILL is the overview", skip `OVERVIEW.md`.
- If the plugin has no reliable Fiji scripting path, document the real automation path instead of forcing Groovy.
- If official docs and runtime behavior differ, keep the docs note in the API file and put the validated path in the runnable workflow.

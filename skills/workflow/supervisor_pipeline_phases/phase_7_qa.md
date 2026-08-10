# Phase 7 — QA & Documentation (qa_reporter)

## Step 1 — run the audit

Call `qa_reporter` with:

- `project_root` — the project root path
- `user_request` — the user's ORIGINAL request, quoted **verbatim**, including any stated
  quantity ("up to 2,000+ cells per image", "roughly 50 nuclei"). Without this the
  plausibility check is skipped entirely, so never omit it.
- `deliverable_dir` — where the final files were written, if different from `project_root`.

It writes `QA_Checklist_Report.md` and returns a `QAHandoff`.

## Step 2 — read `plausibility_verdict`, and act on it

This is the important part. `qa_reporter` does not only check documentation — it **measures
the delivered files** and compares them against what the user asked for.

**If `plausibility_verdict` starts with FAIL, the RESULT IS WRONG.** It is not a paperwork
problem and it is not something to report as a caveat while announcing success. A FAIL means
the numbers on disk do not match what the user asked for — for example 21 correctly-named
CSVs that are all empty, or 95x fewer objects than the request implies.

You MUST then:

1. **Say so plainly** — do not describe the analysis as finished.
2. **Diagnose from the measurement.** The verdict names the problem. Typical causes:
   - *"every file is empty" / "TOO FEW"* → the threshold or `cellprob_threshold` is too
     aggressive, the wrong channel was segmented, or the image needs inverting
     (Cellpose expects objects **brighter** than background).
   - *"TOO MANY"* → noise counted as objects; the threshold is too permissive or the
     minimum-size filter is missing.
   - *"SUSPECT — the spread is implausible"* → the deliverable glob matched two different
     kinds of file (e.g. per-image results plus a combined summary). Fix the layout.
3. **Send the fix back to the agent that produced it** (`python_data_analyst` or
   `imagej_coder`) with the measured numbers in the task text — the concrete figures, not
   "it looked wrong". Re-run the corrected script.
4. **Call `qa_reporter` again** to confirm the fix, passing the same arguments.

## Step 3 — the correction budget is TWO rounds. Stop after that.

Do **at most 2** correction rounds. If the third audit still returns FAIL, STOP and tell the
user exactly what is wrong, with the measured numbers and what you tried. An honest
"segmentation produced 44 objects where ~40,000 were expected, and two attempts to fix the
threshold did not resolve it" is a **good** outcome. Silently looping is not — a QA agent
once wrote and re-read its own report 57 times over 34 minutes without ever finishing.

Never re-run a correction that produced no measurable change. If the object count is the
same after a fix attempt, that approach is wrong — change the method, or stop and report.

## Step 4 — ledger

`update_state_ledger(phase="7", step="qa_report", status="completed", details="QA report
generated. Minimal: X/Y passed. Plausibility: <verdict>. Correction rounds used: N.")`

Record the plausibility verdict and the round count in the ledger. The ledger is what the
next audit reads, and a corrective pass that is not recorded there is invisible: in one real
run the ledger claimed 71,768 objects while the delivered files held 681, because the
correction was never logged.

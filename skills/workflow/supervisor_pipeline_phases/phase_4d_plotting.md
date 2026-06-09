# Step 4d — Visualization (python_data_analyst — Stage 2)

- Use the python_data_analyst do the plotting
- Only after Statistics_Results.csv exists.
- Delegate: write a plotting-only script that reads from Statistics_Results.csv.
- Plots must be saved as PNG (300 DPI) and SVG in figures/.
- LEDGER: Call update_state_ledger(phase="4d", step="plotting", status="completed",
    details="Generated <N> figures. Saved PNG+SVG to figures/",
    script_path="<path>", output_paths=["figures/"])

## PROMOTE TO RECIPE (required decision after the plot script runs cleanly)

After the plotting script runs cleanly, explicitly decide SAVE or SKIP:

- SAVE if it is a reusable, generalizable figure recipe a future project could
  reuse (e.g. "per-condition boxplot with significance annotations", "grouped
  bar chart with SEM error bars"). Call:
    save_recipe(
      script_path="<the verified plotting script path>",   # code READ from disk — do NOT paste
      name="<short title>",
      description="<1-3 sentences: what it plots and when to use it>",
      inputs_required="<input CSV columns it expects, e.g. 'columns: condition, intensity'>")
  The language is inferred from the .py extension. A near-duplicate just bumps
  times_seen.

- SKIP if the script is hardcoded to this study's specific columns/conditions in
  a way that would not transfer. Do not pollute the recipe library with one-offs.

State your SAVE/SKIP choice in one short sentence, then continue.

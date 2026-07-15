import os
import pandas as pd
import re
import subprocess
import sys
import textwrap
import io
import threading
from langchain_core.tools import tool
import tempfile

# ---------------------------------------------------------------------------
# Conda envs the Python agent may execute in.
#
# The main env carries the data-science + measurement stack (pandas, seaborn,
# scipy, scikit-image, scikit-learn, cp_measure). brainglobe lives in its
# own env because it drags in napari + PyQt6 + vtk + keras, which collide with the
# main env's PySide6 GUI and force a pillow downgrade.
#
# A script selects its env with a first-line magic comment:
#     # imagentj-env: brainglobe
# Absent the header, the main env is used.
# ---------------------------------------------------------------------------
_CONDA_ENVS: dict[str, str] = {
    "main": "/opt/conda/envs/local_imagent_J/bin/python",
    "brainglobe": "/opt/conda/envs/brainglobe/bin/python",
}
_DEFAULT_ENV = "main"

_ENV_HEADER_RE = re.compile(r"^#\s*imagentj-env:\s*([A-Za-z0-9_.-]+)\s*$")


def _parse_env_header(code: str) -> str:
    """Return the env named by a `# imagentj-env: <name>` comment in the first 5 lines."""
    for line in code.splitlines()[:5]:
        match = _ENV_HEADER_RE.match(line.strip())
        if match:
            return match.group(1)
    return _DEFAULT_ENV


def _resolve_interpreter(env: str) -> tuple[str | None, str | None]:
    """Map an env name to its python binary. Returns (interpreter, error)."""
    if env not in _CONDA_ENVS:
        known = ", ".join(sorted(_CONDA_ENVS))
        return None, f"Error: unknown env '{env}'. Available envs: {known}."
    interpreter = _CONDA_ENVS[env]
    if not os.path.exists(interpreter):
        # Dev/host runs outside the container: fall back to the current interpreter
        # rather than failing, but only for the default env.
        if env == _DEFAULT_ENV:
            return sys.executable, None
        return None, (
            f"Error: env '{env}' is not installed in this container "
            f"(expected {interpreter}). Rebuild the image or use the 'main' env."
        )
    return interpreter, None

# ---------------------------------------------------------------------------
# Global process registry — lets the Stop button kill running subprocesses
# ---------------------------------------------------------------------------
_registry_lock = threading.Lock()
_running_processes: list[subprocess.Popen] = []


def _register_process(proc: subprocess.Popen) -> None:
    with _registry_lock:
        _running_processes.append(proc)


def _unregister_process(proc: subprocess.Popen) -> None:
    with _registry_lock:
        try:
            _running_processes.remove(proc)
        except ValueError:
            pass


def kill_running_processes() -> int:
    """Kill all tracked subprocesses. Called by the Stop button. Returns count killed."""
    killed = 0
    with _registry_lock:
        for proc in list(_running_processes):
            try:
                proc.kill()
                killed += 1
            except Exception:
                pass
        _running_processes.clear()
    return killed

@tool
def inspect_csv_header(file_path: str):
    """
    Returns the COMPLETE schema of a CSV — every column name and dtype — plus a 5-row
    sample preview. This is a SCHEMA tool, not a data loader: it intentionally truncates
    to the first 5 rows (the remaining rows are NOT shown and you do NOT need them). The
    column names and dtypes it returns are the full, exhaustive set — that is everything
    required to write pandas code against this file.

    Call this exactly ONCE per file, BEFORE writing code. The schema never changes while
    you work, so re-calling it (or re-reading the script) returns identical output and
    just wastes turns. Your Python script will read the full data at run time via
    pd.read_csv — you do not need to see the remaining rows here.

    Input MUST be a valid absolute file path (e.g., 'C:/Users/Name/data.csv').
    """
    try:
        # No more path joining; use the path directly
        if not os.path.exists(file_path):
            return f"Error: The file path '{file_path}' does not exist on this PC."

        df = pd.read_csv(file_path, nrows=5)

        buffer = io.StringIO()
        df.info(buf=buffer)
        info_str = buffer.getvalue()

        # Total row count so the model knows the sample is deliberate, not all the data.
        try:
            with open(file_path, "rb") as _f:
                total_rows = max(sum(1 for _ in _f) - 1, 0)  # minus header
            total_str = f"{total_rows} data rows"
        except Exception:
            total_str = "unknown row count"

        base = (
            f"Structure of {os.path.basename(file_path)} ({len(df.columns)} columns, {total_str}):\n"
            f"{info_str}\n"
            f"Sample preview — first 5 of {total_str} (truncated on purpose; the column list "
            f"above is COMPLETE and is all you need to write your code):\n{df.to_string()}\n"
            f"You now have the full schema. Do NOT inspect or re-read again — write your script."
        )
        return base
    except Exception as e:
        return f"Error reading file at {file_path}: {str(e)}"


def run_python_code(code: str, output_directory: str):

    """
    Executes Python code with full PC access.
    Packages pd, np, plt, sns, and stats are PRE-IMPORTED (main env only).
    NEVER execute code that was generated by yourself.

    The script may select a conda env with a first-line magic comment, e.g.
    `# imagentj-env: brainglobe`. Without it the main env is used, and only the
    main env gets the pre-imported data-science preamble.

    Input:
      - code: Python code to execute (string).
      - output_directory: Directory where any output files should be saved (string).
    """
    if not os.path.exists(output_directory):
        return f"Error: Directory '{output_directory}' not found."

    env = _parse_env_header(code)
    interpreter, env_error = _resolve_interpreter(env)
    if env_error:
        return env_error

    # Only the main env is guaranteed to carry seaborn/pandas/scipy. A side env
    # (brainglobe) gets a bare preamble so an import it lacks can't crash the run
    # before the agent's own code starts.
    is_main = env == _DEFAULT_ENV

    header_lines: list[str] = []
    if is_main:
        header_lines += [
            "import pandas as pd",
            "import numpy as np",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "from scipy import stats",
        ]
    header_lines += [
        "import os",
        "import sys",
        "",
        "try:",
        f"    os.chdir(r'{output_directory}')",
    ]
    if is_main:
        header_lines += [
            '    sns.set_theme(style="whitegrid")',
            "    plt.rcParams['figure.dpi'] = 300",
        ]
    header_lines.append("    # --- AGENT CODE START ---")
    header = "\n".join(header_lines)

    footer = textwrap.dedent("""
            # --- AGENT CODE END ---
            print("\\n--- EXECUTION FINISHED SUCCESSFULLY ---")
        except Exception as e:
            print(f"\\nPYTHON TRACEBACK ERROR: {str(e)}", file=sys.stderr)
            sys.exit(1)
    """).strip()
    
    # Indent the agent's code by 4 spaces to align with the 'try' block
    indented_code = textwrap.indent(code, "    ")
    
    full_script = f"{header}\n{indented_code}\n{footer}"

    script_path = os.path.join(tempfile.gettempdir(), "supervisor_py_exec.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(full_script)

    try:
        proc = subprocess.Popen(
            [interpreter, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _register_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return "SYSTEM ERROR: Python script timed out after 600 seconds."
        finally:
            _unregister_process(proc)

        if proc.returncode != 0:
            return (
                f"CRASH DETECTED IN PYTHON (env='{env}'):\n"
                f"STDOUT: {stdout}\nSTDERR: {stderr}"
            )
        # The leading "SUCCESS:" is load-bearing: learned_memory._run_succeeded gates the
        # background Librarian on out.lstrip().startswith("SUCCESS:"). Keep the colon
        # immediately after SUCCESS or Python runs stop being learned as recipes.
        return f"SUCCESS: (env='{env}')\n{stdout}"
    except Exception as e:
        return f"SYSTEM ERROR: {str(e)}"
    

python_analyst_tools = [inspect_csv_header, run_python_code]
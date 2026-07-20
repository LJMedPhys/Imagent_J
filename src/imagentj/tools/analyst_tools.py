import os
import pandas as pd
import re
import signal
import subprocess
import sys
import textwrap
import time
import io
import threading
from langchain_core.tools import tool
import tempfile

from imagentj import run_control

# Backstop only, for when the watchdog is disabled or its LLM is unreachable — a
# run nothing is watching must still not hang the agent forever.
#
# Deliberately generous (2h). The watchdog is the real defence and kills a stuck
# run within minutes; this cap exists solely to bound the unwatched case. Setting
# it tight would silently kill the legitimate long jobs this tool is used for
# (cellpose over a big dataset, stitching, DeepImageJ) hours before they finish,
# overriding a watchdog that had correctly judged them healthy.
_HARD_TIMEOUT_SECONDS = int(os.environ.get("IMAGENTJ_SCRIPT_HARD_TIMEOUT", "7200"))

# ---------------------------------------------------------------------------
# Conda envs the Python agent may execute in.
#
# The main env carries the data-science + measurement stack (pandas, seaborn,
# scipy, scikit-image, scikit-learn, cp_measure). brainglobe lives in its
# own env because it drags in napari + PyQt6 + vtk + keras, which collide with the
# main env's PySide6 GUI and force a pillow downgrade.
#
# napari-mcp is the isolated env that hosts the in-container napari viewer AND the
# micro_sam ("Segment Anything for Microscopy") stack (torch + segment-anything +
# micro_sam). The analyst runs micro_sam batch/automatic segmentation scripts here
# with `# imagentj-env: napari-mcp`; the SAME env backs the interactive napari
# widget the supervisor drives via mcp__napari_mcp__execute_code, so a mask made in
# a script and a mask made interactively come from an identical model.
#
# A script selects its env with a first-line magic comment:
#     # imagentj-env: brainglobe
# Absent the header, the main env is used.
# ---------------------------------------------------------------------------
_CONDA_ENVS: dict[str, str] = {
    "main": "/opt/conda/envs/local_imagent_J/bin/python",
    "brainglobe": "/opt/conda/envs/brainglobe/bin/python",
    "napari-mcp": "/opt/conda/envs/napari-mcp/bin/python",
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
# Subprocess termination
#
# Scripts here routinely fan out into child processes — multiprocessing pools,
# cellpose/stardist workers, napari. proc.kill() only reaps the direct child and
# leaves those orphaned and still burning CPU/GPU, so every run gets its own
# session (start_new_session=True) and we signal the whole process group.
#
# SIGTERM first so a script can unwind (flush files, release the GPU), SIGKILL
# after a grace period for anything ignoring it.
# ---------------------------------------------------------------------------
_TERM_GRACE_SECONDS = 3.0


def _terminate_process_group(proc: subprocess.Popen, grace: float = _TERM_GRACE_SECONDS) -> bool:
    """Signal a run's whole process group down. Returns True once it is gone."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        return True  # already reaped

    # SIGTERM the group and give the direct child time to unwind.
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return True
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)

    # Then SIGKILL the group regardless. The child exiting does not mean the group
    # is empty — a grandchild that ignores SIGTERM would otherwise be left running,
    # which is exactly the orphaned-worker case this function exists to prevent.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    return proc.poll() is not None


def kill_running_processes() -> int:
    """
    Kill every in-flight run. Retained for callers that just want a count;
    run_control.terminate_all() is the richer API the Stop button uses.
    """
    handles = run_control.terminate_all("Stopped by user", by="user")
    return len(handles)


def _drain(stream, sink: list[str], handle: "run_control.RunHandle", label: str) -> None:
    """
    Pump one pipe into both the final transcript and the live handle.

    Reading in a thread is what makes a running script observable at all, and it
    also removes the pipe-buffer deadlock the old communicate() call papered over
    with its timeout: a script printing more than ~64 KB to stderr used to block
    forever once the pipe filled.
    """
    try:
        for line in iter(stream.readline, ""):
            sink.append(line)
            handle.append_output(line if label == "out" else f"[stderr] {line}")
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass

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


def run_python_code(code: str, output_directory: str, purpose: str = ""):

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
            bufsize=1,               # line-buffered: the watchdog sees progress promptly
            start_new_session=True,  # own process group, so we can kill the whole tree
        )
    except Exception as e:
        return f"SYSTEM ERROR: {str(e)}"

    handle = run_control.register(run_control.RunHandle(
        language="python",
        code=code,
        purpose=purpose,
        terminator=lambda reason, p=proc: _terminate_process_group(p),
    ))

    out_lines: list[str] = []
    err_lines: list[str] = []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out_lines, handle, "out"), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_lines, handle, "err"), daemon=True),
    ]
    for reader in readers:
        reader.start()

    try:
        try:
            proc.wait(timeout=_HARD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_process_group(proc)
            handle.terminate(
                f"Exceeded the hard {_HARD_TIMEOUT_SECONDS}s execution limit", by="watchdog"
            )
        for reader in readers:
            reader.join(timeout=5.0)

        stdout = "".join(out_lines)
        stderr = "".join(err_lines)

        # A run we took down deliberately must NOT read as a crash. The debugger
        # agent treats crash output as something to repair, so a user pressing Stop
        # would otherwise kick off a pointless fix-the-nonexistent-bug loop.
        if handle.status == "stopped":
            return (
                f"EXECUTION STOPPED BY USER (env='{env}').\n"
                f"The script was terminated on request — this is NOT a bug to fix. "
                f"Do not retry or debug it; wait for the user's next instruction.\n"
                f"Partial STDOUT before termination:\n{stdout[-2000:]}"
            )
        if handle.status == "killed":
            return (
                f"EXECUTION TERMINATED BY WATCHDOG (env='{env}').\n"
                f"Reason: {handle.kill_reason}\n"
                f"This was not a normal crash — the script was killed while running "
                f"because it appeared stuck or misbehaving. Review the reason and the "
                f"partial output below, then decide whether to fix the script, change "
                f"approach, or ask the user.\n"
                f"Partial STDOUT before termination:\n{stdout[-2000:]}\n"
                f"Partial STDERR:\n{stderr[-1000:]}"
            )

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
    finally:
        # Leave no orphan behind: if we exit this frame for any reason while the
        # child is still up (an exception in our own bookkeeping, say), take the
        # process group down rather than let it keep running unsupervised.
        if proc.poll() is None:
            _terminate_process_group(proc, grace=0.5)
        handle.mark_finished()
        run_control.unregister(handle)



python_analyst_tools = [inspect_csv_header, run_python_code]
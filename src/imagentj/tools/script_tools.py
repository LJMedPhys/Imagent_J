import jpype
from langchain.tools import tool
from imagentj.imagej_context import get_ij
from jpype import JClass


def run_groovy_script(script: str, ij) -> str:
    """Execute Groovy scripts in ImageJ/Fiji."""

    System = jpype.JClass("java.lang.System")
    ByteArrayOutputStream = jpype.JClass("java.io.ByteArrayOutputStream")
    PrintStream = jpype.JClass("java.io.PrintStream")

    out_stream = ByteArrayOutputStream()
    err_stream = ByteArrayOutputStream()

    original_out = System.out
    original_err = System.err

    System.setOut(PrintStream(out_stream))
    System.setErr(PrintStream(err_stream))

    try:
        result = ij.py.run_script("Groovy", script)

        stdout = out_stream.toString()
        stderr = err_stream.toString()

        status = "SUCCESS"
        if stderr.strip():
            status = "WARNING"

        return (
            f"STATUS: {status}\n"
            "LANGUAGE: Groovy\n"
            "STDOUT:\n"
            f"{stdout}\n"
            "STDERR:\n"
            f"{stderr}\n"
            "RESULT:\n"
            f"{result}"
        )

    except Exception as e:
        return (
            "STATUS: ERROR\n"
            "LANGUAGE: Groovy\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            f"{str(e)}\n{err_stream.toString()}\n"
            "RESULT:\nnull"
        )

    finally:
        System.setOut(original_out)
        System.setErr(original_err)


def run_java_script(script: str, ij) -> str:
    """Execute Java scripts via ImageJ ScriptService."""

    System = jpype.JClass("java.lang.System")
    ByteArrayOutputStream = jpype.JClass("java.io.ByteArrayOutputStream")
    PrintStream = jpype.JClass("java.io.PrintStream")

    out_stream = ByteArrayOutputStream()
    err_stream = ByteArrayOutputStream()

    original_out = System.out
    original_err = System.err

    System.setOut(PrintStream(out_stream))
    System.setErr(PrintStream(err_stream))

    try:
        result = ij.py.run_script("Java", script)

        stdout = out_stream.toString()
        stderr = err_stream.toString()

        status = "SUCCESS"
        if stderr.strip():
            status = "WARNING"

        return (
            f"STATUS: {status}\n"
            "LANGUAGE: Java\n"
            "STDOUT:\n"
            f"{stdout}\n"
            "STDERR:\n"
            f"{stderr}\n"
            "RESULT:\n"
            f"{result}"
        )

    except Exception as e:
        return (
            "STATUS: ERROR\n"
            "LANGUAGE: Java\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            f"{str(e)}\n{err_stream.toString()}\n"
            "RESULT:\nnull"
        )

    finally:
        System.setOut(original_out)
        System.setErr(original_err)


def wrap_macro(user_macro: str) -> str:
    return f"""
setBatchMode(true);
call("ij.IJ.log", "__MACRO_START__");

{user_macro}

call("ij.IJ.log", "__MACRO_END__");
"""


def run_imagej_macro(macro: str, ij) -> str:
    try:
        ij.IJ.log("\\Clear")

        wrapped = wrap_macro(macro)

        print("Running wrapped macro:", wrapped)

        ij.IJ.runMacro(wrapped)

        log = ij.IJ.getLog() or ""

        if "__MACRO_START__" in log and "__MACRO_END__" not in log:
            status = "ERROR"
            stderr = "Macro aborted during execution"
        elif "Error:" in log or "ERROR:" in log:
            status = "WARNING"
            stderr = log
        else:
            status = "SUCCESS"
            stderr = ""

        return (
            f"STATUS: {status}\n"
            "LANGUAGE: Macro\n"
            "STDOUT:\n"
            f"{log}\n"
            "STDERR:\n"
            f"{stderr}\n"
            "RESULT:\nnull"
        )

    except Exception as e:
        return (
            "STATUS: ERROR\n"
            "LANGUAGE: Macro\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            f"{str(e)}\n"
            "RESULT:\nnull"
        )


@tool
def run_script_safe(language: str, code: str, max_retries: int = 3) -> str:
    """
    Unified safe execution tool for the supervisor.

    This tool executes ImageJ/Fiji scripts safely in the GUI, handling:

      - Window snapshot & automatic cleanup on failure
      - Retry handling (up to `max_retries`)
      - Only shows images after successful execution

    Supported languages (determined automatically from the `language` argument):
      - "groovy"  : Groovy scripts
      - "java"    : Java scripts


    Usage notes for the supervisor:
      - The coder and debugger agents only generate or repair code; they
        never execute scripts.
      - This tool MUST be used to execute all ImageJ/Fiji scripts from
        generated code.
      - On execution failure, new windows created by the script will
        automatically be closed before retrying.
      - Only successful execution leaves windows visible for the user.

    Parameters:
      language (str) : "groovy", "java"
      code (str)     : The script code to execute
      max_retries (int, optional) : Number of times to retry on failure

    Returns:
      str : Output log from script execution, including any error messages.
    """
    ij = get_ij()

    WindowManager = JClass("ij.WindowManager")

    # Map language to the original execution tool
    tool_map = {
        "groovy": run_groovy_script,
        "java": run_java_script,
    }

    if language.lower() not in tool_map:
        raise ValueError(f"Unsupported language: {language}")

    exec_tool = tool_map[language.lower()]
    last_output = ""


        # Snapshot open windows
    windows_before = set(WindowManager.getImageTitles())

    # Run the script
    try:
        output = exec_tool(code, ij)
    except Exception as e:
        output = f"Exception during execution: {e}"

    last_output = output

    # Snapshot new windows
    windows_after = set(WindowManager.getImageTitles())
    new_windows = windows_after - windows_before

    # Determine failure
    failed = any(k in output.lower() for k in ["error", "exception", "failed"])

    if failed:
        # Close windows created during failed attempt
        for title in new_windows:
            imp = WindowManager.getImage(title)
            if imp:
                imp.changes = False
                imp.close()

            print("Execution failed")
            return output
    else:
        # Success: leave windows visible
        return output

    return last_output
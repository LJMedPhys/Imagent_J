# interactive_agent_runner.py
# Run this from the same environment where `supervisor` is defined.

import sys
import time
from langsmith import traceable
import os
from agents import init_agent
from langchain_openai import ChatOpenAI
from imagej_context import get_ij


os.environ["JAVA_HOME"] = r"C:\Users\lukas.johanns\Downloads\fiji-latest-win64-jdk(1)\Fiji\java\win64"

# from langgraph.checkpoint.memory import MemorySaver  # alternative (in-memory)

# ----- CONFIG -----
THREAD_ID = "imagej_supervisor_thread"   # keep constant to preserve context


# ----- Prepare checkpointer (persistent across runs) -----



# If your supervisor was created *without* the checkpoint, you can re-create it
# or set supervisor.checkpoint = checkpointer depending on API. Here we assume
# you can pass checkpointer when creating the agent. If you already created
# ``supervisor`` without checkpoint, recreate it like you did earlier with:
#
# supervisor = create_deep_agent(..., checkpoint=checkpointer, debug=True, verbose=True)
#
# If you already set checkpoint at creation, skip re-creation.

# ----- Helper: nicely print streaming events -----

thinking = True

def handle_event(event):
    global thinking

    # --- Model thinking / streaming ---
    if "model" in event:
        if thinking:
            print("\n[AI is thinking...]\n")
            thinking = True

        msgs = event["model"].get("messages", [])
        if msgs:
            last = msgs[-1]
            content = (
                last.get("content")
                if isinstance(last, dict)
                else getattr(last, "content", None)
            )
            if content:
                print(content, end="", flush=True)
        return

    # --- Tool invocation ---
    if "tools" in event:
        tools = event["tools"]

        # Handle single or multiple tool calls robustly
        if isinstance(tools, list):
            for t in tools:
                name = t.get("name", "unknown_tool")
                print(f"\n[Calling tool: {name}]")
        elif isinstance(tools, dict):
            name = tools.get("name", "unknown_tool")
            print(f"\n[Calling tool: {name}]")

        return

    # --- Final output ---
    if "output" in event:
        thinking = True
        out = event["output"]
        final_text = out.get("output") or out.get("result") or out

        print("\n\n=== AI ===")
        print(final_text if isinstance(final_text, str) else str(final_text))
        print("==========\n")
        return



intro_message ="""
Hello I am ImageJ agent, some call me ImagentJ :) 
I can design a step-by-step protocol and, if useful, generate a runnable Groovy macro (and execute/test it if you want).

To get started, please share:
- Goal: what you want measured/segmented/processed.
- Example data: 1–2 sample images (file type), single image or batch?
- Image details: dimensions, channels, z-stacks/time series, pixel size (units).
- Targets: what objects/features to detect; which channel(s) matter.
- Preprocessing: background/flat-field correction, denoising needs?
- Outputs: tables/measurements, labeled masks/overlays, ROIs, saved images.
- Constraints: plugins available (e.g., Fiji with Bio-Formats, MorpholibJ, TrackMate, StarDist), OS, any runtime limits.

If you’re unsure, tell me the biological question and show one representative image—I’ll propose a clear plan and a script you can run.

"""

# ----- Interactive loop -----
@traceable
def interactive_loop(agent, checkpointer, thread_id=THREAD_ID):
    config = {"configurable": {"thread_id": thread_id}}

    try:
        agent.checkpoint = checkpointer
    except Exception:
        pass

    print("----- Starting interactive session -----")
    print("(type 'exit' or 'quit' to stop)\n")
    print(intro_message)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        print("\nAI:", end=" ", flush=True)

        for event in agent.stream(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
            stream_mode="updates",
        ):
            handle_event(event)



try:
    global ij
    ij = get_ij()
    ij.ui().showUI()

    supervisor , checkpointer = init_agent() # noqa: F821
except NameError:
    print("ERROR: 'supervisor' agent object not found in this namespace.")
    print("Make sure you created it with create_deep_agent(..., checkpoint=checkpointer, debug=True).")
    sys.exit(1)

interactive_loop(supervisor, checkpointer)


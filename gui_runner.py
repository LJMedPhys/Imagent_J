import sys
import os
import jpype
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QTextEdit, QLineEdit, QPushButton, QLabel,
)
from PySide6.QtCore import QObject, Signal, Slot, QThread
from agents import init_agent
from imagej_context import get_ij


os.environ["JAVA_HOME"] = r"C:\Users\lukas.johanns\Downloads\fiji-latest-win64-jdk(1)\Fiji\java\win64"

# ----- CONFIG -----
THREAD_ID = "imagej_supervisor_thread"   # keep constant to preserve context

intro_message = """
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


class AgentWorker(QObject):
    # Signals to communicate back to the Main Thread
    event_received = Signal(dict)
    finished = Signal()
    error = Signal(str)

    def __init__(self, supervisor, thread_id):
        super().__init__()
        self.supervisor = supervisor
        self.thread_id = thread_id

    @Slot(str)
    def run(self, user_input: str):
        """
        This method runs in the background thread.
        """
        try:
            # --- CRITICAL: Attach this thread to the JVM ---
            # Since ImageJ runs on Java, and this is a new Python thread,
            # we must explicitly attach it to the JVM or ImageJ calls may hang/crash.
            if jpype.isJVMStarted() and not jpype.isThreadAttachedToJVM():
                jpype.attachThreadToJVM()

            config = {"configurable": {"thread_id": self.thread_id}}
            
            # Streaming the agent response
            for event in self.supervisor.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="updates",
            ):
                # Emit result back to GUI immediately
                self.event_received.emit(event)
                
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class ImageJAgentGUI(QWidget):
    # Signal to trigger the worker (This is the fix for the freezing)
    start_agent_work = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageJ Agent GUI")
        self.resize(800, 600)

        # ----- UI Elements -----
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.input_line = QLineEdit()
        self.send_button = QPushButton("Send")
        self.status_label = QLabel("Ready")

        layout = QVBoxLayout()
        layout.addWidget(self.output_area)
        layout.addWidget(self.input_line)
        layout.addWidget(self.send_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        # ----- Connect UI signals -----
        self.send_button.clicked.connect(self.on_send)
        self.input_line.returnPressed.connect(self.on_send)

        # ----- Initialize ImageJ & Agent (Main Thread) -----
        # Note: imagej_context must be thread-safe or carefully managed
        self.ij = get_ij()
        self.ij.ui().showUI()
        
        self.supervisor, self.checkpointer = init_agent()

        self.append_output(intro_message)

    def append_output(self, text):
        self.output_area.append(text)

    def on_agent_finished(self):
        self.status_label.setText("Ready")
        # Optional: Clean up thread resources if desired here
        # self.thread.quit() 

    def on_agent_error(self, msg):
        self.append_output(f"[Agent error]\n{msg}")
        self.status_label.setText("Error")
        self.status_label.setStyleSheet("color: red;")

    def on_send(self):
        user_input = self.input_line.text().strip()
        if not user_input:
            return

        self.input_line.clear()
        self.append_output(f"\n<b>You:</b> {user_input}")
        self.append_output("AI: ...")
        self.status_label.setText("Thinking...")
        self.status_label.setStyleSheet("color: blue;")

        # --- Threading Setup ---
        # 1. Create Thread and Worker
        self.thread = QThread()
        self.worker = AgentWorker(self.supervisor, THREAD_ID)
        
        # 2. Move Worker to Thread
        self.worker.moveToThread(self.thread)

        # 3. Connect Signals
        
        # FIX: Connect our custom Signal to the Worker's run Slot
        self.start_agent_work.connect(self.worker.run)
        
        # Standard cleanup connections
        self.worker.event_received.connect(self.handle_event)
        self.worker.error.connect(self.on_agent_error)
        self.worker.finished.connect(self.on_agent_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # 4. Start the thread
        self.thread.start()

        # 5. Emit the signal to trigger the work
        # This effectively pushes 'user_input' into the background thread's queue
        self.start_agent_work.emit(user_input)

    def handle_event(self, event):
        """
        Parses LangGraph events and updates UI.
        Runs on Main Thread via Signal.
        """
        # 1) Assistant text messages
        if "model" in event:
            model = event["model"]
            for msg in model.get("messages", []):
                content = getattr(msg, "content", None)
                if content:
                    # Update text nicely (removes the "AI: ..." placeholder implicitly by appending)
                    self.append_output(f"{content}")

            for tool_call in model.get("tool_calls", []):
                name = tool_call.get("name")
                args = tool_call.get("args", {})
                self.append_output(f"\n<i>[Calling tool: {name}...]</i>")

        # 2) Tool execution results
        if "tools" in event:
            for tool_msg in event["tools"].get("messages", []):
                tool_name = getattr(tool_msg, "name", "Tool")
                # Using blockquote for tool output distinctness
                self.append_output(f"\n> <b>{tool_name} finished.</b>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageJAgentGUI()
    window.show()
    sys.exit(app.exec())
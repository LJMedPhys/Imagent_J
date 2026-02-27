
import sys
sys.path.insert(0, 'src')
import os
import json
import logging
import jpype
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QListWidget,
    QSplitter, QGroupBox, QScrollArea, QMessageBox, QListWidgetItem,
    QSizePolicy, QFrame,
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt, QSize, QEvent
from queue import Queue

from imagentj.agents import init_agent
from imagentj.imagej_context import get_ij
from imagentj.chat_history import ChatHistoryManager

logging.basicConfig(
    filename="/app/data/imagentj_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)
log = logging.getLogger("imagentj")

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts/saved_scripts")

intro_message = """
Hello I am ImageJ agent, some call me ImagentJ :)
I can design a step-by-step protocol and, if useful, generate a runnable Groovy macro (and execute/test it if you want).

To get started, please share:
- Goal: what you want measured/segmented/processed.
- Example data: 1–2 sample images (file type), single image or batch?
- Targets: what objects/features to detect; which channel(s) matter.
- Preprocessing: background/flat-field correction, denoising needs?
- Outputs: tables/measurements, labeled masks/overlays, ROIs, saved images.
- Constraints: plugins available (e.g., Fiji with Bio-Formats, MorpholibJ, TrackMate, StarDist), OS, any runtime limits.

If you're unsure, tell me the biological question and show one representative image—I'll propose a clear plan and a script you can run.
"""

os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = "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"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_PROJECT"] = "pr-majestic-ecumenist-75"
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "true"


# ===========================================================================
# Metrics Panel Widget
# ===========================================================================

class MetricsPanelWidget(QWidget):
    """Compact live dashboard showing token, timing, cost and tool-call stats."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        header = QLabel("<b>📊 Session Metrics</b>")
        header.setAlignment(Qt.AlignCenter)
        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Token group
        tok_box = QGroupBox("Tokens")
        tok_layout = QVBoxLayout(tok_box)
        tok_layout.setSpacing(2)
        self._lbl_in    = QLabel()
        self._lbl_out   = QLabel()
        self._lbl_total = QLabel()
        for lbl in (self._lbl_in, self._lbl_out, self._lbl_total):
            lbl.setTextFormat(Qt.RichText)
            tok_layout.addWidget(lbl)
        root.addWidget(tok_box)

        # Performance group
        perf_box = QGroupBox("Performance")
        perf_layout = QVBoxLayout(perf_box)
        perf_layout.setSpacing(2)
        self._lbl_time = QLabel()
        self._lbl_cost = QLabel()
        for lbl in (self._lbl_time, self._lbl_cost):
            lbl.setTextFormat(Qt.RichText)
            perf_layout.addWidget(lbl)
        root.addWidget(perf_box)

        # Tool group
        tool_box = QGroupBox("Tool Calls")
        tool_layout = QVBoxLayout(tool_box)
        tool_layout.setSpacing(2)
        self._lbl_calls  = QLabel()
        self._lbl_failed = QLabel()
        self._lbl_soft   = QLabel()
        for lbl in (self._lbl_calls, self._lbl_failed, self._lbl_soft):
            lbl.setTextFormat(Qt.RichText)
            tool_layout.addWidget(lbl)
        root.addWidget(tool_box)

        self._btn_reset = QPushButton("🔁 Reset Session Stats")
        self._btn_reset.setStyleSheet("font-size: 11px; padding: 4px;")
        root.addWidget(self._btn_reset)
        root.addStretch()

        self.update_metrics({
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "thinking_seconds": 0.0, "cost_usd": 0.0,
            "tool_calls": 0, "failed_tool_calls": 0, "soft_error_tool_calls": 0,
        })

    @Slot(dict)
    def update_metrics(self, data: dict):
        def fmt(name, value, color, bold=False):
            w = "bold" if bold else "normal"
            return (
                f"<span style='color:#555;'>{name}:</span> "
                f"<span style='color:{color};font-weight:{w};'>{value}</span>"
            )

        self._lbl_in.setText(    fmt("Input",    f"{data['input_tokens']:,}",  "#2980b9"))
        self._lbl_out.setText(   fmt("Output",   f"{data['output_tokens']:,}", "#27ae60"))
        self._lbl_total.setText( fmt("Total",    f"{data['total_tokens']:,}",  "#8e44ad", bold=True))

        secs  = data["thinking_seconds"]
        t_str = f"{int(secs//60)}m {int(secs%60)}s" if secs >= 60 else f"{secs:.1f}s"
        self._lbl_time.setText(  fmt("⏱ Think time", t_str,                    "#16a085"))

        cost = data["cost_usd"]
        cost_str = f"${cost:.4f}" if cost >= 0.0001 else "—"
        self._lbl_cost.setText(  fmt("💰 Est. cost",  cost_str,                 "#c0392b"))

        self._lbl_calls.setText( fmt("Total",          data['tool_calls'],             "#2c3e50"))
        self._lbl_failed.setText(fmt("Hard errors",    data['failed_tool_calls'],      "#e74c3c"))
        self._lbl_soft.setText(  fmt("Soft errors ⚠",  data['soft_error_tool_calls'],  "#e67e22"))


# ===========================================================================
# Chat History Panel
# ===========================================================================

class ChatHistoryPanel(QWidget):
    """Left-hand panel: session list + New Chat button."""

    thread_selected  = Signal(str)   # emits thread_id
    new_chat_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumWidth(180)
        self.setMaximumWidth(280)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QLabel("<b>Chat history</b>")
        header.setStyleSheet("font-size: 13px; padding: 4px 0;")
        layout.addWidget(header)

        self.btn_new = QPushButton("New Chat")
        self.btn_new.setStyleSheet(
            "background-color: #2ecc71; color: white; font-weight: bold; "
            "padding: 6px; border-radius: 4px;"
        )
        self.btn_new.clicked.connect(self.new_chat_requested)
        layout.addWidget(self.btn_new)

        self.session_list = QListWidget()
        self.session_list.setWordWrap(True)
        self.session_list.setStyleSheet(
            "QListWidget { border: 1px solid #ddd; border-radius: 4px; }"
            "QListWidget::item { padding: 6px 4px; border-bottom: 1px solid #eee; }"
            "QListWidget::item:selected { background-color: #3498db; color: white; }"
        )
        self.session_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.session_list)

        self.setLayout(layout)
        self._thread_ids: list[str] = []

    def populate(self, threads: list[tuple[str, dict]]):
        self.session_list.clear()
        self._thread_ids = []
        for thread_id, meta in threads:
            title    = meta.get("title", "Untitled")
            date_str = meta.get("last_updated", "")[:10]
            item = QListWidgetItem(f"{title}\n{date_str}")
            item.setSizeHint(QSize(0, 52))
            self.session_list.addItem(item)
            self._thread_ids.append(thread_id)

    def set_active(self, thread_id: str):
        if thread_id in self._thread_ids:
            self.session_list.setCurrentRow(self._thread_ids.index(thread_id))
        else:
            self.session_list.clearSelection()

    def _on_item_clicked(self, item: QListWidgetItem):
        idx = self.session_list.row(item)
        if 0 <= idx < len(self._thread_ids):
            self.thread_selected.emit(self._thread_ids[idx])


# ===========================================================================
# Agent Worker
# ===========================================================================

class AgentWorker(QObject):
    event_received = Signal(dict)
    finished       = Signal()
    error          = Signal(str)

    def __init__(self, supervisor, thread_id: str, tracker_callback):
        super().__init__()
        self.supervisor       = supervisor
        self.thread_id        = thread_id   # mutable — updated on session switch
        self.tracker_callback = tracker_callback
        self.tasks            = Queue()
        self._stop_requested  = False

    @Slot()
    def start(self):
        if jpype.isJVMStarted() and not jpype.isThreadAttachedToJVM():
            jpype.attachThreadToJVM()

        while True:
            prompt = self.tasks.get()
            if prompt is None:   # poison pill
                break
            self._stop_requested = False
            self._run_prompt(prompt)

    def _run_prompt(self, user_input: str):
        try:
            config = {
                "configurable": {"thread_id": self.thread_id},
                "callbacks":    [self.tracker_callback],
            }
            for event in self.supervisor.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="updates",
            ):
                if self._stop_requested:
                    break
                self.event_received.emit(event)
        except Exception as e:
            log.exception(f"_run_prompt exception: {e}")
            self.error.emit(str(e))
        finally:
            log.debug("_run_prompt finished, emitting finished signal")
            self.finished.emit()

    def submit(self, prompt: str):
        self.tasks.put(prompt)

    def request_stop(self):
        self._stop_requested = True


# ===========================================================================
# Main GUI
# ===========================================================================

class ImageJAgentGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImagentJ - AI Supervisor & Script Library")
        self.resize(1100, 680)
        self.setAcceptDrops(True)
        self.attached_files: list[str] = []

        # History manager
        self.history_manager = ChatHistoryManager()

        # ── Agent + metrics (created here so QApplication already exists) ───
        (self.supervisor,
         self.checkpointer,
         self._metrics,
         self._metrics_bridge,
         self._tracker_cb) = init_agent()

        # ── Build UI ─────────────────────────────────────────────────────────
        main_layout = QHBoxLayout()
        splitter    = QSplitter(Qt.Horizontal)

        # LEFT: chat history sidebar
        self.history_panel = ChatHistoryPanel()
        self.history_panel.thread_selected.connect(self.switch_thread)
        self.history_panel.new_chat_requested.connect(self.new_chat)

        # MIDDLE: chat interface
        chat_widget = QWidget()
        chat_layout = QVBoxLayout()

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)

        self.attachment_status = QLabel("No files attached")
        self.attachment_status.setStyleSheet(
            "color: #7f8c8d; font-style: italic; padding-left: 5px;"
        )

        self.input_line = QTextEdit()
        self.input_line.setFixedHeight(120)

        self.send_button = QPushButton("Send")
        self.send_button.setStyleSheet(
            "background-color: #3498db; color: white; font-weight: bold; padding: 8px;"
        )
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet(
            "background-color: #bdc3c7; color: #7f8c8d; font-weight: bold; padding: 8px;"
        )
        self.stop_button.clicked.connect(self.on_stop)

        self.status_label = QLabel("Agent is ready to help")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.send_button, stretch=4)
        button_layout.addWidget(self.stop_button, stretch=1)

        chat_layout.addWidget(self.output_area,        stretch=3)
        chat_layout.addWidget(self.attachment_status,  stretch=0)
        chat_layout.addWidget(self.input_line,         stretch=1)
        chat_layout.addLayout(button_layout)
        chat_layout.addWidget(self.status_label,       stretch=0)
        chat_widget.setLayout(chat_layout)

        # RIGHT: metrics panel
        self.metrics_panel = MetricsPanelWidget()
        self.metrics_panel.setMinimumWidth(180)
        self.metrics_panel.setMaximumWidth(240)
        self.metrics_panel._btn_reset.clicked.connect(self._reset_metrics)

        splitter.addWidget(self.history_panel)
        splitter.addWidget(chat_widget)
        splitter.addWidget(self.metrics_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        # ── Wire signals ──────────────────────────────────────────────────
        self.send_button.clicked.connect(self.on_send)
        self.input_line.installEventFilter(self)
        self._metrics_bridge.updated.connect(self.metrics_panel.update_metrics)

        # ── ImageJ ───────────────────────────────────────────────────────
        self.ij = get_ij()
        self.ij.ui().showUI()

        # ── Worker thread ─────────────────────────────────────────────────
        self.current_thread_id: str = ""
        self._is_new_thread: bool   = True

        self.thread = QThread()
        self.worker = AgentWorker(self.supervisor, "", self._tracker_cb)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.event_received.connect(self.handle_event)
        self.worker.finished.connect(self.on_agent_finished)
        self.worker.error.connect(self.on_agent_error)
        self.thread.start()

        # ── Init session ──────────────────────────────────────────────────
        self._init_session()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _init_session(self):
        threads = self.history_manager.list_threads()
        self.history_panel.populate(threads)
        if threads:
            self._load_thread(threads[0][0])
        else:
            self._start_new_thread()

    def _start_new_thread(self):
        thread_id = self.history_manager.create_thread()
        self.current_thread_id = thread_id
        self.worker.thread_id  = thread_id
        self._is_new_thread    = True
        self.output_area.clear()
        self.output_area.append(intro_message)
        self.history_panel.populate(self.history_manager.list_threads())
        self.history_panel.set_active(thread_id)

    def _load_thread(self, thread_id: str):
        self.current_thread_id = thread_id
        self.worker.thread_id  = thread_id
        self._is_new_thread    = False
        self.output_area.clear()
        messages = self.history_manager.get_messages_for_display(self.supervisor, thread_id)
        if not messages:
            self.output_area.append(intro_message)
        else:
            html = self.history_manager.format_messages_as_html(messages)
            self.output_area.setHtml(html)
            self.output_area.moveCursor(QTextCursor.End)
        self.history_panel.set_active(thread_id)

    def new_chat(self):
        if self._agent_is_busy():
            QMessageBox.warning(self, "Agent Busy", "Please wait for the current task to finish.")
            return
        self._start_new_thread()

    def switch_thread(self, thread_id: str):
        if thread_id == self.current_thread_id:
            return
        if self._agent_is_busy():
            QMessageBox.warning(self, "Agent Busy", "Please wait for the current task to finish.")
            return
        self._load_thread(thread_id)

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    def _reset_metrics(self):
        self._metrics.reset()
        self._metrics_bridge.updated.emit(self._metrics.snapshot())

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p not in self.attached_files:
                self.attached_files.append(p)
        self._update_attachment_ui()

    def _update_attachment_ui(self):
        if not self.attached_files:
            self.attachment_status.setText("No files attached")
            self.attachment_status.setStyleSheet(
                "color: #7f8c8d; font-style: italic; padding-left: 5px;"
            )
        else:
            names = [os.path.basename(p) for p in self.attached_files]
            self.attachment_status.setText(f"📎 Attached ({len(names)}): {', '.join(names)}")
            self.attachment_status.setStyleSheet("color: #2980b9; font-weight: bold;")

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj == self.input_line and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    self.on_send()
                    return True
        return super().eventFilter(obj, event)

    def _agent_is_busy(self) -> bool:
        return not self.send_button.isEnabled()

    def append_output(self, text: str):
        self.output_area.append(text)

    def set_status(self, text: str):
        colors = {"Ready": "green", "Thinking...": "blue", "Stopping...": "#e74c3c"}
        color  = colors.get(text, "black")
        if text == "Ready":
            self.status_label.setText("Agent is ready to help")
        else:
            self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_ui_busy(self, busy: bool):
        self.stop_button.setEnabled(busy)
        self.send_button.setDisabled(busy)
        self.input_line.setDisabled(busy)
        self.history_panel.setEnabled(not busy)
        if busy:
            self.stop_button.setStyleSheet(
                "background-color: #e74c3c; color: white; font-weight: bold; padding: 8px;"
            )
            self.send_button.setStyleSheet(
                "background-color: #bdc3c7; color: #7f8c8d; font-weight: bold; padding: 8px;"
            )
        else:
            self.stop_button.setStyleSheet(
                "background-color: #bdc3c7; color: #7f8c8d; font-weight: bold; padding: 8px;"
            )
            self.send_button.setStyleSheet(
                "background-color: #3498db; color: white; font-weight: bold; padding: 8px;"
            )

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def on_stop(self):
        if hasattr(self, 'worker') and self.worker:
            self.append_output("\n<i style='color: #e74c3c;'>🛑 Stopping agent...</i>")
            self.worker.request_stop()
            self.set_status("Stopping...")

    def on_agent_finished(self):
        log.debug("on_agent_finished called")
        try:
            self._tracker_cb.finish_query()
            log.debug("finish_query completed OK")
        except Exception as e:
            log.exception(f"finish_query failed: {e}")

        if hasattr(self, 'worker') and self.worker._stop_requested:
            self.append_output("\n<b style='color: green;'>✓ Agent is ready to help</b>")
        self.set_status("Ready")
        self.set_ui_busy(False)

    def on_agent_error(self, msg: str):
        log.error(f"Agent error: {msg}")
        self.append_output(f"[Agent error]\n{msg}")
        self.status_label.setText("Error")
        self.status_label.setStyleSheet("color: red;")
        self.set_ui_busy(False)

    def _execute_agent_query(self, prompt: str):
        self._tracker_cb.start_query(prompt)
        self.set_status("Thinking...")
        self.set_ui_busy(True)
        self.worker.submit(prompt)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def on_send(self):
        user_input = self.input_line.toPlainText().strip()
        if not user_input and not self.attached_files:
            return

        full_prompt = user_input
        if self.attached_files:
            file_list_str = "\n".join([f"- {p}" for p in self.attached_files])
            full_prompt += f"\n\n[SYSTEM: The user has attached the following files/folders]:\n{file_list_str}"

        self.append_output(f"\n<b>You:</b> {user_input if user_input else '[Attached Files]'}")
        if self.attached_files:
            display_names = ", ".join([os.path.basename(p) for p in self.attached_files])
            self.append_output(f"<i style='color: #2980b9;'>📎 Sent with: {display_names}</i>")

        self.append_output("AI: ...")
        self.input_line.clear()

        # Update history metadata
        current_title = self.history_manager._index.get(
            self.current_thread_id, {}
        ).get("title", "New Chat")
        if current_title == "New Chat" and user_input:
            self.history_manager.update_title(self.current_thread_id, user_input)
            self.history_panel.populate(self.history_manager.list_threads())
            self.history_panel.set_active(self.current_thread_id)
        else:
            self.history_manager.touch_thread(self.current_thread_id)
        self._is_new_thread = False

        self._execute_agent_query(full_prompt)
        self.attached_files = []
        self._update_attachment_ui()

    # ------------------------------------------------------------------
    # Event handler (streaming from agent)
    # ------------------------------------------------------------------

    def handle_event(self, event: dict):
        for node_name, node_data in event.items():
            if "Middleware" in node_name:
                continue

            if node_name in ("supervisor", "model"):
                messages = node_data.get("messages", [])
                for msg in messages:
                    tool_calls = getattr(msg, "tool_calls", [])
                    for tc in tool_calls:
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        if name == "task":
                            agent_type = args.get("subagent_type", "Specialist")
                            desc       = args.get("description", "")
                            short_desc = (desc[:120] + '...') if len(desc) > 120 else desc
                            self.append_output(
                                f"\n<div style='color: #e67e22;'><b>🚀 Routing to {agent_type}:</b></div>"
                            )
                            self.append_output(f"<i style='color: #7f8c8d;'>{short_desc}</i>")
                        else:
                            self.append_output(f"\n<i>[System] Calling tool: {name}...</i>")

            if node_name == "model":
                for msg in node_data.get("messages", []):
                    content = getattr(msg, "content", "")
                    if content and not getattr(msg, "tool_calls", None):
                        self.append_output(content)

        if "tools" in event:
            for tool_msg in event["tools"].get("messages", []):
                name = getattr(tool_msg, "name", "Tool")
                if name == "task":
                    self.append_output("\n✅ <b>Sub-agent task completed.</b>")
                else:
                    self.append_output(f"\n> 🛠️ <b>{name}</b> finished.")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageJAgentGUI()
    window.show()
    sys.exit(app.exec())
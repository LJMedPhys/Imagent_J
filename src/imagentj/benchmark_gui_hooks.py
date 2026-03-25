"""
benchmark_gui_hooks.py — Interactive benchmark hooks for the ImagentJ GUI.

Runs inside the container when ``BENCHMARK_MODE=true`` and
``BENCHMARK_INTERACTIVE=true``.  Integrates with the existing
``gui_runner.py`` via three lines of code (see docstring below).

What it does
------------
1. Reads the benchmark instruction from ``BENCHMARK_OUTPUT_DIR/instruction.txt``
   (the adapter wrote it there before starting the container).
2. Discovers input images in ``BENCHMARK_INPUT_DIR``.
3. Copies images to ``/app/data/benchmark_images/`` (writable path for Fiji).
4. Auto-sends the task into the chat after a short delay.
5. Adds a green **Finish Benchmark** button to the GUI.
6. When the user clicks Finish: collects project outputs into
   ``BENCHMARK_OUTPUT_DIR`` and writes ``result.json`` so the host-side
   adapter detects completion.

Integration with gui_runner.py (3 changes)
------------------------------------------
1. Add import::

       from imagentj.benchmark_gui_hooks import is_interactive_benchmark, setup_benchmark_gui

2. At end of ``ImageJAgentGUI.__init__``, after ``self._init_session()``::

       if is_interactive_benchmark():
           setup_benchmark_gui(self)

3. (Optional) suppress intro message in ``_start_new_thread``::

       if not is_interactive_benchmark():
           self.chat_scroll.add_message('ai', intro_message)
"""

import json
import os
import shutil
from pathlib import Path

from PySide6.QtWidgets import QPushButton, QMessageBox
from PySide6.QtCore import QTimer

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def is_benchmark_mode() -> bool:
    return os.environ.get("BENCHMARK_MODE", "").lower() == "true"


def is_interactive_benchmark() -> bool:
    return (
        is_benchmark_mode()
        and os.environ.get("BENCHMARK_INTERACTIVE", "").lower() == "true"
    )


def _input_dir() -> Path:
    return Path(os.environ.get("BENCHMARK_INPUT_DIR", "/benchmark/input"))


def _output_dir() -> Path:
    return Path(os.environ.get("BENCHMARK_OUTPUT_DIR", "/benchmark/output"))


_IMAGE_EXT = {
    ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp",
    ".nd2", ".czi", ".lif", ".lsm", ".ome.tif", ".ome.tiff",
    ".svs", ".ics", ".ids",
}


# ---------------------------------------------------------------------------
# Read task + stage images
# ---------------------------------------------------------------------------

def _load_task() -> tuple[str, list[Path]]:
    """Read instruction from the output mount and discover input images."""
    instruction = ""
    f = _output_dir() / "instruction.txt"
    if f.exists():
        instruction = f.read_text(encoding="utf-8").strip()

    images = sorted(
        p for p in _input_dir().iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXT
    )
    return instruction, images


def _stage_images(images: list[Path]) -> list[Path]:
    """Copy images to a writable path that Fiji can access."""
    dest = Path("/app/data/benchmark_images")
    dest.mkdir(parents=True, exist_ok=True)
    local = []
    for img in images:
        dst = dest / img.name
        shutil.copy2(str(img), str(dst))
        local.append(dst)
    return local


# ---------------------------------------------------------------------------
# Finish Benchmark — collect outputs and write sentinel
# ---------------------------------------------------------------------------

def _collect_and_finish(gui) -> None:
    out = _output_dir()
    out.mkdir(parents=True, exist_ok=True)

    # Only copy the project folder(s) created during this benchmark session
    proj_root = Path("/app/data/projects")
    before = getattr(gui, "_bench_projects_before", set())

    if proj_root.exists():
        current = {d.name for d in proj_root.iterdir() if d.is_dir()}
        new_folders = current - before

        if not new_folders:
            # Fallback: pick the most recently modified folder
            candidates = [d for d in proj_root.iterdir() if d.is_dir()]
            if candidates:
                newest = max(candidates, key=lambda d: d.stat().st_mtime)
                new_folders = {newest.name}

        for folder_name in new_folders:
            src_dir = proj_root / folder_name
            for src in src_dir.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(proj_root)
                    dst = out / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))

    # Usage metrics
    metadata = {}
    if hasattr(gui, "_metrics"):
        m = gui._metrics
        metadata["total_tokens"] = getattr(m, "total_tokens", 0)
        metadata["total_cost_usd"] = getattr(m, "total_cost", 0.0)
        metadata["num_llm_calls"] = getattr(m, "num_calls", 0)
    if hasattr(gui, "_tracker_cb"):
        try:
            metadata["usage_report"] = gui._tracker_cb.get_report()
        except Exception:
            pass

    # Write sentinel — the adapter on the host polls for this file
    (out / "result.json").write_text(json.dumps({
        "success": True,
        "message": "Interactive benchmark session completed by user.",
        "error": "",
        "metadata": metadata,
    }, indent=2, default=str), encoding="utf-8")


def _on_finish(gui) -> None:
    reply = QMessageBox.question(
        gui, "Finish Benchmark",
        "Are you done with this benchmark task?\n\n"
        "All project outputs will be collected.\n"
        "The container will shut down automatically.",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return

    # Show status immediately
    gui.chat_scroll.add_message(
        "system", "Collecting outputs — please wait …",
    )

    # Let the UI repaint before we start copying files
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()

    _collect_and_finish(gui)

    # Show final message — don't use QMessageBox here because the
    # adapter will kill the container as soon as it sees result.json,
    # which would freeze a modal dialog mid-display.
    gui.chat_scroll.add_message(
        "system",
        "✅ Benchmark finished — outputs collected. "
        "The container will shut down in a moment.",
    )


# ---------------------------------------------------------------------------
# Auto-send the benchmark task into the chat
# ---------------------------------------------------------------------------

def _auto_send(gui) -> None:
    # Start a fresh conversation — don't write into an old thread
    gui._start_new_thread()

    instruction, images = _load_task()
    if not instruction:
        gui.chat_scroll.add_message(
            "error",
            f"Benchmark: no instruction.txt found in {_output_dir()}",
        )
        return

    local_images = _stage_images(images) if images else []
    file_list = "\n".join(f"- {p}" for p in local_images)

    prompt = (
        f"{instruction}\n\n"
        f"[SYSTEM: Input images]:\n{file_list}\n\n"
        f"[SYSTEM: This is a BENCHMARK run. Save ALL outputs to "
        f"{_output_dir().resolve()} as well as the project folder.]\n"
    )

    gui.chat_scroll.add_message(
        "system",
        f"Benchmark task loaded — {len(local_images)} image(s). "
        "Sending to agent …",
    )

    # Populate attachments so the GUI shows them
    gui.attached_files = [str(p) for p in local_images]
    gui._update_attachment_ui()

    # Inject into the input box and trigger send
    gui.input_line.setPlainText(prompt)
    gui.on_send()


# ---------------------------------------------------------------------------
# Public entry point — call from gui_runner.py
# ---------------------------------------------------------------------------

def setup_benchmark_gui(gui) -> None:
    """
    Call once at the end of ``ImageJAgentGUI.__init__()``.
    Adds the Finish button and schedules the auto-send.
    """
    # ── Snapshot existing projects before the task runs ───────────────
    proj_root = Path("/app/data/projects")
    if proj_root.exists():
        gui._bench_projects_before = {d.name for d in proj_root.iterdir() if d.is_dir()}
    else:
        gui._bench_projects_before = set()

    # ── Finish Benchmark button ──────────────────────────────────────
    btn = QPushButton("✅  Finish Benchmark")
    btn.setStyleSheet(
        "QPushButton {"
        "  background-color: #27ae60; color: white; font-weight: bold;"
        "  font-size: 14px; padding: 10px 20px; border-radius: 6px;"
        "  border: 2px solid #1e8449;"
        "}"
        "QPushButton:hover { background-color: #2ecc71; }"
        "QPushButton:pressed { background-color: #1e8449; }"
    )
    btn.setToolTip("Collect all outputs and end the benchmark session.")
    btn.clicked.connect(lambda: _on_finish(gui))

    # Insert into the chat layout (above the attachment status line)
    chat_widget = gui.chat_scroll.parent()
    layout = chat_widget.layout()
    if layout is not None:
        layout.insertWidget(1, btn)

    # ── Auto-send after GUI finishes rendering ───────────────────────
    QTimer.singleShot(3000, lambda: _auto_send(gui))
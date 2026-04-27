"""Start a minimal napari viewer exposed through NapariMCP.

This is a release-story demo helper: run it on the host, then point Agent J at
``http://host.docker.internal:9999/mcp`` from the Docker container.
"""

from __future__ import annotations

import signal
import sys
import time

import napari
import numpy as np
from napari_mcp.bridge_server import NapariBridgeServer
from qtpy.QtWidgets import QApplication


def main() -> None:
    running = True
    viewer = napari.Viewer(title="Agent J NapariMCP Demo")
    viewer.add_image(
        np.random.random((128, 128)),
        name="agentj_demo",
        colormap="viridis",
    )

    server = NapariBridgeServer(viewer, port=9999)
    if not server.start():
        print("NAPARI_MCP_BRIDGE_FAILED", flush=True)
        sys.exit(1)

    print("NAPARI_MCP_BRIDGE_READY http://127.0.0.1:9999/mcp", flush=True)

    def shutdown(*_args: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("No QApplication is available after creating napari viewer.")
    app.setQuitOnLastWindowClosed(False)
    while running:
        app.processEvents()
        time.sleep(0.02)

    try:
        server.stop()
    finally:
        viewer.close()


if __name__ == "__main__":
    main()

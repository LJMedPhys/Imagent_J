"""Start a minimal napari viewer exposed through NapariMCP.

This is a release-story demo helper: run it on the host, then point Agent J at
``http://host.docker.internal:9999/mcp`` from the Docker container.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time


DEFAULT_PORT = 9999


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start a host-side napari viewer exposed through NapariMCP."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("NAPARI_MCP_BRIDGE_PORT", str(DEFAULT_PORT))),
        help=f"Bridge port. Defaults to {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--no-demo-layer",
        action="store_true",
        help="Start napari without adding the random demo image layer.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    import napari
    import numpy as np
    from napari_mcp.bridge_server import NapariBridgeServer
    from qtpy.QtWidgets import QApplication

    running = True
    viewer = napari.Viewer(title="Agent J NapariMCP Demo")
    if not args.no_demo_layer:
        viewer.add_image(
            np.random.random((128, 128)),
            name="agentj_demo",
            colormap="viridis",
        )

    server = NapariBridgeServer(viewer, port=args.port)
    if not server.start():
        print("NAPARI_MCP_BRIDGE_FAILED", flush=True)
        sys.exit(1)

    print(f"NAPARI_MCP_BRIDGE_READY http://127.0.0.1:{args.port}/mcp", flush=True)

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

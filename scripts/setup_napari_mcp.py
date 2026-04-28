#!/usr/bin/env python3
"""Set up a host-side napari-mcp bridge for Agent J.

Run this on the host machine, not inside the Agent J Docker container. The
script creates or reuses an isolated Python environment, installs napari and
napari-mcp, and writes .imagentj/mcp.json so Agent J can discover the bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / ".imagentj" / "mcp.json"
DEFAULT_VENV = REPO_ROOT / ".venv-napari-mcp"
DEFAULT_ENV_NAME = "imagentj-napari-mcp"
DEFAULT_PORT = 9999
SERVER_NAME = "napari-mcp"
NAPARI_MCP_REQUIREMENTS = ["napari-mcp", "fastmcp<3"]

VERIFY_IMPORTS = """
import napari
import napari_mcp
import fastmcp
from fastmcp import FastMCP

napari_version = getattr(napari, "__version__", "unknown")
napari_mcp_version = getattr(napari_mcp, "__version__", "installed")
fastmcp_version = getattr(fastmcp, "__version__", "unknown")
print(f"napari={napari_version}")
print(f"napari-mcp={napari_mcp_version}")
print(f"fastmcp={fastmcp_version}")

if not hasattr(FastMCP("imagentj-napari-mcp-check"), "_tool_manager"):
    raise RuntimeError(
        "napari-mcp 0.1.x expects FastMCP._tool_manager. "
        "Install a compatible FastMCP with: python -m pip install 'fastmcp<3'"
    )
"""


def _display_command(command: Sequence[object]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def _run(command: Sequence[object], *, env: dict[str, str] | None = None) -> None:
    print(f"+ {_display_command(command)}")
    subprocess.run(
        [str(part) for part in command],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def _quiet_success(command: Sequence[object]) -> bool:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _select_env_manager(requested: str) -> str:
    if requested != "auto":
        if requested != "venv" and shutil.which(requested) is None:
            raise SystemExit(f"Requested environment manager is not on PATH: {requested}")
        return requested

    for candidate in ("conda", "mamba", "micromamba"):
        if shutil.which(candidate):
            return candidate
    return "venv"


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _base_python() -> str:
    return shutil.which("python3") or sys.executable


def _ensure_conda_env(manager: str, env_name: str, force_reinstall: bool) -> list[str]:
    env_exists = _quiet_success(
        [manager, "run", "-n", env_name, "python", "-c", "import sys"]
    )
    if not env_exists:
        _run(
            [
                manager,
                "create",
                "-n",
                env_name,
                "-c",
                "conda-forge",
                "python=3.11",
                "napari",
                "pyqt6",
                "pip",
                "-y",
            ]
        )
    else:
        print(f"Using existing {manager} environment: {env_name}")
        _run(
            [
                manager,
                "install",
                "-n",
                env_name,
                "-c",
                "conda-forge",
                "napari",
                "pyqt6",
                "pip",
                "-y",
            ]
        )

    pip_command: list[str] = [
        manager,
        "run",
        "-n",
        env_name,
        "python",
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]
    if force_reinstall:
        pip_command.append("--force-reinstall")
    pip_command.extend(NAPARI_MCP_REQUIREMENTS)
    _run(pip_command)

    python_command = [manager, "run", "-n", env_name, "python"]
    _run([*python_command, "-c", VERIFY_IMPORTS])
    return python_command


def _ensure_venv(venv_path: Path, force_reinstall: bool) -> list[str]:
    python_path = _venv_python(venv_path)
    if not python_path.exists():
        _run([_base_python(), "-m", "venv", venv_path])
    else:
        print(f"Using existing virtualenv: {venv_path}")

    _run([python_path, "-m", "pip", "install", "--upgrade", "pip"])
    pip_command: list[object] = [
        python_path,
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]
    if force_reinstall:
        pip_command.append("--force-reinstall")
    pip_command.extend(["napari[pyqt6,optional]", *NAPARI_MCP_REQUIREMENTS])
    _run(pip_command)

    python_command = [str(python_path)]
    _run([*python_command, "-c", VERIFY_IMPORTS])
    return python_command


def _endpoint_url(agentj_target: str, custom_url: str | None, port: int) -> str:
    if custom_url:
        return custom_url
    host = "host.docker.internal" if agentj_target == "docker" else "127.0.0.1"
    return f"http://{host}:{port}/mcp"


def _write_mcp_config(config_path: Path, endpoint_url: str) -> None:
    if config_path.exists():
        raw_config = config_path.read_text()
        if not raw_config.strip():
            config = {}
        else:
            try:
                config = json.loads(raw_config)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Cannot parse existing MCP config {config_path}: {exc}")
    else:
        config = {}

    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{config_path} has a non-object mcpServers value.")

    servers[SERVER_NAME] = {
        "url": endpoint_url,
        "transport": "http",
        "description": "Host-side NapariMCP bridge",
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Wrote MCP config: {config_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install and register a host-side napari-mcp bridge for Agent J."
    )
    parser.add_argument(
        "--env-manager",
        choices=["auto", "conda", "mamba", "micromamba", "venv"],
        default="auto",
        help="Environment manager to use. Defaults to auto.",
    )
    parser.add_argument(
        "--env-name",
        default=DEFAULT_ENV_NAME,
        help=f"Conda/mamba environment name. Defaults to {DEFAULT_ENV_NAME}.",
    )
    parser.add_argument(
        "--venv-path",
        default=str(DEFAULT_VENV),
        help=f"Virtualenv path when --env-manager=venv. Defaults to {DEFAULT_VENV}.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"MCP config path to write. Defaults to {DEFAULT_CONFIG}.",
    )
    parser.add_argument(
        "--agentj-target",
        choices=["docker", "local"],
        default="docker",
        help="Use docker for Agent J in Docker, local for Agent J on the host.",
    )
    parser.add_argument(
        "--endpoint-url",
        help="Override the URL written into the Agent J MCP config.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"NapariMCP bridge port. Defaults to {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="Force-reinstall napari-mcp into the selected environment.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Only write the Agent J MCP config and print launch instructions.",
    )
    parser.add_argument(
        "--start-bridge",
        action="store_true",
        help="Start the napari-mcp bridge after setup. This keeps running.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    manager = _select_env_manager(args.env_manager)
    config_path = _resolve_path(args.config)
    venv_path = _resolve_path(args.venv_path)
    endpoint = _endpoint_url(args.agentj_target, args.endpoint_url, args.port)

    print(f"Repository: {REPO_ROOT}")
    print(f"Environment manager: {manager}")
    print(f"Agent J endpoint: {endpoint}")

    if args.skip_install:
        if manager == "venv":
            python_command = [str(_venv_python(venv_path))]
        else:
            python_command = [manager, "run", "-n", args.env_name, "python"]
    elif manager == "venv":
        python_command = _ensure_venv(venv_path, args.force_reinstall)
    else:
        python_command = _ensure_conda_env(manager, args.env_name, args.force_reinstall)

    _write_mcp_config(config_path, endpoint)

    launch_command = [
        *python_command,
        str(REPO_ROOT / "scripts" / "start_napari_mcp_bridge.py"),
        "--port",
        str(args.port),
    ]

    print("\nNapariMCP setup complete.")
    print("Start the host-side bridge with:")
    print(f"  {_display_command(launch_command)}")
    print("\nThen start or restart Agent J so it discovers the MCP tools:")
    if args.agentj_target == "docker":
        print("  docker compose up imagentj")
        print("  # or, if it is already running:")
        print("  docker compose restart imagentj")
    else:
        print("  python run.py")
        print("  # or restart the GUI runner if you use it")

    if args.start_bridge:
        print("\nStarting the bridge now. Press Ctrl-C to stop it.")
        bridge_env = os.environ.copy()
        bridge_env["NAPARI_MCP_BRIDGE_PORT"] = str(args.port)
        return subprocess.call(
            [str(part) for part in launch_command],
            cwd=REPO_ROOT,
            env=bridge_env,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

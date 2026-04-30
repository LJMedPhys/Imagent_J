#!/usr/bin/env python3
"""Register an MCP server for Agent J.

This is the Agent J equivalent of app-specific MCP installers such as
napari-mcp's Claude Code installer: it writes one entry into an mcpServers
config file. Agent J's generic MCP host reads that config at startup.
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(".imagentj/mcp.json")


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _write_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")


def _parse_env(items: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--env must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        env[key] = value
    return env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register an MCP server for Agent J.")
    parser.add_argument("name", help="Server name under mcpServers.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Config file to update. Defaults to .imagentj/mcp.json.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="HTTP/SSE MCP endpoint URL.")
    source.add_argument("--command", help="Command for a stdio MCP server.")
    parser.add_argument(
        "--args",
        default="",
        help="Command arguments for stdio mode, parsed like a shell string.",
    )
    parser.add_argument("--cwd", help="Working directory for stdio mode.")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Environment variable for stdio mode, as KEY=VALUE. Repeatable.",
    )
    parser.add_argument("--description", help="Optional server description.")
    parser.add_argument(
        "--transport",
        help="Optional transport hint, such as http, sse, or streamable-http.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser()
    config = _load_config(config_path)
    servers = config.setdefault("mcpServers", {})

    server: dict[str, Any]
    if args.url:
        server = {"url": args.url}
        if args.transport:
            server["transport"] = args.transport
    else:
        server = {
            "command": args.command,
            "args": shlex.split(args.args),
        }
        if args.cwd:
            server["cwd"] = args.cwd
        env = _parse_env(args.env)
        if env:
            server["env"] = env

    if args.description:
        server["description"] = args.description

    servers[args.name] = server
    _write_config(config_path, config)
    print(f"Registered MCP server '{args.name}' in {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

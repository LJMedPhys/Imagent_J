import asyncio
import importlib.machinery
import importlib.util
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, Optional

from langchain.tools import tool


_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_AUTOSTART_WAIT_SECONDS = 20
_PATH_ARGUMENT_KEYS = {"path", "save_path", "save_dir"}
_AUTOSTART_LOCK = threading.Lock()
_AUTOSTART_PROCESS: subprocess.Popen[Any] | None = None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _default_source_dir() -> Optional[str]:
    configured = os.getenv("NAPARI_MCP_SOURCE_DIR")
    if configured:
        return configured

    repo_parent = Path(__file__).resolve().parents[4]
    candidates = [
        repo_parent / "napari-mcp" / "src",
        Path("/app/napari-mcp/src"),
        Path("/opt/napari-mcp/src"),
    ]
    for candidate in candidates:
        if (candidate / "napari_mcp").exists():
            return str(candidate)
    return None


def _timeout_seconds(value: int) -> int:
    try:
        timeout = int(value)
    except Exception:
        timeout = _DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, 600))


def _autostart_wait_seconds() -> int:
    raw = os.getenv("NAPARI_MCP_AUTOSTART_WAIT_SECONDS")
    if raw is None:
        return _DEFAULT_AUTOSTART_WAIT_SECONDS
    return _timeout_seconds(raw)


def _normalise_arguments(arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("NapariMCP arguments JSON must decode to an object.")
        return parsed
    raise TypeError("NapariMCP arguments must be a dict, JSON object string, or null.")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return repr(value)


def _parse_text_payload(content: Any) -> Any:
    if not isinstance(content, list) or len(content) != 1:
        return None

    item = content[0]
    if not isinstance(item, dict) or item.get("type") != "text":
        return None

    text = item.get("text")
    if not isinstance(text, str):
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _tool_to_dict(mcp_tool: Any) -> Dict[str, Any]:
    data = _jsonable(mcp_tool)
    if isinstance(data, dict):
        return {
            "name": data.get("name"),
            "description": data.get("description", ""),
            "input_schema": data.get("inputSchema")
            or data.get("input_schema")
            or data.get("parameters"),
        }
    return {"name": repr(mcp_tool), "description": "", "input_schema": None}


def _serialise_result(result: Any) -> Dict[str, Any]:
    if hasattr(result, "content") or hasattr(result, "structured_content"):
        payload: Dict[str, Any] = {
            "content": _jsonable(getattr(result, "content", None)),
            "is_error": bool(
                getattr(result, "is_error", getattr(result, "isError", False))
            ),
        }
        structured = getattr(result, "structured_content", None)
        if structured is None:
            structured = getattr(result, "structuredContent", None)
        if structured is not None:
            payload["structured_content"] = _jsonable(structured)
            payload["parsed_content"] = _jsonable(structured)
        data_attr = getattr(result, "data", None)
        if data_attr is not None:
            payload["data"] = _jsonable(data_attr)
            payload["parsed_content"] = _jsonable(data_attr)
        if "parsed_content" not in payload:
            parsed = _parse_text_payload(payload["content"])
            if parsed is not None:
                payload["parsed_content"] = parsed
        return payload

    data = _jsonable(result)
    if isinstance(data, dict):
        content = data.get("content")
        parsed = _parse_text_payload(content)
        if parsed is not None:
            data["parsed_content"] = parsed
        return data
    return {"content": data}


def _configured_path_mappings() -> list[tuple[str, str]]:
    mappings: list[tuple[str, str]] = []

    raw_map = os.getenv("NAPARI_MCP_PATH_MAP", "")
    for item in raw_map.split(","):
        text = item.strip()
        if not text or "=" not in text:
            continue
        container_prefix, host_prefix = text.split("=", 1)
        container_prefix = container_prefix.strip().rstrip("/")
        host_prefix = host_prefix.strip().rstrip("/")
        if container_prefix and host_prefix:
            mappings.append((container_prefix, host_prefix))

    host_data_dir = os.getenv("NAPARI_MCP_HOST_DATA_DIR")
    if host_data_dir:
        host_data_dir = host_data_dir.rstrip("/")
        mappings.extend(
            [
                ("/app/data", host_data_dir),
                ("/data", host_data_dir),
            ]
        )

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in mappings:
        if mapping not in seen:
            deduped.append(mapping)
            seen.add(mapping)
    return deduped


def _translate_bridge_path(path: str) -> tuple[str, Optional[Dict[str, str]]]:
    if not path.startswith("/"):
        return path, None

    for container_prefix, host_prefix in _configured_path_mappings():
        if path == container_prefix:
            return host_prefix, {"from": path, "to": host_prefix}
        prefix = container_prefix + "/"
        if path.startswith(prefix):
            relative = path[len(prefix) :]
            translated = str(Path(host_prefix) / relative)
            return translated, {"from": path, "to": translated}
    return path, None


def _translate_napari_arguments(
    arguments: Dict[str, Any],
) -> tuple[Dict[str, Any], list[Dict[str, str]]]:
    translated = dict(arguments)
    path_translations: list[Dict[str, str]] = []
    for key in _PATH_ARGUMENT_KEYS:
        value = translated.get(key)
        if not isinstance(value, str) or not value:
            continue
        new_value, change = _translate_bridge_path(value)
        translated[key] = new_value
        if change:
            change["field"] = key
            path_translations.append(change)
    return translated, path_translations


def _finalise_tool_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict) and result.get("is_error"):
        payload["status"] = "error"
    parsed = result.get("parsed_content") if isinstance(result, dict) else None
    if isinstance(parsed, dict) and parsed.get("status") in {"error", "failed"}:
        payload["status"] = "error"
        payload["message"] = str(parsed.get("message") or parsed)
    return payload


def _stdio_config() -> Dict[str, Any]:
    command = os.getenv("NAPARI_MCP_COMMAND") or sys.executable
    raw_args = os.getenv("NAPARI_MCP_ARGS")
    if raw_args:
        args = shlex.split(raw_args)
    else:
        args = ["-m", "napari_mcp.server"]
        if _bool_env("NAPARI_MCP_AUTO_DETECT", True):
            args.extend(
                [
                    "run",
                    "--auto-detect",
                    "--port",
                    os.getenv("NAPARI_MCP_BRIDGE_PORT", "9999"),
                ]
            )

    env = dict(os.environ)
    source_dir = _default_source_dir()
    if source_dir:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            source_dir if not existing else os.pathsep.join([source_dir, existing])
        )

    cwd = os.getenv("NAPARI_MCP_CWD")
    return {
        "transport": "stdio",
        "command": command,
        "args": args,
        "env": env,
        "cwd": cwd,
        "source_dir": source_dir,
    }


def _active_transport() -> Dict[str, Any]:
    url = os.getenv("NAPARI_MCP_URL")
    if url:
        return {"transport": "http", "url": url}
    return _stdio_config()


def _redacted_transport(config: Dict[str, Any]) -> Dict[str, Any]:
    if config["transport"] == "http":
        return {"transport": "http", "url": config["url"]}
    return {
        "transport": "stdio",
        "command": config["command"],
        "args": config["args"],
        "cwd": config.get("cwd"),
        "source_dir": config.get("source_dir"),
    }


def _configuration_help() -> str:
    return (
        "Set NAPARI_MCP_URL to connect to an already running napari-mcp bridge "
        "(for example http://host.docker.internal:9999/mcp from Docker Desktop), "
        "and optionally set NAPARI_MCP_AUTOSTART=true with "
        "NAPARI_MCP_AUTOSTART_COMMAND to launch that bridge before retrying, "
        "or install napari-mcp in the Agent J environment so the adapter can "
        "start `python -m napari_mcp.server run --auto-detect` over stdio."
    )


def _module_available(name: str, source_dir: Optional[str] = None) -> bool:
    if importlib.util.find_spec(name) is not None:
        return True
    if source_dir:
        return importlib.machinery.PathFinder.find_spec(name, [source_dir]) is not None
    return False


def _connection_probe_target(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return parsed.hostname, port


def _tcp_connects(url: str, timeout: float = 1.0) -> bool:
    target = _connection_probe_target(url)
    if not target:
        return False
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_connection_failure(exc: BaseException) -> bool:
    text = repr(exc).lower()
    needles = (
        "connect",
        "connection",
        "connection refused",
        "connection attempts failed",
        "name or service not known",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "network is unreachable",
    )
    return any(needle in text for needle in needles)


def _autostart_enabled() -> bool:
    return _bool_env("NAPARI_MCP_AUTOSTART", False)


def _start_autostart_process() -> Dict[str, Any]:
    global _AUTOSTART_PROCESS

    command = os.getenv("NAPARI_MCP_AUTOSTART_COMMAND")
    if not command:
        return {
            "status": "skipped",
            "message": (
                "NAPARI_MCP_AUTOSTART is enabled, but "
                "NAPARI_MCP_AUTOSTART_COMMAND is not set."
            ),
        }

    with _AUTOSTART_LOCK:
        if _AUTOSTART_PROCESS and _AUTOSTART_PROCESS.poll() is None:
            return {
                "status": "already_running",
                "pid": _AUTOSTART_PROCESS.pid,
            }

        cwd = os.getenv("NAPARI_MCP_AUTOSTART_CWD") or None
        log_path = os.getenv("NAPARI_MCP_AUTOSTART_LOG")
        stdout = subprocess.DEVNULL
        stderr: int | Any = subprocess.DEVNULL
        log_handle = None
        if log_path:
            path = Path(log_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = path.open("ab")
            stdout = log_handle
            stderr = subprocess.STDOUT

        try:
            _AUTOSTART_PROCESS = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(os.environ),
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except Exception as exc:
            return {"status": "error", "message": f"Autostart failed: {exc}"}
        finally:
            if log_handle is not None:
                log_handle.close()

    return {"status": "started", "pid": _AUTOSTART_PROCESS.pid}


async def _maybe_autostart_http_bridge(config: Dict[str, Any]) -> Dict[str, Any]:
    if not _autostart_enabled():
        return {
            "status": "skipped",
            "message": "Set NAPARI_MCP_AUTOSTART=true to enable bridge autostart.",
        }

    before = _tcp_connects(config["url"])
    if before:
        return {"status": "already_reachable"}

    launch = _start_autostart_process()
    wait_seconds = _autostart_wait_seconds()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _tcp_connects(config["url"]):
            return {
                "status": "ready",
                "launch": launch,
                "wait_seconds": wait_seconds,
            }
        await asyncio.sleep(0.5)

    return {
        "status": "not_ready",
        "launch": launch,
        "wait_seconds": wait_seconds,
        "message": "Autostart command ran, but the NapariMCP URL did not become reachable.",
    }


def _stdio_preflight(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    command = config.get("command")
    args = config.get("args") or []
    uses_current_python = False
    try:
        uses_current_python = Path(command).resolve() == Path(sys.executable).resolve()
    except Exception:
        uses_current_python = command == sys.executable

    if not uses_current_python or args[:2] != ["-m", "napari_mcp.server"]:
        return None

    source_dir = config.get("source_dir")
    missing = [
        name
        for name in ("mcp", "fastmcp", "napari_mcp")
        if not _module_available(name, source_dir=source_dir)
    ]
    if not missing:
        return None

    return {
        "status": "error",
        "transport": _redacted_transport(config),
        "message": (
            "Cannot start the local NapariMCP stdio server because these Python "
            f"modules are missing from the selected environment: {', '.join(missing)}."
        ),
        "help": _configuration_help(),
    }


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    try:
        import nest_asyncio

        nest_asyncio.apply(loop)
        return loop.run_until_complete(coro)
    except Exception:
        outcome: Dict[str, Any] = {}

        def runner() -> None:
            try:
                outcome["value"] = asyncio.run(coro)
            except Exception as exc:  # pragma: no cover - defensive fallback
                outcome["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")


async def _with_timeout(coro: Any, timeout_seconds: int) -> Any:
    return await asyncio.wait_for(coro, timeout=_timeout_seconds(timeout_seconds))


async def _list_tools_http(config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from fastmcp import Client
    except Exception as exc:
        return {
            "status": "error",
            "message": f"fastmcp is required for NAPARI_MCP_URL connections: {exc}",
            "help": _configuration_help(),
        }

    client = Client(config["url"])
    async with client:
        tools = await client.list_tools()
    return {
        "status": "ok",
        "transport": _redacted_transport(config),
        "tools": [_tool_to_dict(item) for item in tools],
    }


async def _call_tool_http(
    config: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        from fastmcp import Client
    except Exception as exc:
        return {
            "status": "error",
            "message": f"fastmcp is required for NAPARI_MCP_URL connections: {exc}",
            "help": _configuration_help(),
        }

    call_arguments, path_translations = _translate_napari_arguments(arguments)
    client = Client(config["url"])
    async with client:
        result = await client.call_tool(tool_name, call_arguments)
    payload = {
        "status": "ok",
        "transport": _redacted_transport(config),
        "tool_name": tool_name,
        "result": _serialise_result(result),
    }
    if path_translations:
        payload["path_translations"] = path_translations
    return _finalise_tool_payload(payload)


async def _stdio_session(config: Dict[str, Any]):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as exc:
        raise RuntimeError(
            "The Python MCP SDK is required for stdio NapariMCP connections. "
            "Install the `mcp` package or set NAPARI_MCP_URL for HTTP bridge mode."
        ) from exc

    params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
        env=config["env"],
        cwd=config.get("cwd"),
    )
    return stdio_client(params), ClientSession


async def _list_tools_stdio(config: Dict[str, Any]) -> Dict[str, Any]:
    preflight = _stdio_preflight(config)
    if preflight:
        return preflight

    stdio_context, client_session = await _stdio_session(config)
    async with stdio_context as (read, write):
        async with client_session(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    tool_items = getattr(tools, "tools", tools)
    return {
        "status": "ok",
        "transport": _redacted_transport(config),
        "tools": [_tool_to_dict(item) for item in tool_items],
    }


async def _call_tool_stdio(
    config: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    preflight = _stdio_preflight(config)
    if preflight:
        preflight["tool_name"] = tool_name
        return preflight

    stdio_context, client_session = await _stdio_session(config)
    async with stdio_context as (read, write):
        async with client_session(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)

    payload = {
        "status": "ok",
        "transport": _redacted_transport(config),
        "tool_name": tool_name,
        "result": _serialise_result(result),
    }
    return _finalise_tool_payload(payload)


async def _list_tools(timeout_seconds: int) -> Dict[str, Any]:
    config = _active_transport()
    try:
        if config["transport"] == "http":
            try:
                return await _with_timeout(_list_tools_http(config), timeout_seconds)
            except Exception as exc:
                if not _is_connection_failure(exc):
                    raise
                autostart = await _maybe_autostart_http_bridge(config)
                try:
                    result = await _with_timeout(
                        _list_tools_http(config), timeout_seconds
                    )
                    result["autostart"] = autostart
                    return result
                except Exception as retry_exc:
                    return {
                        "status": "error",
                        "transport": _redacted_transport(config),
                        "message": str(retry_exc),
                        "autostart": autostart,
                        "help": _configuration_help(),
                    }
        return await _with_timeout(_list_tools_stdio(config), timeout_seconds)
    except Exception as exc:
        return {
            "status": "error",
            "transport": _redacted_transport(config),
            "message": str(exc),
            "help": _configuration_help(),
        }


async def _call_tool(
    tool_name: str, arguments: Dict[str, Any], timeout_seconds: int
) -> Dict[str, Any]:
    config = _active_transport()
    try:
        if config["transport"] == "http":
            try:
                return await _with_timeout(
                    _call_tool_http(config, tool_name, arguments), timeout_seconds
                )
            except Exception as exc:
                if not _is_connection_failure(exc):
                    raise
                autostart = await _maybe_autostart_http_bridge(config)
                try:
                    result = await _with_timeout(
                        _call_tool_http(config, tool_name, arguments),
                        timeout_seconds,
                    )
                    result["autostart"] = autostart
                    return result
                except Exception as retry_exc:
                    return {
                        "status": "error",
                        "transport": _redacted_transport(config),
                        "tool_name": tool_name,
                        "message": str(retry_exc),
                        "autostart": autostart,
                        "help": _configuration_help(),
                    }
        return await _with_timeout(
            _call_tool_stdio(config, tool_name, arguments), timeout_seconds
        )
    except Exception as exc:
        return {
            "status": "error",
            "transport": _redacted_transport(config),
            "tool_name": tool_name,
            "message": str(exc),
            "help": _configuration_help(),
        }


@tool("napari_mcp_list_tools")
def napari_mcp_list_tools(timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> dict:
    """
    List tools exposed by NapariMCP.

    Use only when the user explicitly asks Agent J to use NapariMCP/napari or to
    inspect/control a napari viewer. This proves whether Agent J can reach the
    NapariMCP server before issuing viewer operations.
    """
    return _run_async(_list_tools(timeout_seconds))


@tool("napari_mcp_call")
def napari_mcp_call(
    tool_name: str,
    arguments: Optional[dict] = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Call one NapariMCP tool through Agent J.

    Use only when the user explicitly requests NapariMCP/napari. Prefer
    `session_information` or `list_layers` for a safe first call. For tools such
    as `execute_code`, pass only code that is directly relevant to the user's
    trusted local napari workflow. In HTTP bridge mode, file path arguments such
    as /app/data/... and /data/... are translated to the configured host data
    directory before calling napari. If a call returns status=ok, do not repeat
    the same call; answer the user with the result. If it returns status=error,
    report the exact message instead of retrying the same arguments.
    """
    try:
        normalised_arguments = _normalise_arguments(arguments)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    return _run_async(_call_tool(tool_name, normalised_arguments, timeout_seconds))

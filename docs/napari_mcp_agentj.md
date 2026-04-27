# NapariMCP as an Agent J Leaf Capability

Agent J can call NapariMCP as an optional external tool channel. This keeps the
story simple: Agent J remains the workflow supervisor for ImageJ/Fiji analysis,
documentation, statistics, and reporting; NapariMCP becomes a napari-specific
viewer/control capability that is triggered only when the user explicitly asks
for napari or NapariMCP.

## What Changed

- `napari_mcp_list_tools` lists tools exposed by a reachable NapariMCP server.
- `napari_mcp_call` calls one NapariMCP tool, such as `session_information`,
  `list_layers`, `add_layer`, `screenshot`, or `execute_code`.
- The supervisor prompt tells Agent J to use this bridge only for explicit
  napari/NapariMCP requests.

## Recommended Demo

1. Start a napari session with the NapariMCP plugin.
2. Open `Plugins > napari-mcp: MCP Server Control`.
3. Click `Start Server`.
   For a scripted local demo, first create a Python 3.10+ environment with
   napari and NapariMCP, then run:

   ```bash
   QT_API=pyqt6 python scripts/start_napari_mcp_bridge.py
   ```

4. Start Agent J with:

   ```bash
   export NAPARI_MCP_URL=http://host.docker.internal:9999/mcp
   docker compose up imagentj
   ```

5. Ask Agent J:

   ```text
   Please use NapariMCP and call session_information to show the current napari session.
   ```

A successful response proves that Agent J can reach NapariMCP and call its tools.

## Optional Autostart

Agent J can retry a NapariMCP HTTP call after launching a configured bridge
command. This is intentionally opt-in. Without an explicit command, Agent J will
report that the bridge is down instead of starting arbitrary processes.

```bash
export NAPARI_MCP_URL=http://host.docker.internal:9999/mcp
export NAPARI_MCP_AUTOSTART=true
export NAPARI_MCP_AUTOSTART_COMMAND='QT_API=pyqt6 /path/to/python /path/to/Imagent_J/scripts/start_napari_mcp_bridge.py'
export NAPARI_MCP_AUTOSTART_CWD=/path/to/Imagent_J
export NAPARI_MCP_AUTOSTART_LOG=/tmp/napari-mcp-bridge.log
```

On the first `napari_mcp_list_tools` or `napari_mcp_call` connection failure,
the adapter starts the command, waits for `NAPARI_MCP_URL` to accept TCP
connections, then retries the original MCP request once.

## Docker Notes

Installing graphical napari into the main Agent J image is possible, but it is
not the safest first demo path. Agent J already carries Fiji, Java, PySide, Xvfb,
OpenGL libraries, and several bioimage plugins. Adding napari and another Qt
stack into the same container increases image size and raises Python/Qt/OpenGL
compatibility risk.

The lower-risk demo path is to run napari separately and let Agent J talk to it:

- Local napari on the host: set `NAPARI_MCP_URL=http://host.docker.internal:9999/mcp`.
  A Docker container cannot directly start host GUI applications by itself, so
  autostart requires a host-side launcher/service or a command that is actually
  available inside the Agent J runtime.
- Sidecar napari container: expose a NapariMCP-compatible HTTP endpoint inside
  the Docker network and set `NAPARI_MCP_URL` to that URL. The upstream plugin
  bridge currently binds to `127.0.0.1`, so a sidecar setup needs either a
  same-container reverse proxy or a small bind-host patch; keep it on a private
  Docker network.
- Same Agent J environment: install `napari-mcp` and let the adapter start
  `python -m napari_mcp.server run --auto-detect --port 9999` over stdio.
  Pin `fastmcp<3` with the current NapariMCP code; FastMCP 3.x changed private
  server internals used by NapariMCP's bridge wrapper.

The bridge URL mode is the most useful for a release story because it avoids
coupling Agent J's ImageJ runtime to napari's GUI runtime.

## Configuration

- `NAPARI_MCP_URL`: HTTP bridge URL. Docker Compose defaults to
  `http://host.docker.internal:9999/mcp`, and you can override it for another
  bridge endpoint. If set, Agent J uses direct HTTP.
- `NAPARI_MCP_COMMAND`: command for stdio mode. Defaults to the current Python.
- `NAPARI_MCP_ARGS`: arguments for stdio mode. Defaults to
  `-m napari_mcp.server run --auto-detect --port 9999`.
- `NAPARI_MCP_SOURCE_DIR`: optional source checkout path for local development,
  such as `/app/napari-mcp/src`.
- `NAPARI_MCP_BRIDGE_PORT`: auto-detect bridge port. Defaults to `9999`.
- `NAPARI_MCP_AUTOSTART`: set to `true` to try launching the HTTP bridge when
  the configured `NAPARI_MCP_URL` is unreachable.
- `NAPARI_MCP_AUTOSTART_COMMAND`: command to run when autostart is enabled.
  This command runs where Agent J runs. In Docker, that means inside the
  container unless you provide a host-side bridge manager.
- `NAPARI_MCP_AUTOSTART_CWD`: optional working directory for the command.
- `NAPARI_MCP_AUTOSTART_LOG`: optional log file for command stdout/stderr.
- `NAPARI_MCP_AUTOSTART_WAIT_SECONDS`: how long to wait for the URL to become
  reachable before returning an error. Defaults to `20`.

## Positioning

NapariMCP is excellent at controlling a napari viewer. Agent J's broader value is
orchestration: choosing the image-analysis route, using ImageJ/Fiji plugins,
generating and testing scripts, preserving project state, doing statistics and
plotting, and producing documentation. Showing NapariMCP as a callable leaf
capability makes the relationship complementary rather than competitive.

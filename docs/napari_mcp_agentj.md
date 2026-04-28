# NapariMCP Through Agent J's Generic MCP Host

Agent J does not need a NapariMCP-specific tool adapter. It now behaves like a
small MCP host: load an `mcpServers` config, call `tools/list`, convert each
returned `inputSchema` into a LangChain tool schema, and forward calls through
`tools/call`.

NapariMCP is just one configured MCP server.

## Implementation

- Generic host adapter: `src/imagentj/tools/mcp_host_tools.py`
- Agent registration point: `src/imagentj/agents.py`, via `get_mcp_tools()`
- Runtime tool namespace: `mcp__<server>__<tool>`
- Raw diagnostics: `mcp_list_servers`, `mcp_list_tools`, `mcp_call_tool`

For a config entry named `napari-mcp`, the upstream `add_layer` tool is exposed
to the model as `mcp__napari_mcp__add_layer`. The schema comes from the MCP
server's own `inputSchema`, so Agent J does not hard-code NapariMCP parameters.

## Quick Setup

Run the setup script on the host machine, not inside the Agent J Docker
container:

```bash
python scripts/setup_napari_mcp.py
```

By default the script:

- creates or reuses a conda/mamba environment named `imagentj-napari-mcp`;
- installs `napari`, `pyqt6`, `napari-mcp`, and a compatible `fastmcp<3`;
- writes `.imagentj/mcp.json` with `http://host.docker.internal:9999/mcp`;
- prints the bridge launch command.

If conda/mamba is not available, the script falls back to a local
`.venv-napari-mcp` virtual environment and installs `napari[pyqt6,optional]`
with pip. The `fastmcp<3` pin matters because `napari-mcp 0.1.x` uses FastMCP
2.x internals for bridge-mode tool overrides.

Start the host-side bridge:

```bash
conda run -n imagentj-napari-mcp python scripts/start_napari_mcp_bridge.py
```

If the setup script selected `mamba`, `micromamba`, or a virtualenv, use the
launch command printed by the script instead.

Or install/register and start the bridge in one command:

```bash
python scripts/setup_napari_mcp.py --start-bridge
```

Then start or restart Agent J so dynamic MCP tool discovery runs:

```bash
docker compose up imagentj
# or:
docker compose restart imagentj
```

For a non-Docker Agent J process, use localhost in the generated config:

```bash
python scripts/setup_napari_mcp.py --agentj-target local
```

Useful setup options:

```bash
# Use a specific port.
python scripts/setup_napari_mcp.py --port 9998

# Force a Python virtual environment instead of conda/mamba.
python scripts/setup_napari_mcp.py --env-manager venv

# Register a fully custom endpoint.
python scripts/setup_napari_mcp.py --endpoint-url http://127.0.0.1:9999/mcp
```

## Manual Registration

This is the same idea as `napari-mcp`'s Claude Code installer: write an MCP
server entry into the host application's config. For Agent J, use any of these:

- `IMAGENTJ_MCP_CONFIG_JSON`: inline JSON
- `IMAGENTJ_MCP_CONFIG`: path to a JSON/TOML config file
- `mcp.json`, `.imagentj/mcp.json`, `.mcp.json`, or `~/.imagentj/mcp.json`

Register the default Docker-side URL for the host-side NapariMCP bridge:

```bash
python scripts/install_mcp_server.py napari-mcp \
  --url http://host.docker.internal:9999/mcp \
  --transport http \
  --description "Host-side NapariMCP bridge"
```

HTTP bridge example:

```json
{
  "mcpServers": {
    "napari-mcp": {
      "url": "http://host.docker.internal:9999/mcp",
      "transport": "http"
    }
  }
}
```

Stdio example matching upstream `napari-mcp` installers:

```json
{
  "mcpServers": {
    "napari-mcp": {
      "command": "uv",
      "args": ["run", "--with", "napari-mcp", "napari-mcp"]
    }
  }
}
```

With Docker Compose, the inline version looks like:

```bash
export IMAGENTJ_MCP_CONFIG_JSON='{"mcpServers":{"napari-mcp":{"url":"http://host.docker.internal:9999/mcp","transport":"http"}}}'
docker compose up imagentj
```

## Running the Bridge

For a fresh Agent J-controlled napari window, use the helper script:

```bash
conda run -n imagentj-napari-mcp python scripts/start_napari_mcp_bridge.py
```

If you used `--env-manager venv`, run the printed `.venv-napari-mcp/.../python`
command instead.

You can select a different port:

```bash
conda run -n imagentj-napari-mcp python scripts/start_napari_mcp_bridge.py --port 9998
```

To connect Agent J to an existing napari session instead, start napari from the
environment where `napari-mcp` is installed, open
`Plugins > napari-mcp: MCP Server Control`, and click `Start Server`.

## Troubleshooting

If bridge startup fails with an error like:

```text
AttributeError: 'FastMCP' object has no attribute '_tool_manager'
```

the host-side napari environment installed an incompatible FastMCP 3.x release.
Repair it with:

```bash
conda run -n imagentj-napari-mcp python -m pip install --upgrade 'fastmcp<3'
```

Then start the bridge again.

## Demo

1. Start a napari session with the NapariMCP plugin.
2. Open `Plugins > napari-mcp: MCP Server Control`.
3. Click `Start Server`.
4. Start Agent J with an `mcpServers` config that points at that endpoint.
5. Ask Agent J to inspect the napari session.

If discovery succeeds, Agent J will have tools such as
`mcp__napari_mcp__session_information`, `mcp__napari_mcp__list_layers`, and
`mcp__napari_mcp__add_layer`.

## Configuration Knobs

- `IMAGENTJ_MCP_DISCOVERY_TIMEOUT_SECONDS`: startup discovery timeout.
- `IMAGENTJ_MCP_TOOL_TIMEOUT_SECONDS`: per-tool call timeout.
- `IMAGENTJ_MCP_KEEP_ALIVE`: keep stdio MCP clients alive between calls.
- `IMAGENTJ_MCP_PATH_MAP`: comma-separated path mappings such as
  `/app/data=/Users/me/project/data,/data=/Users/me/project/data`.
- `IMAGENTJ_MCP_HOST_DATA_DIR`: shortcut that maps `/app/data` and `/data` to a
  host directory.

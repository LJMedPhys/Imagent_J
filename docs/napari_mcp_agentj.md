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

## Registering NapariMCP

This is the same idea as `napari-mcp`'s Claude Code installer: write an MCP
server entry into the host application's config. For Agent J, use any of these:

- `IMAGENTJ_MCP_CONFIG_JSON`: inline JSON
- `IMAGENTJ_MCP_CONFIG`: path to a JSON/TOML config file
- `mcp.json`, `.imagentj/mcp.json`, `.mcp.json`, or `~/.imagentj/mcp.json`

Register the default host-side NapariMCP bridge:

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

# Security Policy

`nbs-mcp-server` is intended to run locally as an MCP stdio server.

## Filesystem Access

By default the server can access paths supplied by your MCP client. This keeps installation simple and matches common local MCP server behavior.

For locked-down setups, run the configurator with `--allowed-root <directory>`. That writes `NBS_MCP_ALLOWED_ROOT`, and the server will only read/write files inside that directory.

Do not set an allowed root to a sensitive system directory.

## Reporting Issues

Please report security issues privately through your repository's preferred security contact, or open a GitHub security advisory after publishing the repository.

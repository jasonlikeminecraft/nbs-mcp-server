# Security Policy

`nbs-mcp-server` is intended to run locally as an MCP stdio server.

## Filesystem Access

Tools only allow paths inside `NBS_MCP_ALLOWED_ROOT`. If the environment variable is not set, the server uses the current working directory at startup.

Do not set `NBS_MCP_ALLOWED_ROOT` to a sensitive system directory.

## Reporting Issues

Please report security issues privately through your repository's preferred security contact, or open a GitHub security advisory after publishing the repository.

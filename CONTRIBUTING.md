# Contributing

Thanks for helping improve `nbs-mcp-server`.

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Checks

Run the smoke test before opening a pull request:

```bash
python tests/smoke_test.py
```

Also run:

```bash
python -m compileall .
```

## Design Notes

- Keep MCP tools returning the same envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": ..., "details": ...}`.
- Keep optional filesystem restriction behavior working when `NBS_MCP_ALLOWED_ROOT` is set.
- Prefer extending the compatibility functions in `nbs_core.py` instead of coupling tools directly to a specific `.nbs` library.
- Add AI-readable, structured return data for new tools.

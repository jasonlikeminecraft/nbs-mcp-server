from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SERVER_NAME = "nbs"
PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ClientTarget:
    key: str
    name: str
    paths: tuple[Path, ...]
    format: str = "json"
    notes: str = ""


def _home() -> Path:
    return Path.home()


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _platform_paths() -> dict[str, ClientTarget]:
    system = platform.system().lower()
    home = _home()
    appdata = _env_path("APPDATA")

    if system == "windows":
        claude = ((appdata / "Claude" / "claude_desktop_config.json",) if appdata else ())
        cursor = tuple(
            path
            for path in [
                home / ".cursor" / "mcp.json",
                (appdata / "Cursor" / "User" / "mcp.json") if appdata else None,
            ]
            if path is not None
        )
        windsurf = tuple(
            path
            for path in [
                home / ".codeium" / "windsurf" / "mcp_config.json",
                (appdata / "Windsurf" / "User" / "mcp.json") if appdata else None,
            ]
            if path is not None
        )
        vscode_global = (appdata / "Code" / "User" / "globalStorage") if appdata else None
    elif system == "darwin":
        claude = (home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",)
        cursor = (
            home / ".cursor" / "mcp.json",
            home / "Library" / "Application Support" / "Cursor" / "User" / "mcp.json",
        )
        windsurf = (
            home / ".codeium" / "windsurf" / "mcp_config.json",
            home / "Library" / "Application Support" / "Windsurf" / "User" / "mcp.json",
        )
        vscode_global = home / "Library" / "Application Support" / "Code" / "User" / "globalStorage"
    else:
        claude = (
            home / ".config" / "Claude" / "claude_desktop_config.json",
            home / ".config" / "claude" / "claude_desktop_config.json",
        )
        cursor = (
            home / ".cursor" / "mcp.json",
            home / ".config" / "Cursor" / "User" / "mcp.json",
        )
        windsurf = (
            home / ".codeium" / "windsurf" / "mcp_config.json",
            home / ".config" / "Windsurf" / "User" / "mcp.json",
        )
        vscode_global = home / ".config" / "Code" / "User" / "globalStorage"

    cline_paths: tuple[Path, ...] = ()
    roo_paths: tuple[Path, ...] = ()
    if vscode_global:
        cline_paths = (
            vscode_global / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
            vscode_global / "saoudrizwan.claude-dev" / "settings" / "mcp_settings.json",
        )
        roo_paths = (
            vscode_global / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
            vscode_global / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
        )

    return {
        "claude_desktop": ClientTarget("claude_desktop", "Claude Desktop", claude),
        "cursor": ClientTarget("cursor", "Cursor", cursor),
        "windsurf": ClientTarget("windsurf", "Windsurf", windsurf),
        "cline": ClientTarget("cline", "Cline", cline_paths, notes="VS Code extension config if the extension has created its storage folder."),
        "roo_code": ClientTarget("roo_code", "Roo Code", roo_paths, notes="VS Code extension config if the extension has created its storage folder."),
        "codex": ClientTarget("codex", "Codex", (home / ".codex" / "config.toml",), "toml", "Codex CLI/Desktop config.toml."),
    }


def server_entry(allowed_root: Path, command_mode: str) -> dict[str, Any]:
    env = {"NBS_MCP_ALLOWED_ROOT": str(allowed_root)}
    if command_mode == "script":
        return {"command": "nbs-mcp-server", "args": [], "env": env}
    server_py = PROJECT_ROOT / "server.py"
    return {"command": sys.executable, "args": [str(server_py)], "env": env}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any], dry_run: bool, backup: bool) -> str | None:
    if dry_run:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: str | None = None
    if backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_file = path.with_suffix(path.suffix + f".bak-{timestamp}")
        shutil.copy2(path, backup_file)
        backup_path = str(backup_file)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")
    return backup_path


def _quote_toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_quote_toml_string(value) for value in values) + "]"


def codex_block(entry: dict[str, Any]) -> str:
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {_quote_toml_string(str(entry['command']))}",
    ]
    args = entry.get("args", [])
    if args:
        lines.append(f"args = {_toml_array([str(item) for item in args])}")
    env = entry.get("env", {})
    if env:
        lines.append("env = { " + ", ".join(f"{key} = {_quote_toml_string(str(value))}" for key, value in env.items()) + " }")
    return "\n".join(lines) + "\n"


def remove_codex_block(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    output: list[str] = []
    changed = False
    index = 0
    header = f"[mcp_servers.{SERVER_NAME}]"
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == header:
            changed = True
            index += 1
            while index < len(lines):
                next_stripped = lines[index].strip()
                if next_stripped.startswith("[") and next_stripped.endswith("]"):
                    break
                index += 1
            continue
        output.append(lines[index])
        index += 1
    cleaned = "\n".join(output).rstrip()
    return (cleaned + "\n" if cleaned else ""), changed


def write_text(path: Path, text: str, dry_run: bool, backup: bool) -> str | None:
    if dry_run:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: str | None = None
    if backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_file = path.with_suffix(path.suffix + f".bak-{timestamp}")
        shutil.copy2(path, backup_file)
        backup_path = str(backup_file)
    path.write_text(text, encoding="utf-8", newline="\n")
    return backup_path


def choose_paths(target: ClientTarget, create_missing: bool) -> list[Path]:
    existing = [path for path in target.paths if path.exists()]
    if existing:
        return existing
    parent_existing = [path for path in target.paths if path.parent.exists()]
    if parent_existing:
        return [parent_existing[0]]
    if create_missing and target.paths:
        return [target.paths[0]]
    return []


def configure_path(path: Path, entry: dict[str, Any], remove: bool, dry_run: bool, backup: bool) -> dict[str, Any]:
    data = load_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: mcpServers must be a JSON object")

    before = servers.get(SERVER_NAME)
    if remove:
        changed = SERVER_NAME in servers
        servers.pop(SERVER_NAME, None)
        action = "removed" if changed else "unchanged"
    else:
        changed = before != entry
        servers[SERVER_NAME] = entry
        action = "updated" if before else "added"
        if not changed and before:
            action = "unchanged"

    backup_path = write_json(path, data, dry_run=dry_run, backup=backup) if changed else None
    dry_run_action = {
        "added": "would_add",
        "updated": "would_update",
        "removed": "would_remove",
        "unchanged": "unchanged",
    }.get(action, "would_change")
    return {
        "path": str(path),
        "action": dry_run_action if dry_run and changed else action,
        "changed": changed,
        "backup": backup_path,
    }


def configure_codex_path(path: Path, entry: dict[str, Any], remove: bool, dry_run: bool, backup: bool) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    without_block, had_block = remove_codex_block(text)
    if remove:
        changed = had_block
        action = "removed" if changed else "unchanged"
        new_text = without_block
    else:
        block = codex_block(entry)
        new_text = without_block.rstrip() + ("\n\n" if without_block.strip() else "") + block
        changed = new_text != text
        action = "updated" if had_block else "added"
        if not changed:
            action = "unchanged"
    backup_path = write_text(path, new_text, dry_run=dry_run, backup=backup) if changed else None
    dry_run_action = {
        "added": "would_add",
        "updated": "would_update",
        "removed": "would_remove",
        "unchanged": "unchanged",
    }.get(action, "would_change")
    return {
        "path": str(path),
        "action": dry_run_action if dry_run and changed else action,
        "changed": changed,
        "backup": backup_path,
    }


def detected_client_keys(available: dict[str, ClientTarget]) -> list[str]:
    return [key for key, target in available.items() if choose_paths(target, create_missing=False)]


def parse_clients(value: str, available: dict[str, ClientTarget]) -> list[str]:
    if value == "all":
        return list(available)
    if value == "detected":
        return detected_client_keys(available)
    result = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(result) - set(available))
    if unknown:
        raise ValueError(f"unknown clients: {', '.join(unknown)}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure common AI MCP clients for nbs-mcp-server.")
    parser.add_argument("--clients", default="detected", help="Comma-separated clients, 'detected', or 'all'. Known: claude_desktop,cursor,windsurf,cline,roo_code,codex")
    parser.add_argument("--allowed-root", default=str(PROJECT_ROOT), help="Directory that nbs-mcp-server may read/write.")
    parser.add_argument("--command-mode", choices=["python", "script"], default="python", help="Use current Python + server.py, or the installed nbs-mcp-server script.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing files.")
    parser.add_argument("--remove", action="store_true", help="Remove the nbs server entry from selected clients.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create backups before modifying existing config files.")
    parser.add_argument("--create-missing", action="store_true", help="Create a config file even if the client config directory does not exist.")
    parser.add_argument("--list-clients", action="store_true", help="List known clients and candidate config paths.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    clients = _platform_paths()

    if args.list_clients:
        for target in clients.values():
            print(f"{target.key}: {target.name}")
            for path in target.paths:
                marker = "exists" if path.exists() else "missing"
                print(f"  - {path} [{marker}]")
            if target.notes:
                print(f"    note: {target.notes}")
        return 0

    allowed_root = Path(args.allowed_root).expanduser().resolve()
    entry = server_entry(allowed_root, args.command_mode)
    selected = parse_clients(args.clients, clients)
    if not selected:
        print(json.dumps({"server_name": SERVER_NAME, "entry": entry, "results": [], "message": "No existing MCP client config files were detected. Run with --list-clients to inspect paths, or --clients all --create-missing to create config files."}, indent=2, ensure_ascii=False))
        return 0
    results = []
    for key in selected:
        target = clients[key]
        paths = choose_paths(target, create_missing=args.create_missing)
        if not paths:
            results.append({"client": target.name, "action": "skipped", "reason": "no config path found", "candidate_paths": [str(path) for path in target.paths]})
            continue
        for path in paths:
            try:
                if target.format == "toml":
                    result = configure_codex_path(path, entry, remove=args.remove, dry_run=args.dry_run, backup=not args.no_backup)
                else:
                    result = configure_path(path, entry, remove=args.remove, dry_run=args.dry_run, backup=not args.no_backup)
                result["client"] = target.name
                results.append(result)
            except Exception as exc:
                results.append({"client": target.name, "path": str(path), "action": "error", "error": str(exc)})

    print(json.dumps({"server_name": SERVER_NAME, "entry": entry, "results": results}, indent=2, ensure_ascii=False))
    return 1 if any(item.get("action") == "error" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

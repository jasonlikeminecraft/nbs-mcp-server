from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from configure_clients import main as configure_main


PROJECT_ROOT = Path(__file__).resolve().parent


def run(command: list[str], *, check: bool = True) -> int:
    print("+ " + " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def install_package() -> None:
    run([sys.executable, "-m", "pip", "install", "-e", "."])


def git_pull() -> None:
    if not (PROJECT_ROOT / ".git").exists():
        print("No .git directory found; skipping git pull.")
        return
    run(["git", "pull"])


def configure_clients(args: list[str] | None = None) -> None:
    status = configure_main(args or [])
    if status != 0:
        raise SystemExit(status)


def install(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install nbs-mcp-server and configure detected MCP clients.")
    parser.add_argument("--skip-pip", action="store_true", help="Skip pip install -e .")
    parser.add_argument("--dry-run", action="store_true", help="Show client config changes without writing them.")
    parser.add_argument("--clients", default="detected", help="Clients to configure: detected, all, or comma-separated names.")
    args = parser.parse_args(argv)

    if not args.skip_pip:
        install_package()
    configure_args = ["--clients", args.clients]
    if args.dry_run:
        configure_args.append("--dry-run")
    configure_clients(configure_args)
    print("Install complete. Restart your AI client to load nbs-mcp-server.")
    return 0


def update(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update nbs-mcp-server and refresh detected MCP client configs.")
    parser.add_argument("--skip-git", action="store_true", help="Skip git pull.")
    parser.add_argument("--skip-pip", action="store_true", help="Skip pip install -e .")
    parser.add_argument("--clients", default="detected", help="Clients to configure: detected, all, or comma-separated names.")
    args = parser.parse_args(argv)

    if not args.skip_git:
        git_pull()
    if not args.skip_pip:
        install_package()
    configure_clients(["--clients", args.clients])
    print("Update complete. Restart your AI client to load the new version.")
    return 0


def uninstall(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove nbs-mcp-server from detected MCP clients and optionally uninstall the Python package.")
    parser.add_argument("--clients", default="detected", help="Clients to remove from: detected, all, or comma-separated names.")
    parser.add_argument("--keep-package", action="store_true", help="Only remove client configs; keep the Python package installed.")
    parser.add_argument("--yes", "-y", action="store_true", help="Do not ask before uninstalling the Python package.")
    args = parser.parse_args(argv)

    configure_clients(["--clients", args.clients, "--remove"])
    if args.keep_package:
        print("Client configs removed. Python package kept installed.")
        return 0
    if not args.yes:
        answer = input("Uninstall Python package nbs-mcp-server too? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Client configs removed. Python package kept installed.")
            return 0
    run([sys.executable, "-m", "pip", "uninstall", "-y", "nbs-mcp-server"], check=False)
    print("Uninstall complete. Restart your AI client.")
    return 0

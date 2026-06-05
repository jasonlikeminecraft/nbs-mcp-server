from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def assert_ok(result: dict, label: str) -> dict:
    if not result.get("ok"):
        raise AssertionError(f"{label} failed: {result}")
    return result["data"]


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        os.environ["NBS_MCP_ALLOWED_ROOT"] = str(root)

        from nbs_tools import (
            analyze_music,
            apply_note_patch,
            compare_nbs,
            export_markdown_summary,
            export_midi,
            export_note_table,
            generate_simple_song,
            import_midi,
            make_loop,
            read_nbs_notes,
            validate_nbs,
        )
        from configure_clients import main as configure_main

        base = root / "base.nbs"
        patched = root / "patched.nbs"
        midi = root / "base.mid"
        imported = root / "imported.nbs"
        csv_path = root / "notes.csv"
        report = root / "report.md"
        looped = root / "loop.nbs"

        assert_ok(generate_simple_song(str(base), bars=2), "generate_simple_song")
        assert_ok(validate_nbs(str(base)), "validate_nbs")
        assert_ok(read_nbs_notes(str(base), max_notes=8), "read_nbs_notes")
        assert_ok(analyze_music(str(base)), "analyze_music")
        assert_ok(export_note_table(str(base), str(csv_path)), "export_note_table")
        assert_ok(export_midi(str(base), str(midi)), "export_midi")
        assert_ok(import_midi(str(midi), str(imported)), "import_midi")
        assert_ok(
            apply_note_patch(
                str(base),
                str(patched),
                {
                    "add": [
                        {
                            "tick": 31,
                            "layer": 4,
                            "instrument": 0,
                            "key": 52,
                            "velocity": 88,
                            "panning": 100,
                            "pitch": 0,
                        }
                    ],
                    "metadata": {"song_name": "Smoke Patched"},
                },
            ),
            "apply_note_patch",
        )
        assert_ok(compare_nbs(str(base), str(patched)), "compare_nbs")
        assert_ok(make_loop(str(base), str(looped), repetitions=2), "make_loop")
        assert_ok(export_markdown_summary(str(base), str(report)), "export_markdown_summary")
        configure_status = configure_main(
            [
                "--clients",
                "claude_desktop",
                "--allowed-root",
                str(root),
                "--dry-run",
                "--create-missing",
            ]
        )
        if configure_status != 0:
            raise AssertionError("configure_clients dry-run failed")
        for script, expected_help in [
            ("install.py", "Install nbs-mcp-server"),
            ("update.py", "Update nbs-mcp-server"),
            ("uninstall.py", "Remove nbs-mcp-server"),
        ]:
            help_result = subprocess.run([sys.executable, str(PROJECT_ROOT / script), "--help"], check=False, capture_output=True, text=True)
            if help_result.returncode != 0 or expected_help not in help_result.stdout:
                raise AssertionError(f"{script} --help failed")
        default_config = subprocess.run([sys.executable, str(PROJECT_ROOT / "configure_clients.py"), "--clients", "codex", "--dry-run"], check=False, capture_output=True, text=True)
        if default_config.returncode != 0:
            raise AssertionError("configure_clients default dry-run failed")
        default_entry = json.loads(default_config.stdout)["entry"]
        if default_entry.get("env"):
            raise AssertionError("default installer entry should not set env")
        restricted_config = subprocess.run([sys.executable, str(PROJECT_ROOT / "configure_clients.py"), "--clients", "codex", "--dry-run", "--allowed-root", str(root)], check=False, capture_output=True, text=True)
        restricted_entry = json.loads(restricted_config.stdout)["entry"]
        if "NBS_MCP_ALLOWED_ROOT" not in restricted_entry.get("env", {}):
            raise AssertionError("--allowed-root should set NBS_MCP_ALLOWED_ROOT")

        expected = [base, patched, midi, imported, csv_path, report, looped]
        missing = [str(path) for path in expected if not path.exists()]
        if missing:
            raise AssertionError(f"expected files missing: {missing}")

    print("smoke test passed")


if __name__ == "__main__":
    main()

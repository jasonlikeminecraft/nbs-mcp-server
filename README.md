# nbs-mcp-server

`nbs-mcp-server` is a local Python MCP server that lets AI clients read, analyze, create, edit, convert, and export Minecraft Note Block Studio / Open Note Block Studio `.nbs` files.

It is designed for AI-assisted music workflows: inspect a song, reason about layers and harmony, apply structured edits, generate new material, export previews, and keep all results in machine-readable responses.

## Highlights

- Read and write `.nbs` files with a built-in modern NBS v5-compatible binary layer.
- Inspect metadata, notes, layers, tempo, key ranges, instruments, and validation issues.
- Edit notes, ticks, tempo, velocity, layers, crops, loops, patches, and arrangements.
- Analyze estimated key, chord regions, out-of-scale notes, melody layer, layer roles, and editable regions.
- Generate melodies, chord progressions, basslines, drum patterns, simple songs, loops, and reharmonized layers.
- Import/export CSV, JSON, MIDI, Markdown reports, and Minecraft function-style command notes.
- Auto-configure common MCP clients with one command.
- Optional filesystem restriction for locked-down local setups.

## Status

This is an initial public release. The core `.nbs` reader/writer and MCP tool surface are usable, but music analysis and MIDI import are intentionally lightweight and heuristic. Contributions and real-world `.nbs` compatibility reports are welcome.

## Requirements

- Python 3.10+
- An MCP-compatible client
- Dependencies listed in `pyproject.toml` / `requirements.txt`

## Installation

Clone the repository:

```bash
git clone https://github.com/jasonlikeminecraft/nbs-mcp-server.git
cd nbs-mcp-server
```

Install dependencies:

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

You can also install with:

```bash
pip install -r requirements.txt
```

Then run the zero-argument installer:

```bash
python install.py
```

The installer detects supported MCP clients that already have config files and adds `nbs-mcp-server` automatically. Existing config files are backed up before changes.

## Running

Run the MCP server with:

```bash
python server.py
```

Or, after editable install:

```bash
nbs-mcp-server
```

The server uses MCP stdio transport through `FastMCP`.

## MCP Client Configuration

Most users only need:

```bash
python install.py
```

After editable install, the same installer is available as:

```bash
nbs-mcp-install
```

For advanced users, the configurable installer is:

```bash
python configure_clients.py
```

Or:

```bash
nbs-mcp-configure
```

Supported client targets:

- Claude Desktop
- Cursor
- Windsurf
- Cline
- Roo Code
- Codex

Useful options:

```bash
python configure_clients.py --dry-run
python configure_clients.py --clients claude_desktop,cursor,codex
python configure_clients.py --list-clients
python configure_clients.py --remove --clients all
```

By default the installer configures detected clients and writes an `nbs` MCP server entry using the current Python executable and this repository's `server.py`. Use `--command-mode script` if you prefer the installed `nbs-mcp-server` console command. Use `--allowed-root` only if you want to restrict file access to one directory.

Manual configuration example:

```json
{
  "mcpServers": {
    "nbs": {
      "command": "python",
      "args": ["C:/path/to/nbs-mcp-server/server.py"]
    }
  }
}
```

If you installed the console script, you can use:

```json
{
  "mcpServers": {
    "nbs": {
      "command": "nbs-mcp-server"
    }
  }
}
```

Optional security mode:

```bash
python configure_clients.py --allowed-root "C:/path/to/your/nbs-workspace"
```

When `--allowed-root` is used, the installer writes `NBS_MCP_ALLOWED_ROOT` and the server only reads/writes files inside that directory. Without it, paths are resolved normally.

## Response Format

Every tool returns a stable envelope.

Success:

```json
{
  "ok": true,
  "data": {}
}
```

Failure:

```json
{
  "ok": false,
  "error": "reason",
  "details": {}
}
```

## Tool Overview

### Read and Analyze

- `get_nbs_info(path)` returns metadata, length, layers, tempo, note count, instruments, and key range.
- `read_nbs_notes(path, start_tick=0, end_tick=None, max_notes=500)` returns structured notes.
- `summarize_nbs(path)` returns an AI-readable song summary.
- `analyze_music(path)` estimates key, chords, out-of-scale notes, layer roles, and gaps.
- `describe_layer_roles(path)` classifies layers such as melody, harmony, bass, percussion, or empty.
- `get_editable_regions(path, min_region_ticks=16)` identifies active regions and gaps.
- `validate_nbs(path)` reports likely file and note issues.

### Create and Generate

- `create_blank_nbs(output_path, song_name="Untitled", author="", tempo=10.0, length=0, layer_count=1)`
- `create_nbs_from_notes(output_path, song_name, tempo, notes, author="")`
- `generate_simple_song(output_path, song_name="Generated Song", style="minecraft", key="C major", tempo=10.0, bars=8)`
- `generate_melody(output_path, song_name="Generated Melody", key="C major", tempo=10.0, bars=8, layer=0, density=1.0)`
- `generate_chord_progression(output_path, song_name="Generated Chords", key="C major", tempo=10.0, bars=8, layer=0)`
- `generate_bassline(output_path, song_name="Generated Bassline", key="C major", tempo=10.0, bars=8, layer=0)`
- `generate_drum_pattern(output_path, song_name="Generated Drums", tempo=10.0, bars=8, layer=0, pattern="basic")`

### Edit

- `add_notes(path, output_path, notes, overwrite=false)`
- `remove_notes(path, output_path, start_tick, end_tick, layers=None)`
- `transpose_nbs(path, output_path, semitones, layers=None, clamp=true)`
- `change_tempo(path, output_path, tempo)`
- `shift_ticks(path, output_path, offset, start_tick=0, layers=None)`
- `copy_range(path, output_path, start_tick, end_tick, target_tick, layers=None, overwrite=false)`
- `quantize_nbs(path, output_path, grid, layers=None)`
- `scale_velocity(path, output_path, factor, layers=None)`
- `fade_velocity(path, output_path, start_tick, end_tick, start_velocity, end_velocity, layers=None)`
- `humanize_nbs(path, output_path, velocity_amount=8, panning_amount=8, layers=None)`
- `set_layer_metadata(path, output_path, layer, name=None, volume=None, panning=None, lock=None)`
- `normalize_layers(path, output_path, remove_empty=true, compact=true)`
- `dedupe_notes(path, output_path)`
- `crop_nbs(path, output_path, start_tick, end_tick, shift_to_zero=true)`
- `repair_nbs(path, output_path, fix_ranges=true, remove_empty_layers=true)`

### AI Editing Workflows

- `suggest_edits(path, goal="improve loop", max_suggestions=20)` returns structured edit suggestions.
- `apply_note_patch(path, output_path, patch, overwrite=false)` applies `add`, `remove`, `update`, and `metadata` operations.
- `compare_nbs(base_path, other_path, max_items=500)` compares note and metadata changes.
- `reharmonize_nbs(path, output_path, key="C major", harmony_layer=None)` adds a harmony layer.
- `make_loop(path, output_path, start_tick=0, end_tick=None, repetitions=2)` repeats a source range.
- `arrange_song(path, output_path, arrangement=None)` builds a new arrangement from source sections.

### Import and Export

- `export_note_table(path, output_path, format="csv")`
- `import_note_table(input_path, output_path, song_name="Imported", tempo=10.0)`
- `export_midi(path, output_path, note_duration_ticks=1)`
- `import_midi(input_path, output_path, song_name="Imported MIDI", author="")`
- `render_preview(path, output_path, format="midi")`
- `export_markdown_summary(path, output_path)`
- `export_command_blocks(path, output_path, origin=None)`
- `split_layers(path, output_dir)`
- `merge_nbs(input_paths, output_path, mode="append_layers")`

`merge_nbs` supports `append_layers`, `overlay`, and `sequence`.

## Note Format

Tools that accept notes use this structure:

```json
{
  "tick": 0,
  "layer": 0,
  "instrument": 0,
  "key": 45,
  "velocity": 100,
  "panning": 100,
  "pitch": 0
}
```

Ranges:

- `tick`: `>= 0`
- `layer`: `>= 0`
- `instrument`: `0..255`
- `key`: `0..87`
- `velocity`: `0..100`
- `panning`: `0..200`
- `pitch`: signed 16-bit integer

## Examples

### Read a Song

Ask your MCP client:

```text
Use get_nbs_info with path "songs/demo.nbs", then summarize_nbs for the same file.
```

### Generate a Song

```text
Use generate_simple_song with output_path "songs/generated.nbs", key "D major", tempo 12, bars 8.
```

### Transpose

```text
Use transpose_nbs with path "songs/generated.nbs", output_path "songs/generated_up.nbs", semitones 2.
```

### Export CSV

```text
Use export_note_table with path "songs/generated.nbs", output_path "exports/generated.csv", format "csv".
```

### Export MIDI Preview

```text
Use export_midi with path "songs/generated.nbs", output_path "exports/generated.mid".
```

### Analyze Music

```text
Use analyze_music with path "songs/generated.nbs".
```

### Apply a Patch

```json
{
  "path": "songs/generated.nbs",
  "output_path": "songs/generated_patched.nbs",
  "patch": {
    "add": [
      {
        "tick": 32,
        "layer": 0,
        "instrument": 0,
        "key": 52,
        "velocity": 90,
        "panning": 100,
        "pitch": 0
      }
    ],
    "metadata": {
      "song_name": "Patched Song"
    }
  }
}
```

### Make a Loop

```text
Use make_loop with path "songs/generated.nbs", output_path "songs/loop.nbs", start_tick 0, repetitions 4.
```

## Development

Install in editable mode:

```bash
pip install -e .
```

Run checks:

```bash
python -m compileall .
python tests/smoke_test.py
```

The smoke test creates temporary `.nbs`, `.mid`, `.csv`, and `.md` files and removes them automatically.

## Project Structure

- `server.py` registers all MCP tools.
- `nbs_core.py` contains the stable `.nbs` compatibility layer.
- `nbs_tools.py` implements MCP tool behavior.
- `music_utils.py` contains music-analysis and generation helpers.
- `midi_utils.py` contains minimal MIDI read/write helpers.
- `schemas.py` contains Pydantic models and response envelopes.
- `tests/smoke_test.py` verifies the main public workflow.

## Compatibility Notes

The project includes a self-contained modern NBS v5 binary reader/writer. `pynbs` remains a dependency because future versions may choose to delegate more format details to that library. Keep tool code depending on the wrapper functions in `nbs_core.py`:

- `load_nbs(path)`
- `save_nbs(song, path)`
- `iter_notes(song)`
- `get_note(song, tick, layer)`
- `set_note(song, note, overwrite=False)`
- `delete_note(song, tick, layer)`
- `get_song_info(song)`

## Security

The server is intended to run locally. By default it can access paths supplied by your MCP client. For locked-down setups, configure with `--allowed-root` to restrict access to one directory.

## Publishing Checklist

Before publishing your GitHub repository:

- Confirm the MIT license is the license you want.
- Run `python tests/smoke_test.py`.
- Add screenshots, sample `.nbs` files, or demo videos if you want a richer project page.

## License

MIT. See [LICENSE](LICENSE).

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from midi_utils import read_midi, write_midi
from nbs_core import (
    NbsLayer,
    NbsSong,
    create_song,
    delete_note,
    get_note,
    get_song_info,
    iter_notes,
    load_nbs,
    resolve_safe_path,
    save_nbs,
    set_note,
)
from music_utils import (
    CHORD_PROGRESSIONS,
    analyze_harmony,
    classify_layer_roles,
    find_gaps,
    find_likely_melody_layer,
    is_pitched_instrument,
    make_scale_key,
    nearest_grid,
    note_to_dict,
    parse_key_signature,
)
from schemas import NbsNote, OperationResult, ValidationIssue, dump_model


def tool_result(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return OperationResult.success(func(*args, **kwargs))
        except Exception as exc:
            return OperationResult.failure(str(exc), {"tool": func.__name__, "type": exc.__class__.__name__})

    return wrapper


def _parse_note(raw: dict[str, Any]) -> NbsNote:
    return NbsNote(
        tick=int(raw["tick"]),
        layer=int(raw["layer"]),
        instrument=int(raw.get("instrument", 0)),
        key=int(raw["key"]),
        velocity=int(raw.get("velocity", 100)),
        panning=int(raw.get("panning", 100)),
        pitch=int(raw.get("pitch", 0)),
    )


def _parse_notes(notes: list[dict[str, Any]]) -> list[NbsNote]:
    parsed = [_parse_note(note) for note in notes]
    return sorted(parsed, key=lambda item: (item.tick, item.layer))


def _layer_filter(layer: int, layers: list[int] | None) -> bool:
    return layers is None or layer in set(layers)


def _save_with_note_rebuild(song: NbsSong, notes: list[NbsNote], output_path: str) -> str:
    song.notes = {(note.tick, note.layer): note for note in notes}
    return save_nbs(song, output_path)


def _copy_note(note: NbsNote, **updates: Any) -> NbsNote:
    return note.model_copy(update=updates) if hasattr(note, "model_copy") else note.copy(update=updates)


def _append_or_place(song: NbsSong, note: NbsNote, overwrite: bool = False) -> tuple[bool, int]:
    if set_note(song, note, overwrite=overwrite):
        return True, note.layer
    layer = note.layer + 1
    while get_note(song, note.tick, layer):
        layer += 1
    set_note(song, _copy_note(note, layer=layer), overwrite=True)
    return True, layer


def _note_identity(note: NbsNote) -> tuple[int, int]:
    return note.tick, note.layer


@tool_result
def get_nbs_info(path: str) -> dict[str, Any]:
    song = load_nbs(path)
    return get_song_info(song)


@tool_result
def read_nbs_notes(path: str, start_tick: int = 0, end_tick: int | None = None, max_notes: int = 500) -> dict[str, Any]:
    if start_tick < 0:
        raise ValueError("start_tick must be >= 0")
    if end_tick is not None and end_tick < start_tick:
        raise ValueError("end_tick must be >= start_tick")
    if max_notes <= 0:
        raise ValueError("max_notes must be > 0")
    song = load_nbs(path)
    selected = [
        note
        for note in iter_notes(song)
        if note.tick >= start_tick and (end_tick is None or note.tick <= end_tick)
    ]
    truncated = len(selected) > max_notes
    return {
        "notes": [note_to_dict(note) for note in selected[:max_notes]],
        "count": min(len(selected), max_notes),
        "total_matching": len(selected),
        "truncated": truncated,
    }


@tool_result
def summarize_nbs(path: str) -> dict[str, Any]:
    song = load_nbs(path)
    notes = iter_notes(song)
    by_layer: dict[int, list[NbsNote]] = defaultdict(list)
    for note in notes:
        by_layer[note.layer].append(note)
    layer_summaries = []
    for layer in range(song.layer_count):
        layer_notes = by_layer.get(layer, [])
        keys = [note.key for note in layer_notes]
        layer_summaries.append(
            {
                "layer": layer,
                "name": song.layers.get(layer).name if layer in song.layers else "",
                "note_count": len(layer_notes),
                "instruments": sorted({note.instrument for note in layer_notes}),
                "min_key": min(keys) if keys else None,
                "max_key": max(keys) if keys else None,
                "active_tick_start": min((note.tick for note in layer_notes), default=None),
                "active_tick_end": max((note.tick for note in layer_notes), default=None),
            }
        )
    gaps = find_gaps(notes, song.length)
    return {
        "metadata": get_song_info(song),
        "structure": {
            "active_start_tick": min((note.tick for note in notes), default=None),
            "active_end_tick": max((note.tick for note in notes), default=None),
            "distinct_active_ticks": len({note.tick for note in notes}),
            "obvious_gaps": gaps[:20],
        },
        "layers": layer_summaries,
        "likely_melody_layer": find_likely_melody_layer(notes),
        "possibly_loopable": bool(notes) and (not gaps or gaps[-1]["end_tick"] < song.length - 1),
        "tempo_and_length": {
            "tempo": song.tempo,
            "tps": song.tempo,
            "length_ticks": song.length,
            "duration_seconds": round(song.length / song.tempo, 3) if song.tempo else None,
        },
    }


@tool_result
def create_blank_nbs(
    output_path: str,
    song_name: str = "Untitled",
    author: str = "",
    tempo: float = 10.0,
    length: int = 0,
    layer_count: int = 1,
) -> dict[str, Any]:
    song = create_song(song_name=song_name, author=author, tempo=tempo, length=length, layer_count=layer_count)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "info": get_song_info(song)}


@tool_result
def create_nbs_from_notes(
    output_path: str,
    song_name: str,
    tempo: float,
    notes: list[dict[str, Any]],
    author: str = "",
) -> dict[str, Any]:
    parsed = _parse_notes(notes)
    song = create_song(song_name=song_name, author=author, tempo=tempo, length=0, layer_count=1)
    conflicts = []
    for note in parsed:
        if not set_note(song, note, overwrite=False):
            conflicts.append({"tick": note.tick, "layer": note.layer})
    if conflicts:
        raise ValueError(f"duplicate note positions: {conflicts[:5]}")
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(parsed), "info": get_song_info(song)}


@tool_result
def add_notes(path: str, output_path: str, notes: list[dict[str, Any]], overwrite: bool = False) -> dict[str, Any]:
    song = load_nbs(path)
    added = 0
    conflicts = []
    for note in _parse_notes(notes):
        existing = get_note(song, note.tick, note.layer)
        if existing and not overwrite:
            conflicts.append({"tick": note.tick, "layer": note.layer, "existing": note_to_dict(existing), "incoming": note_to_dict(note)})
            continue
        set_note(song, note, overwrite=True)
        added += 1
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "added_count": added, "conflict_count": len(conflicts), "conflicts": conflicts}


@tool_result
def remove_notes(path: str, output_path: str, start_tick: int, end_tick: int, layers: list[int] | None = None) -> dict[str, Any]:
    if start_tick < 0 or end_tick < start_tick:
        raise ValueError("invalid tick range")
    song = load_nbs(path)
    targets = [
        note
        for note in iter_notes(song)
        if start_tick <= note.tick <= end_tick and _layer_filter(note.layer, layers)
    ]
    for note in targets:
        delete_note(song, note.tick, note.layer)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "removed_count": len(targets)}


@tool_result
def transpose_nbs(path: str, output_path: str, semitones: int, layers: list[int] | None = None, clamp: bool = True) -> dict[str, Any]:
    song = load_nbs(path)
    changed = skipped = clamped = 0
    updated = []
    for note in iter_notes(song):
        if not _layer_filter(note.layer, layers) or not is_pitched_instrument(note.instrument):
            updated.append(note)
            skipped += 1 if _layer_filter(note.layer, layers) else 0
            continue
        new_key = note.key + semitones
        if new_key < 0 or new_key > 87:
            if not clamp:
                updated.append(note)
                skipped += 1
                continue
            new_key = max(0, min(87, new_key))
            clamped += 1
        updated.append(note.model_copy(update={"key": new_key}) if hasattr(note, "model_copy") else note.copy(update={"key": new_key}))
        changed += 1
    saved = _save_with_note_rebuild(song, updated, output_path)
    return {"output_path": saved, "changed_count": changed, "skipped_count": skipped, "clamped_count": clamped}


@tool_result
def change_tempo(path: str, output_path: str, tempo: float) -> dict[str, Any]:
    if tempo <= 0:
        raise ValueError("tempo must be > 0")
    song = load_nbs(path)
    old_tempo = song.tempo
    song.tempo = tempo
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "old_tempo": old_tempo, "new_tempo": tempo}


@tool_result
def shift_ticks(path: str, output_path: str, offset: int, start_tick: int = 0, layers: list[int] | None = None) -> dict[str, Any]:
    song = load_nbs(path)
    base_notes = iter_notes(song)
    moving_positions = {(note.tick, note.layer) for note in base_notes if note.tick >= start_tick and _layer_filter(note.layer, layers)}
    occupied = {(note.tick, note.layer) for note in base_notes if (note.tick, note.layer) not in moving_positions}
    rebuilt = [note for note in base_notes if (note.tick, note.layer) not in moving_positions]
    conflicts = []
    moved = skipped = 0
    for note in base_notes:
        if (note.tick, note.layer) not in moving_positions:
            continue
        new_tick = note.tick + offset
        if new_tick < 0:
            skipped += 1
            continue
        if (new_tick, note.layer) in occupied:
            conflicts.append({"source_tick": note.tick, "target_tick": new_tick, "layer": note.layer})
            skipped += 1
            continue
        occupied.add((new_tick, note.layer))
        rebuilt.append(note.model_copy(update={"tick": new_tick}) if hasattr(note, "model_copy") else note.copy(update={"tick": new_tick}))
        moved += 1
    saved = _save_with_note_rebuild(song, rebuilt, output_path)
    return {"output_path": saved, "moved_count": moved, "conflict_count": len(conflicts), "skipped_count": skipped, "conflicts": conflicts}


@tool_result
def copy_range(
    path: str,
    output_path: str,
    start_tick: int,
    end_tick: int,
    target_tick: int,
    layers: list[int] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if start_tick < 0 or end_tick < start_tick or target_tick < 0:
        raise ValueError("invalid tick range")
    song = load_nbs(path)
    copied = 0
    conflicts = []
    for note in iter_notes(song):
        if not (start_tick <= note.tick <= end_tick and _layer_filter(note.layer, layers)):
            continue
        new_tick = target_tick + (note.tick - start_tick)
        new_note = note.model_copy(update={"tick": new_tick}) if hasattr(note, "model_copy") else note.copy(update={"tick": new_tick})
        existing = get_note(song, new_note.tick, new_note.layer)
        if existing and not overwrite:
            conflicts.append({"tick": new_note.tick, "layer": new_note.layer, "existing": note_to_dict(existing)})
            continue
        set_note(song, new_note, overwrite=True)
        copied += 1
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "copied_count": copied, "conflict_count": len(conflicts), "conflicts": conflicts}


@tool_result
def quantize_nbs(path: str, output_path: str, grid: int, layers: list[int] | None = None) -> dict[str, Any]:
    if grid <= 0:
        raise ValueError("grid must be > 0")
    song = load_nbs(path)
    rebuilt = []
    occupied: set[tuple[int, int]] = set()
    moved = conflicts = 0
    for note in iter_notes(song):
        new_tick = nearest_grid(note.tick, grid) if _layer_filter(note.layer, layers) else note.tick
        if new_tick != note.tick:
            moved += 1
        while (new_tick, note.layer) in occupied:
            new_tick += grid
            conflicts += 1
        occupied.add((new_tick, note.layer))
        rebuilt.append(note.model_copy(update={"tick": new_tick}) if hasattr(note, "model_copy") else note.copy(update={"tick": new_tick}))
    saved = _save_with_note_rebuild(song, rebuilt, output_path)
    return {"output_path": saved, "moved_count": moved, "conflict_count": conflicts}


@tool_result
def export_note_table(path: str, output_path: str, format: str = "csv") -> dict[str, Any]:
    song = load_nbs(path)
    resolved = resolve_safe_path(output_path, must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    rows = [note_to_dict(note) for note in iter_notes(song)]
    fmt = format.lower()
    if fmt == "csv":
        with resolved.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["tick", "layer", "instrument", "key", "velocity", "panning", "pitch"])
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "json":
        resolved.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        raise ValueError("format must be csv or json")
    return {"output_path": str(resolved), "format": fmt, "note_count": len(rows)}


@tool_result
def import_note_table(input_path: str, output_path: str, song_name: str = "Imported", tempo: float = 10.0) -> dict[str, Any]:
    resolved = resolve_safe_path(input_path, must_exist=True)
    if resolved.suffix.lower() == ".json":
        rows = json.loads(resolved.read_text(encoding="utf-8"))
    else:
        with resolved.open("r", newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
    parsed = [note_to_dict(note) for note in _parse_notes(rows)]
    return create_nbs_from_notes(output_path=output_path, song_name=song_name, tempo=tempo, notes=parsed)["data"]


@tool_result
def split_layers(path: str, output_dir: str) -> dict[str, Any]:
    song = load_nbs(path)
    out_dir = resolve_safe_path(output_dir, must_exist=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    source_name = Path(path).stem
    for layer in sorted({note.layer for note in iter_notes(song)}):
        layer_song = create_song(
            song_name=f"{song.song_name or source_name} - Layer {layer}",
            author=song.author,
            tempo=song.tempo,
            length=song.length,
            layer_count=1,
        )
        layer_song.description = song.description
        layer_song.layers[0] = song.layers.get(layer, NbsLayer())
        for note in iter_notes(song):
            if note.layer == layer:
                set_note(layer_song, note.model_copy(update={"layer": 0}) if hasattr(note, "model_copy") else note.copy(update={"layer": 0}), overwrite=True)
        output_path = out_dir / f"{source_name}_layer_{layer}.nbs"
        outputs.append({"source_layer": layer, "output_path": save_nbs(layer_song, str(output_path)), "note_count": len(layer_song.notes)})
    return {"output_dir": str(out_dir), "files": outputs}


@tool_result
def merge_nbs(input_paths: list[str], output_path: str, mode: str = "append_layers") -> dict[str, Any]:
    if not input_paths:
        raise ValueError("input_paths must not be empty")
    songs = [load_nbs(path) for path in input_paths]
    merged = create_song(song_name="Merged NBS", author="", tempo=songs[0].tempo, length=0, layer_count=0)
    conflicts = []
    if mode == "append_layers":
        layer_offset = 0
        for song in songs:
            for layer, metadata in song.layers.items():
                merged.layers[layer + layer_offset] = metadata
            for note in iter_notes(song):
                set_note(merged, note.model_copy(update={"layer": note.layer + layer_offset}) if hasattr(note, "model_copy") else note.copy(update={"layer": note.layer + layer_offset}), overwrite=True)
            layer_offset += song.layer_count
    elif mode == "overlay":
        for song in songs:
            for note in iter_notes(song):
                target = note
                while get_note(merged, target.tick, target.layer):
                    conflicts.append({"tick": target.tick, "original_layer": target.layer})
                    target = target.model_copy(update={"layer": target.layer + 1}) if hasattr(target, "model_copy") else target.copy(update={"layer": target.layer + 1})
                set_note(merged, target, overwrite=True)
    elif mode == "sequence":
        tick_offset = 0
        for song in songs:
            for note in iter_notes(song):
                set_note(merged, note.model_copy(update={"tick": note.tick + tick_offset}) if hasattr(note, "model_copy") else note.copy(update={"tick": note.tick + tick_offset}), overwrite=True)
            tick_offset += song.length
    else:
        raise ValueError("mode must be append_layers, overlay, or sequence")
    saved = save_nbs(merged, output_path)
    return {"output_path": saved, "mode": mode, "note_count": len(merged.notes), "conflict_count": len(conflicts), "conflicts": conflicts[:200]}


@tool_result
def validate_nbs(path: str) -> dict[str, Any]:
    issues: list[ValidationIssue] = []
    try:
        song = load_nbs(path)
    except Exception as exc:
        issue = ValidationIssue(severity="error", code="unreadable", message=str(exc), details={"type": exc.__class__.__name__})
        return {"valid": False, "issues": [dump_model(issue)]}
    notes = iter_notes(song)
    for note in notes:
        if not 0 <= note.key <= 87:
            issues.append(ValidationIssue(severity="error", code="key_out_of_range", message="note key is outside 0-87", details=note_to_dict(note)))
        if not 0 <= note.velocity <= 100:
            issues.append(ValidationIssue(severity="error", code="velocity_out_of_range", message="velocity is outside 0-100", details=note_to_dict(note)))
        if not 0 <= note.panning <= 200:
            issues.append(ValidationIssue(severity="error", code="panning_out_of_range", message="panning is outside 0-200", details=note_to_dict(note)))
        if note.layer >= max(song.layer_count, 1) + 32:
            issues.append(ValidationIssue(severity="warning", code="layer_unusually_high", message="note layer is much higher than declared layer count", details=note_to_dict(note)))
    active_layers = {note.layer for note in notes}
    empty_layers = [layer for layer in range(song.layer_count) if layer not in active_layers]
    if empty_layers:
        issues.append(ValidationIssue(severity="warning", code="empty_layers", message="song contains empty layers", details={"layers": empty_layers[:200], "count": len(empty_layers)}))
    counts = Counter((note.tick, note.layer) for note in notes)
    duplicates = [{"tick": tick, "layer": layer, "count": count} for (tick, layer), count in counts.items() if count > 1]
    if len(duplicates) > 10:
        issues.append(ValidationIssue(severity="warning", code="many_duplicate_positions", message="song contains many duplicate note positions", details={"duplicates": duplicates[:200], "count": len(duplicates)}))
    return {
        "valid": not any(issue.severity == "error" for issue in issues),
        "issue_count": len(issues),
        "issues": [dump_model(issue) for issue in issues],
        "info": get_song_info(song),
    }


@tool_result
def generate_simple_song(
    output_path: str,
    song_name: str = "Generated Song",
    style: str = "minecraft",
    key: str = "C major",
    tempo: float = 10.0,
    bars: int = 8,
) -> dict[str, Any]:
    if bars <= 0:
        raise ValueError("bars must be > 0")
    root, scale, mode = parse_key_signature(key)
    ticks_per_beat = 4
    beats_per_bar = 4
    length = bars * beats_per_bar * ticks_per_beat
    song = create_song(song_name=song_name, author="nbs-mcp-server", tempo=tempo, length=length, layer_count=4)
    song.description = f"Generated deterministic {style} example in {key}."
    song.layers[0].name = "Melody"
    song.layers[1].name = "Harmony"
    song.layers[2].name = "Bass"
    song.layers[3].name = "Percussion"
    progression = CHORD_PROGRESSIONS["minor" if mode == "minor" else "major"]
    melody_pattern = [0, 2, 4, 5, 4, 2, 1, 0]
    note_count = 0
    for bar in range(bars):
        bar_tick = bar * beats_per_bar * ticks_per_beat
        chord_degree = progression[bar % len(progression)]
        for beat in range(beats_per_bar):
            tick = bar_tick + beat * ticks_per_beat
            degree = melody_pattern[(bar * beats_per_bar + beat) % len(melody_pattern)] + chord_degree
            set_note(song, NbsNote(tick=tick, layer=0, instrument=0, key=make_scale_key(root, degree, 45, scale), velocity=92, panning=100, pitch=0), overwrite=True)
            note_count += 1
        for chord_index, chord_step in enumerate([chord_degree, chord_degree + 2, chord_degree + 4]):
            harmony_tick = bar_tick + chord_index * ticks_per_beat
            set_note(song, NbsNote(tick=harmony_tick, layer=1, instrument=6, key=make_scale_key(root, chord_step, 33, scale), velocity=70, panning=100, pitch=0), overwrite=True)
            note_count += 1
        set_note(song, NbsNote(tick=bar_tick, layer=2, instrument=1, key=make_scale_key(root, chord_degree, 21, scale), velocity=85, panning=100, pitch=0), overwrite=True)
        note_count += 1
        for beat in range(beats_per_bar):
            tick = bar_tick + beat * ticks_per_beat
            drum_key = 33 if beat in {0, 2} else 39
            set_note(song, NbsNote(tick=tick, layer=3, instrument=2, key=drum_key, velocity=80, panning=100, pitch=0), overwrite=True)
            note_count += 1
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(song.notes), "planned_note_count": note_count, "info": get_song_info(song)}


@tool_result
def export_midi(path: str, output_path: str, note_duration_ticks: int = 1) -> dict[str, Any]:
    song = load_nbs(path)
    resolved = resolve_safe_path(output_path, must_exist=False)
    layer_names = {layer: metadata.name for layer, metadata in song.layers.items()}
    write_midi(resolved, iter_notes(song), song.tempo, layer_names, note_duration_ticks=note_duration_ticks)
    return {"output_path": str(resolved), "note_count": len(song.notes), "tempo": song.tempo}


@tool_result
def import_midi(input_path: str, output_path: str, song_name: str = "Imported MIDI", author: str = "") -> dict[str, Any]:
    resolved = resolve_safe_path(input_path, must_exist=True)
    rows, tempo = read_midi(resolved)
    return create_nbs_from_notes(output_path=output_path, song_name=song_name, tempo=tempo, notes=rows, author=author)["data"]


@tool_result
def render_preview(path: str, output_path: str, format: str = "midi") -> dict[str, Any]:
    fmt = format.lower()
    if fmt not in {"midi", "mid"}:
        raise ValueError("render_preview currently supports format='midi'")
    return export_midi(path=path, output_path=output_path)["data"]


@tool_result
def analyze_music(path: str) -> dict[str, Any]:
    song = load_nbs(path)
    notes = iter_notes(song)
    harmony = analyze_harmony(notes)
    return {
        "info": get_song_info(song),
        "harmony": harmony,
        "layer_roles": classify_layer_roles(notes, song.layer_count),
        "likely_melody_layer": find_likely_melody_layer(notes),
        "gaps": find_gaps(notes, song.length),
    }


@tool_result
def describe_layer_roles(path: str) -> dict[str, Any]:
    song = load_nbs(path)
    return {"layers": classify_layer_roles(iter_notes(song), song.layer_count)}


@tool_result
def compare_nbs(base_path: str, other_path: str, max_items: int = 500) -> dict[str, Any]:
    if max_items <= 0:
        raise ValueError("max_items must be > 0")
    base = load_nbs(base_path)
    other = load_nbs(other_path)
    base_notes = {_note_identity(note): note for note in iter_notes(base)}
    other_notes = {_note_identity(note): note for note in iter_notes(other)}
    added = []
    removed = []
    changed = []
    for position, note in other_notes.items():
        if position not in base_notes:
            added.append(note_to_dict(note))
        elif note_to_dict(base_notes[position]) != note_to_dict(note):
            changed.append({"position": {"tick": position[0], "layer": position[1]}, "before": note_to_dict(base_notes[position]), "after": note_to_dict(note)})
    for position, note in base_notes.items():
        if position not in other_notes:
            removed.append(note_to_dict(note))
    metadata_changes = {
        key: {"base": get_song_info(base)[key], "other": get_song_info(other)[key]}
        for key in ["song_name", "author", "length", "layer_count", "tempo", "time_signature"]
        if get_song_info(base)[key] != get_song_info(other)[key]
    }
    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "added": added[:max_items],
        "removed": removed[:max_items],
        "changed": changed[:max_items],
        "metadata_changes": metadata_changes,
        "truncated": any(len(items) > max_items for items in [added, removed, changed]),
    }


@tool_result
def apply_note_patch(path: str, output_path: str, patch: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    song = load_nbs(path)
    added = updated = removed = conflicts = 0
    conflict_items = []
    for raw in patch.get("remove", []):
        if delete_note(song, int(raw["tick"]), int(raw["layer"])):
            removed += 1
    for raw in patch.get("update", []):
        old_tick = int(raw.get("old_tick", raw.get("tick")))
        old_layer = int(raw.get("old_layer", raw.get("layer")))
        existing = get_note(song, old_tick, old_layer)
        if not existing:
            conflicts += 1
            conflict_items.append({"operation": "update", "reason": "source note not found", "tick": old_tick, "layer": old_layer})
            continue
        delete_note(song, old_tick, old_layer)
        data = note_to_dict(existing)
        data.update(raw.get("note", raw))
        data.pop("old_tick", None)
        data.pop("old_layer", None)
        note = _parse_note(data)
        if not set_note(song, note, overwrite=overwrite):
            set_note(song, existing, overwrite=True)
            conflicts += 1
            conflict_items.append({"operation": "update", "reason": "target occupied", "tick": note.tick, "layer": note.layer})
            continue
        updated += 1
    for raw in patch.get("add", []):
        note = _parse_note(raw)
        if not set_note(song, note, overwrite=overwrite):
            conflicts += 1
            conflict_items.append({"operation": "add", "reason": "target occupied", "tick": note.tick, "layer": note.layer})
            continue
        added += 1
    metadata = patch.get("metadata", {})
    for key in ["song_name", "author", "original_author", "description", "tempo", "time_signature"]:
        if key in metadata:
            setattr(song, key, metadata[key])
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "added_count": added, "updated_count": updated, "removed_count": removed, "conflict_count": conflicts, "conflicts": conflict_items}


@tool_result
def suggest_edits(path: str, goal: str = "improve loop", max_suggestions: int = 20) -> dict[str, Any]:
    song = load_nbs(path)
    notes = iter_notes(song)
    suggestions = []
    gaps = find_gaps(notes, song.length)
    roles = classify_layer_roles(notes, song.layer_count)
    if "loop" in goal.lower() and gaps:
        suggestions.append({"type": "copy_range", "reason": "song has empty regions that can be filled for a steadier loop", "parameters": {"start_tick": 0, "end_tick": min(song.length - 1, 31), "target_tick": max(0, song.length)}})
    if "brighter" in goal.lower() or "happy" in goal.lower() or "欢快" in goal:
        suggestions.append({"type": "transpose_nbs", "reason": "raising pitched notes can make the piece feel brighter", "parameters": {"semitones": 2, "clamp": True}})
    if any(role["role"] == "empty" for role in roles):
        suggestions.append({"type": "normalize_layers", "reason": "empty layers can be removed to simplify editing", "parameters": {"remove_empty": True}})
    harmony = analyze_harmony(notes)
    if harmony.get("out_of_scale_count", 0):
        suggestions.append({"type": "repair_nbs", "reason": "some notes appear outside the estimated scale", "parameters": {"fix_out_of_range": True}})
    return {"goal": goal, "suggestions": suggestions[:max_suggestions], "analysis": {"roles": roles, "harmony": harmony}}


@tool_result
def set_layer_metadata(path: str, output_path: str, layer: int, name: str | None = None, volume: int | None = None, panning: int | None = None, lock: int | None = None) -> dict[str, Any]:
    if layer < 0:
        raise ValueError("layer must be >= 0")
    song = load_nbs(path)
    while song.layer_count <= layer:
        song.layers[song.layer_count] = NbsLayer()
        song.layer_count += 1
    metadata = song.layers.get(layer, NbsLayer())
    if name is not None:
        metadata.name = name
    if volume is not None:
        metadata.volume = max(0, min(100, int(volume)))
    if panning is not None:
        metadata.panning = max(0, min(200, int(panning)))
    if lock is not None:
        metadata.lock = 1 if lock else 0
    song.layers[layer] = metadata
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "layer": layer, "metadata": metadata.__dict__}


@tool_result
def scale_velocity(path: str, output_path: str, factor: float, layers: list[int] | None = None) -> dict[str, Any]:
    if factor < 0:
        raise ValueError("factor must be >= 0")
    song = load_nbs(path)
    changed = 0
    updated = []
    for note in iter_notes(song):
        if _layer_filter(note.layer, layers):
            updated.append(_copy_note(note, velocity=max(0, min(100, round(note.velocity * factor)))))
            changed += 1
        else:
            updated.append(note)
    saved = _save_with_note_rebuild(song, updated, output_path)
    return {"output_path": saved, "changed_count": changed}


@tool_result
def fade_velocity(path: str, output_path: str, start_tick: int, end_tick: int, start_velocity: int, end_velocity: int, layers: list[int] | None = None) -> dict[str, Any]:
    if end_tick < start_tick:
        raise ValueError("end_tick must be >= start_tick")
    song = load_nbs(path)
    span = max(1, end_tick - start_tick)
    changed = 0
    updated = []
    for note in iter_notes(song):
        if start_tick <= note.tick <= end_tick and _layer_filter(note.layer, layers):
            ratio = (note.tick - start_tick) / span
            velocity = round(start_velocity + (end_velocity - start_velocity) * ratio)
            updated.append(_copy_note(note, velocity=max(0, min(100, velocity))))
            changed += 1
        else:
            updated.append(note)
    saved = _save_with_note_rebuild(song, updated, output_path)
    return {"output_path": saved, "changed_count": changed}


@tool_result
def humanize_nbs(path: str, output_path: str, velocity_amount: int = 8, panning_amount: int = 8, layers: list[int] | None = None) -> dict[str, Any]:
    song = load_nbs(path)
    changed = 0
    updated = []
    for index, note in enumerate(iter_notes(song)):
        if _layer_filter(note.layer, layers):
            velocity_delta = ((note.tick + note.layer * 3 + index) % (velocity_amount * 2 + 1)) - velocity_amount
            panning_delta = ((note.tick * 2 + note.layer + index) % (panning_amount * 2 + 1)) - panning_amount
            updated.append(_copy_note(note, velocity=max(0, min(100, note.velocity + velocity_delta)), panning=max(0, min(200, note.panning + panning_delta))))
            changed += 1
        else:
            updated.append(note)
    saved = _save_with_note_rebuild(song, updated, output_path)
    return {"output_path": saved, "changed_count": changed}


@tool_result
def normalize_layers(path: str, output_path: str, remove_empty: bool = True, compact: bool = True) -> dict[str, Any]:
    song = load_nbs(path)
    old_layer_count = song.layer_count
    active_layers = sorted({note.layer for note in iter_notes(song)})
    if not compact:
        saved = save_nbs(song, output_path)
        return {"output_path": saved, "layer_map": {layer: layer for layer in range(song.layer_count)}, "removed_empty_count": 0}
    source_layers = active_layers if remove_empty else list(range(song.layer_count))
    layer_map = {old: new for new, old in enumerate(source_layers)}
    updated = [_copy_note(note, layer=layer_map[note.layer]) for note in iter_notes(song) if note.layer in layer_map]
    new_layers = {}
    for old, new in layer_map.items():
        new_layers[new] = song.layers.get(old, NbsLayer())
    song.layers = new_layers
    song.layer_count = len(new_layers)
    saved = _save_with_note_rebuild(song, updated, output_path)
    return {"output_path": saved, "layer_map": layer_map, "removed_empty_count": max(0, old_layer_count - len(new_layers))}


@tool_result
def dedupe_notes(path: str, output_path: str) -> dict[str, Any]:
    song = load_nbs(path)
    before = len(iter_notes(song))
    song.notes = {(note.tick, note.layer): note for note in iter_notes(song)}
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "removed_count": before - len(song.notes)}


@tool_result
def crop_nbs(path: str, output_path: str, start_tick: int, end_tick: int, shift_to_zero: bool = True) -> dict[str, Any]:
    if start_tick < 0 or end_tick < start_tick:
        raise ValueError("invalid tick range")
    song = load_nbs(path)
    cropped = []
    for note in iter_notes(song):
        if start_tick <= note.tick <= end_tick:
            cropped.append(_copy_note(note, tick=note.tick - start_tick if shift_to_zero else note.tick))
    song.length = end_tick - start_tick + 1 if shift_to_zero else end_tick + 1
    saved = _save_with_note_rebuild(song, cropped, output_path)
    return {"output_path": saved, "note_count": len(cropped), "length": song.length}


@tool_result
def repair_nbs(path: str, output_path: str, fix_ranges: bool = True, remove_empty_layers: bool = True) -> dict[str, Any]:
    song = load_nbs(path)
    changed = 0
    updated = []
    for note in iter_notes(song):
        data = note_to_dict(note)
        if fix_ranges:
            fixed = {
                "key": max(0, min(87, note.key)),
                "velocity": max(0, min(100, note.velocity)),
                "panning": max(0, min(200, note.panning)),
                "instrument": max(0, min(255, note.instrument)),
            }
            if any(data[key] != fixed[key] for key in fixed):
                data.update(fixed)
                changed += 1
        updated.append(_parse_note(data))
    _save_with_note_rebuild(song, updated, output_path)
    if remove_empty_layers:
        return normalize_layers(output_path, output_path)["data"]
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "changed_count": changed}


@tool_result
def get_editable_regions(path: str, min_region_ticks: int = 16) -> dict[str, Any]:
    song = load_nbs(path)
    notes = iter_notes(song)
    active_ticks = sorted({note.tick for note in notes})
    if not active_ticks:
        return {"regions": [], "gaps": [{"start_tick": 0, "end_tick": song.length, "duration": song.length}]}
    regions = []
    start = previous = active_ticks[0]
    for tick in active_ticks[1:]:
        if tick - previous > min_region_ticks:
            regions.append({"start_tick": start, "end_tick": previous, "duration": previous - start + 1})
            start = tick
        previous = tick
    regions.append({"start_tick": start, "end_tick": previous, "duration": previous - start + 1})
    return {"regions": regions, "gaps": find_gaps(notes, song.length, min_gap=min_region_ticks)}


@tool_result
def generate_melody(output_path: str, song_name: str = "Generated Melody", key: str = "C major", tempo: float = 10.0, bars: int = 8, layer: int = 0, density: float = 1.0) -> dict[str, Any]:
    root, scale, _mode = parse_key_signature(key)
    song = create_song(song_name=song_name, author="nbs-mcp-server", tempo=tempo, length=bars * 16, layer_count=layer + 1)
    pattern = [0, 2, 4, 5, 7, 5, 4, 2]
    step = 2 if density > 1.5 else 4
    for index, tick in enumerate(range(0, song.length, step)):
        degree = pattern[index % len(pattern)]
        set_note(song, NbsNote(tick=tick, layer=layer, instrument=0, key=make_scale_key(root, degree, 45, scale), velocity=90, panning=100, pitch=0), overwrite=True)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(song.notes), "info": get_song_info(song)}


@tool_result
def generate_chord_progression(output_path: str, song_name: str = "Generated Chords", key: str = "C major", tempo: float = 10.0, bars: int = 8, layer: int = 0) -> dict[str, Any]:
    root, scale, mode = parse_key_signature(key)
    song = create_song(song_name=song_name, author="nbs-mcp-server", tempo=tempo, length=bars * 16, layer_count=layer + 1)
    progression = CHORD_PROGRESSIONS["minor" if mode == "minor" else "major"]
    for bar in range(bars):
        chord_degree = progression[bar % len(progression)]
        for offset, degree in enumerate([chord_degree, chord_degree + 2, chord_degree + 4]):
            set_note(song, NbsNote(tick=bar * 16 + offset * 4, layer=layer, instrument=6, key=make_scale_key(root, degree, 33, scale), velocity=75, panning=100, pitch=0), overwrite=True)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(song.notes), "info": get_song_info(song)}


@tool_result
def generate_bassline(output_path: str, song_name: str = "Generated Bassline", key: str = "C major", tempo: float = 10.0, bars: int = 8, layer: int = 0) -> dict[str, Any]:
    root, scale, mode = parse_key_signature(key)
    song = create_song(song_name=song_name, author="nbs-mcp-server", tempo=tempo, length=bars * 16, layer_count=layer + 1)
    progression = CHORD_PROGRESSIONS["minor" if mode == "minor" else "major"]
    for bar in range(bars):
        degree = progression[bar % len(progression)]
        for beat in [0, 8]:
            set_note(song, NbsNote(tick=bar * 16 + beat, layer=layer, instrument=1, key=make_scale_key(root, degree, 21, scale), velocity=88, panning=100, pitch=0), overwrite=True)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(song.notes), "info": get_song_info(song)}


@tool_result
def generate_drum_pattern(output_path: str, song_name: str = "Generated Drums", tempo: float = 10.0, bars: int = 8, layer: int = 0, pattern: str = "basic") -> dict[str, Any]:
    song = create_song(song_name=song_name, author="nbs-mcp-server", tempo=tempo, length=bars * 16, layer_count=layer + 1)
    for bar in range(bars):
        for beat in range(4):
            tick = bar * 16 + beat * 4
            key = 33 if beat in {0, 2} else 39
            set_note(song, NbsNote(tick=tick, layer=layer, instrument=2, key=key, velocity=82, panning=100, pitch=0), overwrite=True)
            if pattern == "busy" and beat in {1, 3}:
                set_note(song, NbsNote(tick=tick + 2, layer=layer, instrument=2, key=42, velocity=60, panning=100, pitch=0), overwrite=True)
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "note_count": len(song.notes), "info": get_song_info(song)}


@tool_result
def reharmonize_nbs(path: str, output_path: str, key: str = "C major", harmony_layer: int | None = None) -> dict[str, Any]:
    song = load_nbs(path)
    root, scale, mode = parse_key_signature(key)
    target_layer = harmony_layer if harmony_layer is not None else song.layer_count
    song.layers[target_layer] = NbsLayer(name="Reharmonized Harmony")
    song.layer_count = max(song.layer_count, target_layer + 1)
    progression = CHORD_PROGRESSIONS["minor" if mode == "minor" else "major"]
    bars = max(1, (song.length + 15) // 16)
    added = 0
    for bar in range(bars):
        chord_degree = progression[bar % len(progression)]
        for offset, degree in enumerate([chord_degree, chord_degree + 2, chord_degree + 4]):
            set_note(song, NbsNote(tick=bar * 16 + offset * 4, layer=target_layer, instrument=6, key=make_scale_key(root, degree, 33, scale), velocity=65, panning=100, pitch=0), overwrite=True)
            added += 1
    saved = save_nbs(song, output_path)
    return {"output_path": saved, "harmony_layer": target_layer, "added_count": added}


@tool_result
def make_loop(path: str, output_path: str, start_tick: int = 0, end_tick: int | None = None, repetitions: int = 2) -> dict[str, Any]:
    if repetitions <= 0:
        raise ValueError("repetitions must be > 0")
    song = load_nbs(path)
    end = end_tick if end_tick is not None else song.length - 1
    if end < start_tick:
        raise ValueError("end_tick must be >= start_tick")
    source = [note for note in iter_notes(song) if start_tick <= note.tick <= end]
    span = end - start_tick + 1
    loop_song = create_song(song_name=f"{song.song_name} Loop".strip(), author=song.author, tempo=song.tempo, length=span * repetitions, layer_count=song.layer_count)
    loop_song.layers = dict(song.layers)
    for rep in range(repetitions):
        for note in source:
            set_note(loop_song, _copy_note(note, tick=note.tick - start_tick + rep * span), overwrite=True)
    saved = save_nbs(loop_song, output_path)
    return {"output_path": saved, "source_note_count": len(source), "note_count": len(loop_song.notes), "length": loop_song.length}


@tool_result
def arrange_song(path: str, output_path: str, arrangement: list[dict[str, int]] | None = None) -> dict[str, Any]:
    song = load_nbs(path)
    if arrangement is None:
        midpoint = max(0, song.length // 2)
        arrangement = [
            {"start_tick": 0, "end_tick": midpoint, "repeat": 1},
            {"start_tick": midpoint, "end_tick": song.length - 1, "repeat": 2},
        ]
    arranged = create_song(song_name=f"{song.song_name} Arranged".strip(), author=song.author, tempo=song.tempo, length=0, layer_count=song.layer_count)
    arranged.layers = dict(song.layers)
    cursor = 0
    copied = 0
    for section in arrangement:
        start = int(section["start_tick"])
        end = int(section["end_tick"])
        repeat = int(section.get("repeat", 1))
        if end < start or repeat < 1:
            raise ValueError("invalid arrangement section")
        span = end - start + 1
        source = [note for note in iter_notes(song) if start <= note.tick <= end]
        for _ in range(repeat):
            for note in source:
                set_note(arranged, _copy_note(note, tick=cursor + note.tick - start), overwrite=True)
                copied += 1
            cursor += span
    arranged.length = cursor
    saved = save_nbs(arranged, output_path)
    return {"output_path": saved, "copied_count": copied, "length": arranged.length, "arrangement": arrangement}


@tool_result
def export_markdown_summary(path: str, output_path: str) -> dict[str, Any]:
    song = load_nbs(path)
    summary = summarize_nbs(path)["data"]
    analysis = analyze_music(path)["data"]
    resolved = resolve_safe_path(output_path, must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    text = [
        f"# {song.song_name or Path(path).name}",
        "",
        f"- Author: {song.author or 'Unknown'}",
        f"- Tempo: {song.tempo} TPS",
        f"- Length: {song.length} ticks",
        f"- Layers: {song.layer_count}",
        f"- Notes: {len(song.notes)}",
        "",
        "## Estimated Harmony",
        "",
        f"- Key: {analysis['harmony']['key'].get('key')}",
        f"- Confidence: {analysis['harmony']['key'].get('confidence')}",
        "",
        "## Layer Roles",
        "",
    ]
    for role in analysis["layer_roles"]:
        text.append(f"- Layer {role['layer']}: {role['role']} ({role['note_count']} notes)")
    text.extend(["", "## Gaps", ""])
    for gap in summary["structure"]["obvious_gaps"][:20]:
        text.append(f"- {gap['start_tick']} to {gap['end_tick']} ({gap['duration']} ticks)")
    resolved.write_text("\n".join(text) + "\n", encoding="utf-8")
    return {"output_path": str(resolved)}


@tool_result
def export_command_blocks(path: str, output_path: str, origin: dict[str, int] | None = None) -> dict[str, Any]:
    song = load_nbs(path)
    resolved = resolve_safe_path(output_path, must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    origin = origin or {"x": 0, "y": 64, "z": 0}
    lines = [
        "# Generated by nbs-mcp-server",
        "# Each line is a simple playsound command approximation.",
    ]
    for note in iter_notes(song):
        pitch = round(2 ** ((note.key - 45) / 12), 4)
        volume = round(note.velocity / 100, 3)
        lines.append(
            f"schedule function nbs_tick_{note.tick} {note.tick}t"
        )
        lines.append(
            f"# tick {note.tick} layer {note.layer}: playsound minecraft:block.note_block.harp master @a {origin['x']} {origin['y']} {origin['z']} {volume} {pitch}"
        )
    resolved.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output_path": str(resolved), "command_count": len(song.notes), "format": "mcfunction_notes"}

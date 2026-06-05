from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from schemas import NbsInfo, NbsNote, dump_model


DEFAULT_VANILLA_INSTRUMENT_COUNT = 16
DEFAULT_FILE_VERSION = 5


@dataclass
class NbsLayer:
    name: str = ""
    lock: int = 0
    volume: int = 100
    panning: int = 100


@dataclass
class NbsSong:
    song_name: str = ""
    author: str = ""
    original_author: str = ""
    description: str = ""
    tempo: float = 10.0
    time_signature: int = 4
    length: int = 0
    layer_count: int = 1
    file_version: int = DEFAULT_FILE_VERSION
    vanilla_instrument_count: int = DEFAULT_VANILLA_INSTRUMENT_COUNT
    minutes_spent: int = 0
    left_clicks: int = 0
    right_clicks: int = 0
    blocks_added: int = 0
    blocks_removed: int = 0
    midi_schematic_name: str = ""
    loop: bool = False
    max_loop_count: int = 0
    loop_start_tick: int = 0
    layers: dict[int, NbsLayer] = field(default_factory=dict)
    notes: dict[tuple[int, int], NbsNote] = field(default_factory=dict)
    custom_instruments: list[dict[str, Any]] = field(default_factory=list)


class NbsFormatError(ValueError):
    pass


def allowed_root() -> Path:
    root = os.environ.get("NBS_MCP_ALLOWED_ROOT") or os.getcwd()
    return Path(root).expanduser().resolve()


def resolve_safe_path(path: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = allowed_root() / candidate
    resolved = candidate.resolve()
    root = allowed_root()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path is outside allowed root: {resolved}") from exc
    if must_exist and not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved


def _read_exact(file: BinaryIO, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise NbsFormatError("unexpected end of .nbs file")
    return data


def _read_u8(file: BinaryIO) -> int:
    return _read_exact(file, 1)[0]


def _read_i16(file: BinaryIO) -> int:
    return struct.unpack("<h", _read_exact(file, 2))[0]


def _read_u16(file: BinaryIO) -> int:
    return struct.unpack("<H", _read_exact(file, 2))[0]


def _read_i32(file: BinaryIO) -> int:
    return struct.unpack("<i", _read_exact(file, 4))[0]


def _read_string(file: BinaryIO) -> str:
    length = _read_i32(file)
    if length < 0 or length > 10_000_000:
        raise NbsFormatError(f"invalid string length: {length}")
    return _read_exact(file, length).decode("utf-8", errors="replace")


def _write_u8(file: BinaryIO, value: int) -> None:
    file.write(struct.pack("<B", max(0, min(255, int(value)))))


def _write_i16(file: BinaryIO, value: int) -> None:
    file.write(struct.pack("<h", max(-32768, min(32767, int(value)))))


def _write_u16(file: BinaryIO, value: int) -> None:
    file.write(struct.pack("<H", max(0, min(65535, int(value)))))


def _write_i32(file: BinaryIO, value: int) -> None:
    file.write(struct.pack("<i", int(value)))


def _write_string(file: BinaryIO, value: str) -> None:
    encoded = (value or "").encode("utf-8")
    _write_i32(file, len(encoded))
    file.write(encoded)


def _read_notes(file: BinaryIO, song: NbsSong) -> None:
    tick = -1
    while True:
        tick_jump = _read_u16(file)
        if tick_jump == 0:
            break
        tick += tick_jump
        layer = -1
        while True:
            layer_jump = _read_u16(file)
            if layer_jump == 0:
                break
            layer += layer_jump
            instrument = _read_u8(file)
            key = _read_u8(file)
            velocity = _read_u8(file) if song.file_version >= 4 else 100
            panning = _read_u8(file) if song.file_version >= 4 else 100
            pitch = _read_i16(file) if song.file_version >= 4 else 0
            song.notes[(tick, layer)] = NbsNote(
                tick=tick,
                layer=layer,
                instrument=instrument,
                key=key,
                velocity=velocity,
                panning=panning,
                pitch=pitch,
            )


def _read_layer_metadata(file: BinaryIO, song: NbsSong) -> None:
    for layer_index in range(song.layer_count):
        name = _read_string(file)
        lock = _read_u8(file) if song.file_version >= 4 else 0
        volume = _read_u8(file)
        panning = _read_u8(file) if song.file_version >= 2 else 100
        song.layers[layer_index] = NbsLayer(name=name, lock=lock, volume=volume, panning=panning)


def _read_custom_instruments(file: BinaryIO, song: NbsSong) -> None:
    raw = file.read(1)
    if not raw:
        return
    count = raw[0]
    for _ in range(count):
        instrument = {
            "name": _read_string(file),
            "sound_file": _read_string(file),
            "key": _read_u8(file),
        }
        if song.file_version >= 4:
            raw_show = file.read(1)
            if raw_show:
                instrument["show_press_key"] = bool(raw_show[0])
        song.custom_instruments.append(instrument)


def load_nbs(path: str) -> NbsSong:
    resolved = resolve_safe_path(path, must_exist=True)
    with resolved.open("rb") as file:
        first_length = _read_u16(file)
        song = NbsSong()
        if first_length == 0:
            song.file_version = _read_u8(file)
            song.vanilla_instrument_count = _read_u8(file)
            song.length = _read_u16(file)
            song.layer_count = _read_u16(file)
        else:
            song.file_version = 0
            song.length = first_length
            song.layer_count = _read_u16(file)
        song.song_name = _read_string(file)
        song.author = _read_string(file)
        song.original_author = _read_string(file)
        song.description = _read_string(file)
        song.tempo = _read_u16(file) / 100.0
        _read_u8(file)
        _read_u8(file)
        song.time_signature = _read_u8(file)
        song.minutes_spent = _read_i32(file)
        song.left_clicks = _read_i32(file)
        song.right_clicks = _read_i32(file)
        song.blocks_added = _read_i32(file)
        song.blocks_removed = _read_i32(file)
        song.midi_schematic_name = _read_string(file)
        if song.file_version >= 4:
            song.loop = bool(_read_u8(file))
            song.max_loop_count = _read_u8(file)
            song.loop_start_tick = _read_u16(file)
        _read_notes(file, song)
        _read_layer_metadata(file, song)
        _read_custom_instruments(file, song)
    _normalize_song(song)
    return song


def save_nbs(song: NbsSong, path: str) -> str:
    _normalize_song(song)
    resolved = resolve_safe_path(path, must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("wb") as file:
        _write_u16(file, 0)
        _write_u8(file, DEFAULT_FILE_VERSION)
        _write_u8(file, song.vanilla_instrument_count or DEFAULT_VANILLA_INSTRUMENT_COUNT)
        _write_u16(file, song.length)
        _write_u16(file, song.layer_count)
        _write_string(file, song.song_name)
        _write_string(file, song.author)
        _write_string(file, song.original_author)
        _write_string(file, song.description)
        _write_u16(file, round(song.tempo * 100))
        _write_u8(file, 0)
        _write_u8(file, 10)
        _write_u8(file, song.time_signature)
        _write_i32(file, song.minutes_spent)
        _write_i32(file, song.left_clicks)
        _write_i32(file, song.right_clicks)
        _write_i32(file, song.blocks_added)
        _write_i32(file, song.blocks_removed)
        _write_string(file, song.midi_schematic_name)
        _write_u8(file, 1 if song.loop else 0)
        _write_u8(file, song.max_loop_count)
        _write_u16(file, song.loop_start_tick)
        _write_notes(file, song.notes.values())
        for index in range(song.layer_count):
            layer = song.layers.get(index, NbsLayer())
            _write_string(file, layer.name)
            _write_u8(file, layer.lock)
            _write_u8(file, layer.volume)
            _write_u8(file, layer.panning)
        _write_u8(file, len(song.custom_instruments))
        for instrument in song.custom_instruments:
            _write_string(file, str(instrument.get("name", "")))
            _write_string(file, str(instrument.get("sound_file", "")))
            _write_u8(file, int(instrument.get("key", 45)))
            _write_u8(file, 1 if instrument.get("show_press_key", False) else 0)
    return str(resolved)


def _write_notes(file: BinaryIO, notes: Iterable[NbsNote]) -> None:
    by_tick: dict[int, list[NbsNote]] = {}
    for note in sorted(notes, key=lambda item: (item.tick, item.layer)):
        by_tick.setdefault(note.tick, []).append(note)
    previous_tick = -1
    for tick in sorted(by_tick):
        _write_u16(file, tick - previous_tick)
        previous_tick = tick
        previous_layer = -1
        for note in sorted(by_tick[tick], key=lambda item: item.layer):
            _write_u16(file, note.layer - previous_layer)
            previous_layer = note.layer
            _write_u8(file, note.instrument)
            _write_u8(file, note.key)
            _write_u8(file, note.velocity)
            _write_u8(file, note.panning)
            _write_i16(file, note.pitch)
        _write_u16(file, 0)
    _write_u16(file, 0)


def _normalize_song(song: NbsSong) -> None:
    if song.notes:
        song.length = max(song.length, max(note.tick for note in song.notes.values()) + 1)
        song.layer_count = max(song.layer_count, max(note.layer for note in song.notes.values()) + 1)
    song.layer_count = max(0, song.layer_count)
    for index in range(song.layer_count):
        song.layers.setdefault(index, NbsLayer())


def create_song(song_name: str = "Untitled", author: str = "", tempo: float = 10.0, length: int = 0, layer_count: int = 1) -> NbsSong:
    song = NbsSong(song_name=song_name, author=author, tempo=tempo, length=max(0, length), layer_count=max(0, layer_count))
    _normalize_song(song)
    return song


def iter_notes(song: NbsSong) -> list[NbsNote]:
    return sorted(song.notes.values(), key=lambda item: (item.tick, item.layer))


def get_note(song: NbsSong, tick: int, layer: int) -> NbsNote | None:
    return song.notes.get((tick, layer))


def set_note(song: NbsSong, note: NbsNote, overwrite: bool = False) -> bool:
    position = (note.tick, note.layer)
    if position in song.notes and not overwrite:
        return False
    song.notes[position] = note
    _normalize_song(song)
    return True


def delete_note(song: NbsSong, tick: int, layer: int) -> bool:
    removed = song.notes.pop((tick, layer), None) is not None
    _normalize_song(song)
    return removed


def get_song_info(song: NbsSong) -> dict[str, Any]:
    notes = iter_notes(song)
    keys = [note.key for note in notes]
    used_instruments = sorted({note.instrument for note in notes})
    info = NbsInfo(
        song_name=song.song_name,
        author=song.author,
        original_author=song.original_author,
        description=song.description,
        length=song.length,
        layer_count=song.layer_count,
        tempo=song.tempo,
        tps=song.tempo,
        time_signature=song.time_signature,
        note_count=len(notes),
        custom_instruments=song.custom_instruments,
        file_version=song.file_version,
        used_instruments=used_instruments,
        min_key=min(keys) if keys else None,
        max_key=max(keys) if keys else None,
    )
    return dump_model(info)

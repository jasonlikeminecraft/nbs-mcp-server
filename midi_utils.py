from __future__ import annotations

import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

from schemas import NbsNote


PPQ = 480
NBS_TICKS_PER_BEAT = 4
MIDI_TICKS_PER_NBS_TICK = PPQ // NBS_TICKS_PER_BEAT


def nbs_key_to_midi(key: int) -> int:
    return max(0, min(127, int(key) + 21))


def midi_key_to_nbs(key: int) -> int:
    return max(0, min(87, int(key) - 21))


def bpm_from_nbs_tempo(tempo: float) -> float:
    return max(1.0, float(tempo) * 60.0 / NBS_TICKS_PER_BEAT)


def _varlen(value: int) -> bytes:
    value = max(0, int(value))
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7
    data = bytearray()
    while True:
        data.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(data)


def _read_varlen(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset


def _track_chunk(events: list[tuple[int, bytes]]) -> bytes:
    events.sort(key=lambda item: item[0])
    current = 0
    body = bytearray()
    for absolute_tick, payload in events:
        body.extend(_varlen(absolute_tick - current))
        body.extend(payload)
        current = absolute_tick
    body.extend(_varlen(0))
    body.extend(b"\xFF\x2F\x00")
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def write_midi(path: Path, notes: list[NbsNote], tempo: float, layer_names: dict[int, str] | None = None, note_duration_ticks: int = 1) -> None:
    layer_names = layer_names or {}
    bpm = bpm_from_nbs_tempo(tempo)
    mpqn = int(60_000_000 / bpm)
    tracks: list[bytes] = []
    meta_events = [
        (0, b"\xFF\x51\x03" + mpqn.to_bytes(3, "big")),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
    ]
    tracks.append(_track_chunk(meta_events))
    by_layer: dict[int, list[NbsNote]] = defaultdict(list)
    for note in notes:
        by_layer[note.layer].append(note)
    for layer in sorted(by_layer):
        channel = layer % 16
        if channel == 9:
            channel = 15
        events: list[tuple[int, bytes]] = []
        name = layer_names.get(layer, f"Layer {layer}").encode("utf-8")[:127]
        events.append((0, b"\xFF\x03" + _varlen(len(name)) + name))
        for note in by_layer[layer]:
            start = note.tick * MIDI_TICKS_PER_NBS_TICK
            end = start + max(1, note_duration_ticks) * MIDI_TICKS_PER_NBS_TICK
            midi_key = nbs_key_to_midi(note.key)
            velocity = max(1, min(127, round(note.velocity * 127 / 100)))
            events.append((start, bytes([0x90 | channel, midi_key, velocity])))
            events.append((end, bytes([0x80 | channel, midi_key, 0])))
        tracks.append(_track_chunk(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b"".join(tracks))


def _parse_track(data: bytes, track_index: int) -> tuple[list[dict[str, Any]], float | None]:
    offset = 0
    absolute = 0
    running_status: int | None = None
    open_notes: dict[tuple[int, int], tuple[int, int]] = {}
    notes: list[dict[str, Any]] = []
    tempo_mpqn: float | None = None
    while offset < len(data):
        delta, offset = _read_varlen(data, offset)
        absolute += delta
        status = data[offset]
        if status < 0x80:
            if running_status is None:
                break
            status = running_status
        else:
            offset += 1
            running_status = status if status < 0xF0 else running_status
        if status == 0xFF:
            meta_type = data[offset]
            offset += 1
            length, offset = _read_varlen(data, offset)
            payload = data[offset : offset + length]
            offset += length
            if meta_type == 0x51 and length == 3:
                tempo_mpqn = int.from_bytes(payload, "big")
            if meta_type == 0x2F:
                break
            continue
        if status in {0xF0, 0xF7}:
            length, offset = _read_varlen(data, offset)
            offset += length
            continue
        command = status & 0xF0
        channel = status & 0x0F
        data_len = 1 if command in {0xC0, 0xD0} else 2
        payload = data[offset : offset + data_len]
        offset += data_len
        if command == 0x90 and len(payload) == 2 and payload[1] > 0:
            open_notes[(channel, payload[0])] = (absolute, payload[1])
        elif command in {0x80, 0x90} and len(payload) == 2:
            opened = open_notes.pop((channel, payload[0]), None)
            if opened:
                start, velocity = opened
                notes.append(
                    {
                        "tick": round(start / MIDI_TICKS_PER_NBS_TICK),
                        "layer": max(0, track_index - 1),
                        "instrument": 0 if channel != 9 else 2,
                        "key": midi_key_to_nbs(payload[0]),
                        "velocity": max(1, min(100, round(velocity * 100 / 127))),
                        "panning": 100,
                        "pitch": 0,
                    }
                )
    return notes, tempo_mpqn


def read_midi(path: Path) -> tuple[list[dict[str, Any]], float]:
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    header_len = struct.unpack(">I", data[4:8])[0]
    fmt, track_count, division = struct.unpack(">HHH", data[8:14])
    if division != PPQ:
        # The importer still works with other PPQ values by scaling into NBS ticks.
        pass
    offset = 8 + header_len
    all_notes: list[dict[str, Any]] = []
    tempo_mpqn: float | None = None
    for track_index in range(track_count):
        if data[offset : offset + 4] != b"MTrk":
            raise ValueError("invalid MIDI track chunk")
        length = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        offset += 8
        track_data = data[offset : offset + length]
        offset += length
        notes, track_tempo = _parse_track(track_data, track_index)
        all_notes.extend(notes)
        tempo_mpqn = tempo_mpqn or track_tempo
    if tempo_mpqn:
        bpm = 60_000_000 / tempo_mpqn
        nbs_tempo = bpm * NBS_TICKS_PER_BEAT / 60.0
    else:
        nbs_tempo = 10.0
    if fmt not in {0, 1}:
        raise ValueError("only MIDI format 0 and 1 are supported")
    return sorted(all_notes, key=lambda item: (item["tick"], item["layer"])), nbs_tempo

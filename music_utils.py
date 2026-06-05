from __future__ import annotations

from collections import Counter, defaultdict

from schemas import NbsNote


PITCHED_INSTRUMENTS = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
    10, 11, 12, 13, 14, 15,
}
PERCUSSION_INSTRUMENTS = {2, 3, 4}

NOTE_NAMES = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}

MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]
MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10]
CHORD_PROGRESSIONS = {
    "major": [0, 4, 5, 3],
    "minor": [0, 5, 3, 4],
}

ROMAN_MAJOR = ["I", "ii", "iii", "IV", "V", "vi", "vii"]
ROMAN_MINOR = ["i", "ii°", "III", "iv", "v", "VI", "VII"]


def is_pitched_instrument(instrument: int) -> bool:
    return instrument in PITCHED_INSTRUMENTS and instrument not in PERCUSSION_INSTRUMENTS


def note_to_dict(note: NbsNote) -> dict:
    return note.model_dump() if hasattr(note, "model_dump") else note.dict()


def nearest_grid(tick: int, grid: int) -> int:
    return int(round(tick / grid) * grid)


def parse_key_signature(key_name: str) -> tuple[int, list[int], str]:
    parts = key_name.strip().replace("-", " ").split()
    root_name = (parts[0] if parts else "C").upper()
    mode = "minor" if any(part.lower().startswith("min") for part in parts[1:]) else "major"
    root = NOTE_NAMES.get(root_name, 0)
    steps = MINOR_STEPS if mode == "minor" else MAJOR_STEPS
    return root, steps, mode


def make_scale_key(root: int, degree: int, octave_base: int = 33, steps: list[int] | None = None) -> int:
    scale = steps or MAJOR_STEPS
    octave, index = divmod(degree, len(scale))
    return max(0, min(87, octave_base + root + scale[index] + octave * 12))


def find_likely_melody_layer(notes: list[NbsNote]) -> int | None:
    by_layer: dict[int, list[NbsNote]] = {}
    for note in notes:
        if is_pitched_instrument(note.instrument):
            by_layer.setdefault(note.layer, []).append(note)
    if not by_layer:
        return None
    scores = {}
    for layer, layer_notes in by_layer.items():
        avg_key = sum(note.key for note in layer_notes) / len(layer_notes)
        unique_ticks = len({note.tick for note in layer_notes})
        scores[layer] = unique_ticks * 2 + avg_key
    return max(scores, key=scores.get)


def find_gaps(notes: list[NbsNote], length: int, min_gap: int = 16) -> list[dict]:
    if not notes or length <= 0:
        return [{"start_tick": 0, "end_tick": length, "duration": length}] if length else []
    used_ticks = sorted({note.tick for note in notes})
    gaps = []
    previous = 0
    for tick in used_ticks:
        if tick - previous >= min_gap:
            gaps.append({"start_tick": previous, "end_tick": tick - 1, "duration": tick - previous})
        previous = tick + 1
    if length - previous >= min_gap:
        gaps.append({"start_tick": previous, "end_tick": length - 1, "duration": length - previous})
    return gaps


def duplicate_position_count(notes: list[NbsNote]) -> int:
    counts = Counter((note.tick, note.layer) for note in notes)
    return sum(count - 1 for count in counts.values() if count > 1)


def estimate_key(notes: list[NbsNote]) -> dict:
    pitched = [note for note in notes if is_pitched_instrument(note.instrument)]
    if not pitched:
        return {"key": None, "root": None, "mode": None, "confidence": 0.0}
    pitch_classes = Counter(note.key % 12 for note in pitched)
    best = None
    total = sum(pitch_classes.values())
    for root in range(12):
        for mode, steps in [("major", MAJOR_STEPS), ("minor", MINOR_STEPS)]:
            scale = {(root + step) % 12 for step in steps}
            score = sum(count for pc, count in pitch_classes.items() if pc in scale)
            tonic_score = pitch_classes[root] * 0.5
            value = score + tonic_score
            if best is None or value > best["score"]:
                root_name = next(name for name, value_pc in NOTE_NAMES.items() if value_pc == root and len(name) <= 2 and "B" not in name[1:])
                best = {"key": f"{root_name} {mode}", "root": root, "mode": mode, "score": value}
    confidence = round(best["score"] / max(1, total * 1.5), 3)
    return {"key": best["key"], "root": best["root"], "mode": best["mode"], "confidence": confidence}


def analyze_harmony(notes: list[NbsNote], ticks_per_bar: int = 16) -> dict:
    key_info = estimate_key(notes)
    if key_info["root"] is None:
        return {"key": key_info, "chords": [], "out_of_scale_notes": []}
    root = key_info["root"]
    mode = key_info["mode"] or "major"
    scale = MAJOR_STEPS if mode == "major" else MINOR_STEPS
    roman = ROMAN_MAJOR if mode == "major" else ROMAN_MINOR
    scale_pcs = {(root + step) % 12 for step in scale}
    by_bar: dict[int, list[NbsNote]] = defaultdict(list)
    for note in notes:
        if is_pitched_instrument(note.instrument):
            by_bar[note.tick // ticks_per_bar].append(note)
    chords = []
    for bar, bar_notes in sorted(by_bar.items()):
        counts = Counter(note.key % 12 for note in bar_notes)
        best_degree = 0
        best_score = -1
        for degree, step in enumerate(scale):
            chord = {
                (root + step) % 12,
                (root + scale[(degree + 2) % 7]) % 12,
                (root + scale[(degree + 4) % 7]) % 12,
            }
            score = sum(counts[pc] for pc in chord)
            if score > best_score:
                best_score = score
                best_degree = degree
        chords.append(
            {
                "bar": bar,
                "start_tick": bar * ticks_per_bar,
                "end_tick": (bar + 1) * ticks_per_bar - 1,
                "degree": best_degree + 1,
                "roman": roman[best_degree],
                "confidence": round(best_score / max(1, len(bar_notes)), 3),
            }
        )
    out_of_scale = [
        note_to_dict(note)
        for note in notes
        if is_pitched_instrument(note.instrument) and note.key % 12 not in scale_pcs
    ]
    return {"key": key_info, "chords": chords, "out_of_scale_notes": out_of_scale[:200], "out_of_scale_count": len(out_of_scale)}


def classify_layer_roles(notes: list[NbsNote], layer_count: int) -> list[dict]:
    by_layer: dict[int, list[NbsNote]] = defaultdict(list)
    for note in notes:
        by_layer[note.layer].append(note)
    melody = find_likely_melody_layer(notes)
    roles = []
    for layer in range(layer_count):
        layer_notes = by_layer.get(layer, [])
        if not layer_notes:
            role = "empty"
        elif any(not is_pitched_instrument(note.instrument) for note in layer_notes):
            role = "percussion"
        elif layer == melody:
            role = "melody"
        else:
            avg_key = sum(note.key for note in layer_notes) / len(layer_notes)
            role = "bass" if avg_key < 36 else "harmony"
        roles.append({"layer": layer, "role": role, "note_count": len(layer_notes)})
    return roles

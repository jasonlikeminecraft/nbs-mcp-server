from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def dump_model(model: BaseModel) -> dict[str, Any]:
    """Return a plain dict for Pydantic v2, with a v1-compatible fallback."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class NbsNote(BaseModel):
    tick: int = Field(ge=0)
    layer: int = Field(ge=0)
    instrument: int = Field(ge=0, le=255)
    key: int = Field(ge=0, le=87)
    velocity: int = Field(default=100, ge=0, le=100)
    panning: int = Field(default=100, ge=0, le=200)
    pitch: int = Field(default=0, ge=-32768, le=32767)


class NbsInfo(BaseModel):
    song_name: str = ""
    author: str = ""
    original_author: str = ""
    description: str = ""
    length: int = 0
    layer_count: int = 0
    tempo: float = 10.0
    tps: float = 10.0
    time_signature: int = 4
    note_count: int = 0
    custom_instruments: list[dict[str, Any]] = Field(default_factory=list)
    file_version: int = 5
    used_instruments: list[int] = Field(default_factory=list)
    min_key: int | None = None
    max_key: int | None = None


class ValidationIssue(BaseModel):
    severity: Literal["warning", "error"]
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class OperationResult(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return dump_model(cls(ok=True, data=data or {}))

    @classmethod
    def failure(cls, error: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return dump_model(cls(ok=False, error=error, details=details or {}))


class NoteTable(BaseModel):
    notes: list[NbsNote]

    @field_validator("notes")
    @classmethod
    def no_duplicate_positions(cls, value: list[NbsNote]) -> list[NbsNote]:
        seen: set[tuple[int, int]] = set()
        duplicates: list[tuple[int, int]] = []
        for note in value:
            position = (note.tick, note.layer)
            if position in seen:
                duplicates.append(position)
            seen.add(position)
        if duplicates:
            sample = ", ".join(f"tick={t}/layer={l}" for t, l in duplicates[:5])
            raise ValueError(f"duplicate note positions are not allowed: {sample}")
        return value

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from investigation.models import ResolvedScope


@dataclass(frozen=True)
class _FrozenMapping:
    items: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class _FrozenSequence:
    items: tuple[object, ...]


FrozenValue = str | int | float | bool | None | _FrozenMapping | _FrozenSequence


def _freeze(value: object) -> FrozenValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _FrozenMapping(
            tuple((str(key), _freeze(item)) for key, item in sorted(value.items()))
        )
    if isinstance(value, (list, tuple)):
        return _FrozenSequence(tuple(_freeze(item) for item in value))
    raise TypeError(f"Evidence value is not serializable: {type(value).__name__}")


def _thaw(value: FrozenValue) -> object:
    if isinstance(value, _FrozenMapping):
        return {key: _thaw(item) for key, item in value.items}
    if isinstance(value, _FrozenSequence):
        return [_thaw(item) for item in value.items]
    return value


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable output created by a registered deterministic tool."""

    evidence_id: str
    tool_name: str
    scope: ResolvedScope
    payload: tuple[tuple[str, FrozenValue], ...]

    def as_dict(self) -> dict[str, object]:
        return {key: _thaw(value) for key, value in self.payload}


class EvidenceRegistry:
    """Assign evidence IDs and preserve one immutable record per unique result."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._signatures: dict[tuple[object, ...], EvidenceRecord] = {}

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def register(
        self,
        tool_name: str,
        scope: ResolvedScope,
        payload: Mapping[str, object],
    ) -> EvidenceRecord:
        frozen_payload = tuple(
            (str(key), _freeze(value)) for key, value in sorted(payload.items())
        )
        signature = (tool_name, scope, frozen_payload)
        if signature in self._signatures:
            return self._signatures[signature]

        record = EvidenceRecord(
            evidence_id=f"EV-{len(self._records) + 1:03d}",
            tool_name=tool_name,
            scope=scope,
            payload=frozen_payload,
        )
        self._records.append(record)
        self._signatures[signature] = record
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return next(
            (record for record in self._records if record.evidence_id == evidence_id),
            None,
        )


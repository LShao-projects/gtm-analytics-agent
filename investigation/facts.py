"""Fact claims: sentences that code renders from evidence, so no model types a number."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from investigation.evidence import EvidenceRecord, EvidenceRegistry
from investigation.models import FACT_LEVELS, Claim, ClaimLevel

# Contributions below half a cent are rounding noise, matching the evidence tolerance.
_NEGLIGIBLE = 0.005


class FactError(ValueError):
    """A fact claim that cannot be rendered from its cited evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _format(value: float | int | None, value_format: str = "decimal") -> str:
    """Format a value like the dashboard's exact-value display."""
    if value is None:
        return "Not available"
    if value_format == "currency":
        return f"{'-' if value < 0 else ''}${abs(value):,.2f}"
    if value_format == "percent":
        return f"{value:.2%}"
    if value_format == "integer":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _signed_money(value: float) -> str:
    return f"{'+' if value > 0 else ''}{_format(value, 'currency')}"


format_value = _format
signed_money = _signed_money


@dataclass(frozen=True)
class _Contributor:
    label: str
    contribution: float
    current: float | None
    comparison: float | None
    value_format: str


def _contributors(
    record: EvidenceRecord, payload: Mapping[str, object]
) -> list[_Contributor]:
    if record.tool_name == "revenue_decomposition":
        return [
            _Contributor(
                str(row["driver"]),
                float(row["contribution"]),
                row["current"],
                row["comparison"],
                str(row["value_format"]),
            )
            for row in payload["drivers"]
        ]
    return [
        _Contributor(
            str(row["segment"]),
            float(row["absolute_delta"]),
            float(row["current"]),
            float(row["comparison"]),
            "currency",
        )
        for row in payload["segments"]
    ]


def _subject(
    record: EvidenceRecord, payload: Mapping[str, object], row: _Contributor
) -> str:
    if record.tool_name == "segment_contributions":
        return f"{payload['dimension']} segment {row.label}"
    return row.label


def _movement(record: EvidenceRecord, row: _Contributor) -> str:
    if row.current is None or row.comparison is None:
        return ""
    what = "segment revenue" if record.tool_name == "segment_contributions" else "value"
    return (
        f" ({what} moved from {_format(row.comparison, row.value_format)}"
        f" to {_format(row.current, row.value_format)})"
    )


def _primary_and_offset(
    rows: list[_Contributor], observed_change: float
) -> tuple[_Contributor | None, _Contributor | None]:
    """Largest contributor moving with the change, plus a larger opposing one if any."""
    direction = 1 if observed_change > 0 else -1
    with_change = [row for row in rows if row.contribution * direction > _NEGLIGIBLE]
    against = [row for row in rows if row.contribution * direction < -_NEGLIGIBLE]
    primary = max(with_change, key=lambda row: abs(row.contribution), default=None)
    largest_against = max(against, key=lambda row: abs(row.contribution), default=None)
    if largest_against is not None and (
        primary is None or abs(largest_against.contribution) > abs(primary.contribution)
    ):
        return primary, largest_against
    return primary, None


def _render_revenue_change(
    record: EvidenceRecord, payload: Mapping[str, object], key: str | None
) -> str:
    scope = record.scope
    text = (
        f"{payload['revenue_basis']} revenue was "
        f"{_format(payload['current_revenue'], 'currency')} in {scope.current_period.label}"
    )
    if payload["comparison_revenue"] is None:
        return f"{text}."
    relative = payload["relative_change"]
    relative_text = (
        f"{relative:+.2%}" if relative is not None else "relative change unavailable"
    )
    return (
        f"{text} versus {_format(payload['comparison_revenue'], 'currency')} in "
        f"{scope.comparison_period.label}, a change of "
        f"{_signed_money(payload['absolute_change'])} ({relative_text})."
    )


def _render_contribution(
    record: EvidenceRecord, payload: Mapping[str, object], key: str | None
) -> str:
    row = next((row for row in _contributors(record, payload) if row.label == key), None)
    if row is None:
        raise FactError("unknown_fact_key", f"Evidence has no contributor named {key!r}")
    return (
        f"{_subject(record, payload, row)} contributed "
        f"{_signed_money(row.contribution)} to the "
        f"{_signed_money(float(payload['observed_change']))} "
        f"{payload['revenue_basis']} revenue change{_movement(record, row)}."
    )


def _render_primary_contributor(
    record: EvidenceRecord, payload: Mapping[str, object], key: str | None
) -> str:
    observed = float(payload["observed_change"])
    basis = payload["revenue_basis"]
    if abs(observed) < _NEGLIGIBLE:
        return f"{basis} revenue did not change."
    primary, offset = _primary_and_offset(_contributors(record, payload), observed)
    if primary is None:
        return (
            f"No contributor moved in the direction of the "
            f"{_signed_money(observed)} {basis} revenue change."
        )
    text = (
        f"{_subject(record, payload, primary)} was the largest contributor in the "
        f"direction of the {_signed_money(observed)} {basis} revenue change "
        f"({_signed_money(primary.contribution)})."
    )
    if offset is not None:
        text += (
            f" A larger offsetting contribution came from "
            f"{_subject(record, payload, offset)} ({_signed_money(offset.contribution)})."
        )
    return text


@dataclass(frozen=True)
class FactTemplate:
    level: ClaimLevel
    tools: tuple[str, ...]
    needs_key: bool
    render: Callable[[EvidenceRecord, Mapping[str, object], str | None], str]


FACT_TEMPLATES: Mapping[str, FactTemplate] = {
    "revenue_change": FactTemplate(
        "verified_fact", ("revenue_summary",), False, _render_revenue_change
    ),
    "contribution": FactTemplate(
        "observed_contribution",
        ("revenue_decomposition", "segment_contributions"),
        True,
        _render_contribution,
    ),
    "primary_contributor": FactTemplate(
        "observed_contribution",
        ("revenue_decomposition", "segment_contributions"),
        False,
        _render_primary_contributor,
    ),
}


def render_fact(claim: Claim, record: EvidenceRecord) -> str:
    """Render a fact claim from its single evidence record, or raise FactError."""
    template = FACT_TEMPLATES.get(claim.fact or "")
    if template is None:
        raise FactError(
            "unknown_fact_kind",
            f"Fact claims must name one of {sorted(FACT_TEMPLATES)}",
        )
    if claim.level != template.level:
        raise FactError("fact_level_mismatch", f"{claim.fact} is a {template.level} claim")
    if record.tool_name not in template.tools:
        raise FactError(
            "evidence_tool_mismatch",
            f"{claim.fact} needs evidence from {', '.join(template.tools)}",
        )
    if template.needs_key and not claim.key:
        raise FactError("fact_key_required", f"{claim.fact} needs a key")
    if not template.needs_key and claim.key:
        raise FactError("unexpected_fact_key", f"{claim.fact} takes no key")
    try:
        return template.render(record, record.as_dict(), claim.key)
    except FactError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise FactError(
            "invalid_evidence_schema", "Evidence payload cannot be rendered"
        ) from error


def render_claim(claim: Claim, registry: EvidenceRegistry) -> str:
    """Return the report sentence: rendered for facts, the model's text otherwise."""
    if claim.level not in FACT_LEVELS:
        return claim.text
    if len(claim.evidence_ids) != 1:
        raise FactError(
            "fact_requires_single_evidence",
            "A fact claim cites exactly one evidence record",
        )
    record = registry.get(claim.evidence_ids[0])
    if record is None:
        raise FactError(
            "unknown_evidence_reference", f"Unknown evidence: {claim.evidence_ids[0]}"
        )
    return render_fact(claim, record)

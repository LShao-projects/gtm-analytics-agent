"""Property checks against the real Maven database; skipped when it is not built."""

import calendar
import dataclasses
import random

import pytest

from dashboard.data import DEFAULT_DATABASE, query_df, validate_database
from dashboard.models import FilterSpec
from dashboard.ui import _months
from investigation.context import resolve_scope
from investigation.evidence import EvidenceRegistry
from investigation.facts import render_claim
from investigation.models import Claim, InvestigationReport, ResolvedScope
from investigation.tools import SUPPORTED_SEGMENT_DIMENSIONS, InvestigationTools
from investigation.validator import validate_evidence, validate_report


pytestmark = pytest.mark.skipif(
    not DEFAULT_DATABASE.is_file(), reason="the real Maven database is not built"
)


def _label(month: str) -> str:
    year, number = month.split("-")
    return f"{calendar.month_name[int(number)]} {year}"


def _scope(basis: str, previous: str, current: str) -> ResolvedScope:
    result = resolve_scope(
        f"Why did {basis.lower()} revenue change from {_label(previous)} "
        f"to {_label(current)}?"
    )
    assert isinstance(result, ResolvedScope)
    return result


def _reporting_pairs() -> list[tuple[str, str]]:
    months = _months(validate_database(DEFAULT_DATABASE))
    return list(zip(months, months[1:]))


def _check_scope(scope: ResolvedScope) -> None:
    """Every registered tool reconciles and every fact template renders and validates."""
    registry = EvidenceRegistry()
    tools = InvestigationTools(DEFAULT_DATABASE, registry)
    summary = tools.revenue_summary(scope)
    contributors = [tools.revenue_decomposition(scope)] + [
        tools.segment_contributions(scope, dimension=dimension)
        for dimension in SUPPORTED_SEGMENT_DIMENSIONS
    ]

    claims = [Claim("", "verified_fact", (summary.evidence_id,), "revenue_change")]
    for record in contributors:
        claims.append(
            Claim("", "observed_contribution", (record.evidence_id,), "primary_contributor")
        )
        payload = record.as_dict()
        for row in payload.get("drivers", []) + payload.get("segments", []):
            claims.append(
                Claim(
                    "",
                    "observed_contribution",
                    (record.evidence_id,),
                    "contribution",
                    row.get("driver") or row.get("segment"),
                )
            )

    for record in registry.records:
        assert validate_evidence(record).passed, (scope.question, record.tool_name)
    result = validate_report(
        InvestigationReport(scope, tuple(claims), "supported_conclusion"), registry
    )
    assert result.passed, (scope.question, result.issues[:3])
    sentences = [render_claim(claim, registry) for claim in claims]
    assert all(sentences)
    change = summary.as_dict()["absolute_change"]
    assert f"{abs(change):,.2f}" in sentences[0], (scope.question, sentences[0])


def test_every_reporting_month_pair_reconciles_and_renders():
    pairs = _reporting_pairs()
    assert len(pairs) >= 12

    for previous, current in pairs:
        for basis in ("Gross", "Net"):
            _check_scope(_scope(basis, previous, current))


def test_seeded_filtered_scopes_reconcile_and_render():
    pairs = _reporting_pairs()
    devices = list(
        query_df(
            DEFAULT_DATABASE,
            "SELECT DISTINCT device_type AS value FROM website_sessions ORDER BY 1",
        )["value"]
    )
    rng = random.Random(0)

    for _ in range(20):
        previous, current = rng.choice(pairs)
        basis = rng.choice(("Gross", "Net"))
        scope = dataclasses.replace(
            _scope(basis, previous, current),
            filters=FilterSpec(devices=(rng.choice(devices),)),
        )
        _check_scope(scope)

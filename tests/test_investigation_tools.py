import hashlib

import pytest

from dashboard.models import DatePeriod, FilterSpec
from investigation.context import resolve_scope
from investigation.evidence import EvidenceRegistry
from investigation.models import ResolvedScope
from investigation.tools import InvestigationTools, ToolInputError, UnsupportedToolError
from investigation.validator import validate_evidence


MAY = DatePeriod.from_months("2014-05", "2014-05")
JUNE = DatePeriod.from_months("2014-06", "2014-06")


def _scope(*, basis: str = "Gross", comparison: bool = True) -> ResolvedScope:
    result = resolve_scope(
        f"Why did {basis.lower()} revenue change from May 2014 to June 2014?"
        if comparison
        else f"What was {basis.lower()} revenue in June 2014?"
    )
    assert isinstance(result, ResolvedScope)
    return result


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_revenue_summary_uses_dashboard_kpis_and_is_read_only(analytics_db):
    before = _digest(analytics_db)
    tools = InvestigationTools(analytics_db)

    record = tools.revenue_summary(_scope())
    payload = record.as_dict()

    assert payload["current_revenue"] == 0.0
    assert payload["comparison_revenue"] == 130.0
    assert payload["absolute_change"] == -130.0
    assert payload["relative_change"] == -1.0
    assert payload["current"]["sessions"] == 1
    assert payload["comparison"]["orders"] == 2
    assert _digest(analytics_db) == before
    assert validate_evidence(record).passed


def test_net_revenue_decomposition_reconciles_and_preserves_refund_direction(
    analytics_db,
):
    tools = InvestigationTools(analytics_db)

    record = tools.revenue_decomposition(_scope(basis="Net"))
    payload = record.as_dict()
    drivers = {row["driver"]: row for row in payload["drivers"]}

    assert payload["observed_change"] == -80.0
    assert payload["contribution_sum"] == pytest.approx(-80.0)
    assert payload["reconciliation_error"] == pytest.approx(0.0)
    assert drivers["Recorded-refund impact"]["current"] == 0.0
    assert drivers["Recorded-refund impact"]["comparison"] == 50.0
    assert drivers["Recorded-refund impact"]["contribution"] == 50.0
    assert validate_evidence(record).passed


@pytest.mark.parametrize(
    "dimension",
    ("Traffic source", "UTM source", "Campaign", "Device", "Session type"),
)
def test_segment_contributions_reconcile_for_every_registered_dimension(
    analytics_db, dimension
):
    tools = InvestigationTools(analytics_db)

    record = tools.segment_contributions(_scope(), dimension=dimension)
    payload = record.as_dict()

    assert payload["dimension"] == dimension
    assert payload["observed_change"] == -130.0
    assert payload["contribution_sum"] == pytest.approx(-130.0)
    assert payload["segments"]
    assert validate_evidence(record).passed


def test_registry_reuses_identical_evidence_and_assigns_unique_ids(analytics_db):
    registry = EvidenceRegistry()
    tools = InvestigationTools(analytics_db, registry)
    scope = _scope()

    first = tools.revenue_summary(scope)
    duplicate = tools.revenue_summary(scope)
    second = tools.revenue_decomposition(scope)

    assert first is duplicate
    assert first.evidence_id == "EV-001"
    assert second.evidence_id == "EV-002"
    assert registry.records == (first, second)


def test_evidence_payload_preserves_empty_sequences():
    registry = EvidenceRegistry()

    record = registry.register(
        "revenue_decomposition",
        _scope(),
        {
            "drivers": [],
            "metadata": {},
        },
    )

    assert record.as_dict() == {"drivers": [], "metadata": {}}


def test_registered_dispatch_rejects_unknown_tools_and_invalid_arguments(analytics_db):
    tools = InvestigationTools(analytics_db)

    with pytest.raises(UnsupportedToolError, match="not registered"):
        tools.call("write_sql", _scope())
    with pytest.raises(ToolInputError, match="Unsupported segment dimension"):
        tools.call("segment_contributions", _scope(), dimension="Ad spend")
    with pytest.raises(TypeError):
        tools.call("revenue_summary", _scope(), dimension="Device")


def test_comparison_tools_reject_single_period_scope(analytics_db):
    tools = InvestigationTools(analytics_db)
    scope = _scope(comparison=False)

    with pytest.raises(ToolInputError, match="requires a comparison"):
        tools.revenue_decomposition(scope)
    with pytest.raises(ToolInputError, match="requires a comparison"):
        tools.segment_contributions(scope)


def test_empty_filter_selection_is_preserved_in_tool_scope(analytics_db):
    base = _scope()
    scope = ResolvedScope(
        question=base.question,
        current_period=JUNE,
        comparison_period=MAY,
        filters=FilterSpec(devices=()),
        revenue_basis=base.revenue_basis,
        metric=base.metric,
        requires_comparison=True,
        revenue_basis_source=base.revenue_basis_source,
        current_period_source=base.current_period_source,
        comparison_period_source=base.comparison_period_source,
    )

    payload = InvestigationTools(analytics_db).revenue_summary(scope).as_dict()

    assert payload["current_revenue"] == 0.0
    assert payload["comparison_revenue"] == 0.0
    assert payload["relative_change"] is None


import pytest

from dashboard.ui import _format_exact_value
from investigation.context import resolve_scope
from investigation.evidence import EvidenceRegistry
from investigation.facts import (
    FACT_TEMPLATES,
    FactError,
    _format,
    render_claim,
    render_fact,
)
from investigation.models import Claim, ResolvedScope
from investigation.tools import SUPPORTED_SEGMENT_DIMENSIONS, InvestigationTools


def _scope(question: str = "Why did gross revenue change from May 2014 to June 2014?"):
    result = resolve_scope(question)
    assert isinstance(result, ResolvedScope)
    return result


def _driver(name, contribution, current=None, comparison=None, value_format="currency"):
    return {
        "driver": name,
        "current": current,
        "comparison": comparison,
        "value_format": value_format,
        "contribution": contribution,
    }


def _decomposition(registry, observed, drivers):
    return registry.register(
        "revenue_decomposition",
        _scope(),
        {
            "revenue_basis": "Gross",
            "observed_change": observed,
            "contribution_sum": observed,
            "reconciliation_error": 0.0,
            "drivers": drivers,
        },
    )


def _segments(registry, observed, segments):
    return registry.register(
        "segment_contributions",
        _scope(),
        {
            "revenue_basis": "Gross",
            "dimension": "Traffic source",
            "observed_change": observed,
            "contribution_sum": observed,
            "reconciliation_error": 0.0,
            "segments": segments,
        },
    )


def _revenue_change(record):
    return render_fact(
        Claim("", "verified_fact", (record.evidence_id,), "revenue_change"), record
    )


def _primary(record):
    return render_fact(
        Claim("", "observed_contribution", (record.evidence_id,), "primary_contributor"),
        record,
    )


def _contribution(record, key):
    return render_fact(
        Claim("", "observed_contribution", (record.evidence_id,), "contribution", key),
        record,
    )


def test_revenue_change_is_rendered_from_the_summary_evidence(analytics_db):
    registry = EvidenceRegistry()
    tools = InvestigationTools(analytics_db, registry)

    both = tools.revenue_summary(_scope())
    single = tools.revenue_summary(_scope("What was gross revenue in June 2014?"))

    assert _revenue_change(both) == (
        "Gross revenue was $0.00 in Jun 1–Jun 30, 2014 versus $130.00 in "
        "May 1–May 31, 2014, a change of -$130.00 (-100.00%)."
    )
    assert _revenue_change(single) == "Gross revenue was $0.00 in Jun 1–Jun 30, 2014."


def test_revenue_change_says_when_the_relative_change_is_unavailable():
    registry = EvidenceRegistry()
    record = registry.register(
        "revenue_summary",
        _scope("Why did net revenue change from May 2014 to June 2014?"),
        {
            "revenue_basis": "Net",
            "current_revenue": 50.0,
            "comparison_revenue": 0.0,
            "absolute_change": 50.0,
            "relative_change": None,
        },
    )

    assert _revenue_change(record) == (
        "Net revenue was $50.00 in Jun 1–Jun 30, 2014 versus $0.00 in "
        "May 1–May 31, 2014, a change of +$50.00 (relative change unavailable)."
    )


def test_driver_contribution_sentences_come_from_the_evidence(analytics_db):
    registry = EvidenceRegistry()
    net = InvestigationTools(analytics_db, registry).revenue_decomposition(
        _scope("Why did net revenue change from May 2014 to June 2014?")
    )
    record = _decomposition(
        registry,
        -100.0,
        [
            _driver("Sessions", -30.0, 90, 100, "integer"),
            _driver("Order rate", -60.0, 0.05, 0.06, "percent"),
            _driver("Order/session timing residual", -10.0),
        ],
    )

    assert _contribution(net, "Recorded-refund impact") == (
        "Recorded-refund impact contributed +$50.00 to the -$80.00 Net revenue change "
        "(value moved from $50.00 to $0.00)."
    )
    assert _contribution(record, "Order rate") == (
        "Order rate contributed -$60.00 to the -$100.00 Gross revenue change "
        "(value moved from 6.00% to 5.00%)."
    )
    assert _contribution(record, "Sessions") == (
        "Sessions contributed -$30.00 to the -$100.00 Gross revenue change "
        "(value moved from 100 to 90)."
    )
    assert _contribution(record, "Order/session timing residual") == (
        "Order/session timing residual contributed -$10.00 to the -$100.00 Gross "
        "revenue change."
    )


def test_segment_sentences_name_the_dimension_and_segment_revenue():
    registry = EvidenceRegistry()
    record = _segments(
        registry,
        -50.0,
        [
            {"segment": "Paid Search", "current": 100.0, "comparison": 160.0,
             "absolute_delta": -60.0, "share_of_total_delta": 1.2},
            {"segment": "Direct", "current": 50.0, "comparison": 40.0,
             "absolute_delta": 10.0, "share_of_total_delta": -0.2},
        ],
    )

    assert _contribution(record, "Paid Search") == (
        "Traffic source segment Paid Search contributed -$60.00 to the -$50.00 Gross "
        "revenue change (segment revenue moved from $160.00 to $100.00)."
    )
    assert _primary(record) == (
        "Traffic source segment Paid Search was the largest contributor in the "
        "direction of the -$50.00 Gross revenue change (-$60.00)."
    )


def test_primary_contributor_is_the_largest_one_moving_with_the_change():
    registry = EvidenceRegistry()
    record = _decomposition(
        registry,
        -100.0,
        [
            _driver("Sessions", -30.0),
            _driver("Order rate", -60.0),
            _driver("Gross AOV", -10.0),
        ],
    )

    assert _primary(record) == (
        "Order rate was the largest contributor in the direction of the -$100.00 "
        "Gross revenue change (-$60.00)."
    )


def test_primary_contributor_reports_a_larger_offsetting_contribution():
    registry = EvidenceRegistry()
    record = _decomposition(
        registry,
        1.0,
        [
            _driver("Sessions", -10.0),
            _driver("Order rate", 6.0),
            _driver("Gross AOV", 5.0),
        ],
    )

    assert _primary(record) == (
        "Order rate was the largest contributor in the direction of the +$1.00 "
        "Gross revenue change (+$6.00). A larger offsetting contribution came from "
        "Sessions (-$10.00)."
    )


@pytest.mark.parametrize(
    "observed, drivers, expected",
    [
        (
            0.0,
            [_driver("Sessions", 5.0), _driver("Order rate", -5.0)],
            "Gross revenue did not change.",
        ),
        (
            -10.0,
            [_driver("Sessions", -5.0), _driver("Order rate", -5.0)],
            "Sessions was the largest contributor in the direction of the -$10.00 "
            "Gross revenue change (-$5.00).",
        ),
        (
            -0.01,
            [_driver("Sessions", -0.004), _driver("Order rate", -0.003), _driver("Gross AOV", -0.003)],
            "No contributor moved in the direction of the -$0.01 Gross revenue change.",
        ),
    ],
    ids=["no change", "tie keeps evidence order", "only rounding-sized movements"],
)
def test_primary_contributor_edge_cases(observed, drivers, expected):
    record = _decomposition(EvidenceRegistry(), observed, drivers)

    assert _primary(record) == expected


def test_every_template_renders_for_every_registered_dimension(analytics_db):
    registry = EvidenceRegistry()
    tools = InvestigationTools(analytics_db, registry)
    scope = _scope()
    summary = tools.revenue_summary(scope)
    decomposition = tools.revenue_decomposition(scope)

    assert _revenue_change(summary)
    for record in [decomposition] + [
        tools.segment_contributions(scope, dimension=dimension)
        for dimension in SUPPORTED_SEGMENT_DIMENSIONS
    ]:
        assert _primary(record)
        payload = record.as_dict()
        for row in payload.get("drivers", []) + payload.get("segments", []):
            key = row.get("driver") or row.get("segment")
            assert _contribution(record, key)


def test_render_claim_returns_model_text_for_free_text_and_rejects_bad_references():
    registry = EvidenceRegistry()
    record = _decomposition(registry, -10.0, [_driver("Sessions", -10.0)])
    fact = Claim("", "observed_contribution", (record.evidence_id,), "primary_contributor")

    assert render_claim(Claim("A reading.", "interpretation"), registry) == "A reading."
    assert render_claim(fact, registry) == _primary(record)
    for bad, code in (
        (Claim("", "observed_contribution", (), "primary_contributor"), "fact_requires_single_evidence"),
        (Claim("", "observed_contribution", ("EV-999",), "primary_contributor"), "unknown_evidence_reference"),
    ):
        with pytest.raises(FactError) as error:
            render_claim(bad, registry)
        assert error.value.code == code


def test_malformed_evidence_is_reported_not_raised():
    registry = EvidenceRegistry()
    record = registry.register("revenue_summary", _scope(), {"revenue_basis": "Gross"})

    with pytest.raises(FactError) as error:
        _revenue_change(record)

    assert error.value.code == "invalid_evidence_schema"


def test_templates_declare_levels_that_the_validator_can_enforce():
    assert {name: template.level for name, template in FACT_TEMPLATES.items()} == {
        "revenue_change": "verified_fact",
        "contribution": "observed_contribution",
        "primary_contributor": "observed_contribution",
    }


@pytest.mark.parametrize(
    "value, value_format",
    [
        (1234.5, "currency"),
        (-0.004, "currency"),
        (2_500_000, "currency"),
        (0.0712, "percent"),
        (12345, "integer"),
        (1.5, "decimal"),
        (None, "currency"),
    ],
)
def test_value_format_matches_the_dashboard_exact_display(value, value_format):
    assert _format(value, value_format) == _format_exact_value(value, value_format)

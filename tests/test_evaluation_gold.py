"""The frozen gold case must keep matching a fresh calculation on the real database."""

import json
from pathlib import Path

import pytest

from dashboard.data import DEFAULT_DATABASE
from dashboard.metrics import funnel_summary
from dashboard.models import DatePeriod, FilterSpec
from investigation.context import resolve_scope
from investigation.evidence import EvidenceRegistry
from investigation.facts import render_fact
from investigation.models import Claim
from investigation.tools import InvestigationTools

CASE = json.loads(
    (Path(__file__).parents[1] / "evaluation/cases/revenue_may_june_2014_gold.json").read_text()
)
DOLLARS = CASE["tolerance"]["dollars"]
RATE = CASE["tolerance"]["rate"]
EXPECTED = CASE["expected"]


def test_the_case_is_frozen_development_and_not_a_held_out():
    assert CASE["status"] == "FROZEN"
    assert CASE["split"] == "development"
    assert CASE["approved_by"].startswith("User")
    assert CASE["required"] and CASE["forbidden"]


pytestmark_real = pytest.mark.skipif(
    not DEFAULT_DATABASE.is_file(), reason="the real Maven database is not built"
)


@pytestmark_real
def test_tools_reproduce_the_frozen_gross_values():
    tools = InvestigationTools(DEFAULT_DATABASE, EvidenceRegistry())
    scope = resolve_scope(CASE["question"])
    summary = tools.revenue_summary(scope)
    payload = summary.as_dict()

    assert payload["absolute_change"] == pytest.approx(EXPECTED["gross_change"], abs=DOLLARS)
    assert payload["relative_change"] == pytest.approx(
        EXPECTED["gross_relative_change"], abs=RATE
    )
    names = {"refund_amount": DOLLARS, "conversion_rate": RATE, "aov": DOLLARS,
             "gross_revenue": DOLLARS, "net_revenue": DOLLARS, "sessions": 0, "orders": 0}
    for key, (before, after) in EXPECTED["kpis_comparison_then_current"].items():
        assert payload["comparison"][key] == pytest.approx(before, abs=names[key]), key
        assert payload["current"][key] == pytest.approx(after, abs=names[key]), key

    decomposition = tools.revenue_decomposition(scope)
    drivers = {row["driver"]: row["contribution"] for row in decomposition.as_dict()["drivers"]}
    assert drivers == pytest.approx(EXPECTED["gross_decomposition"], abs=DOLLARS)
    sentence = render_fact(
        Claim("", "observed_contribution", (decomposition.evidence_id,), "primary_contributor"),
        decomposition,
    )
    assert sentence.startswith(f"{EXPECTED['primary_contributor']} was the largest contributor")

    for dimension, expected in EXPECTED["segment_contributions"].items():
        record = tools.segment_contributions(scope, dimension=dimension)
        found = {row["segment"]: row["absolute_delta"] for row in record.as_dict()["segments"]}
        assert found == pytest.approx(expected, abs=DOLLARS), dimension


@pytest.mark.parametrize("basis_word", ["net"])
@pytest.mark.skipif(not DEFAULT_DATABASE.is_file(), reason="the real Maven database is not built")
def test_net_variant_matches_the_frozen_net_values(basis_word):
    tools = InvestigationTools(DEFAULT_DATABASE, EvidenceRegistry())
    scope = resolve_scope(CASE["question"].replace("gross", basis_word))
    payload = tools.revenue_summary(scope).as_dict()
    drivers = {
        row["driver"]: row["contribution"]
        for row in tools.revenue_decomposition(scope).as_dict()["drivers"]
    }

    assert payload["absolute_change"] == pytest.approx(EXPECTED["net_change"], abs=DOLLARS)
    assert drivers["Recorded-refund impact"] == pytest.approx(
        EXPECTED["net_refund_impact"], abs=DOLLARS
    )


@pytestmark_real
def test_funnel_follow_up_matches_the_frozen_step_conversions():
    may = DatePeriod.from_months("2014-05", "2014-05")
    june = DatePeriod.from_months("2014-06", "2014-06")
    before = funnel_summary(DEFAULT_DATABASE, FilterSpec(), may).set_index("transition")
    after = funnel_summary(DEFAULT_DATABASE, FilterSpec(), june).set_index("transition")

    for step, (expected_before, expected_after) in EXPECTED[
        "funnel_step_conversion_comparison_then_current"
    ].items():
        assert before.loc[step, "step_conversion"] == pytest.approx(expected_before, abs=RATE)
        assert after.loc[step, "step_conversion"] == pytest.approx(expected_after, abs=RATE)

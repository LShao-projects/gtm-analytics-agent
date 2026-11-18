from dataclasses import FrozenInstanceError

import pytest

from dashboard.models import DatePeriod, FilterSpec
from investigation.context import resolve_scope
from investigation.models import ClarificationRequest, DashboardContext, ResolvedScope


MAY = DatePeriod.from_months("2014-05", "2014-05")
JUNE = DatePeriod.from_months("2014-06", "2014-06")


def _overview_context(**overrides) -> DashboardContext:
    values = {
        "page": "Executive Overview",
        "current_period": JUNE,
        "comparison_period": MAY,
        "comparison_mode": "Previous period",
        "filters": FilterSpec(traffic_sources=("Paid Search",), devices=("desktop",)),
        "primary_metric": "Revenue",
        "revenue_basis": "Gross",
        "page_controls": (("grain", "Month"),),
    }
    values.update(overrides)
    return DashboardContext(**values)


def test_short_change_question_resolves_from_dashboard_context():
    result = resolve_scope("Why did revenue change here?", _overview_context())

    assert isinstance(result, ResolvedScope)
    assert result.current_period == JUNE
    assert result.comparison_period == MAY
    assert result.revenue_basis == "Gross"
    assert result.metric == "gross_revenue"
    assert result.filters == FilterSpec(
        traffic_sources=("Paid Search",), devices=("desktop",)
    )
    assert result.revenue_basis_source == "dashboard"
    assert result.current_period_source == "dashboard"
    assert result.comparison_period_source == "dashboard"


def test_explicit_basis_overrides_dashboard_basis():
    result = resolve_scope(
        "Why did net revenue change here?", _overview_context(revenue_basis="Gross")
    )

    assert isinstance(result, ResolvedScope)
    assert result.revenue_basis == "Net"
    assert result.metric == "net_revenue"
    assert result.revenue_basis_source == "question"


@pytest.mark.parametrize(
    "question",
    (
        "Why did gross revenue change from May 2014 to June 2014?",
        "Why did gross revenue change from 2014-05 to 2014-06?",
        "为什么毛收入从2014年5月到2014年6月发生变化？",
    ),
)
def test_two_explicit_months_override_dashboard_periods(question):
    context = _overview_context(
        current_period=DatePeriod.from_months("2015-02", "2015-02"),
        comparison_period=DatePeriod.from_months("2015-01", "2015-01"),
    )

    result = resolve_scope(question, context)

    assert isinstance(result, ResolvedScope)
    assert result.current_period == JUNE
    assert result.comparison_period == MAY
    assert result.current_period_source == "question"
    assert result.comparison_period_source == "question"


def test_one_explicit_month_can_use_matching_dashboard_comparison():
    result = resolve_scope(
        "Why did gross revenue change in June 2014?", _overview_context()
    )

    assert isinstance(result, ResolvedScope)
    assert result.current_period == JUNE
    assert result.comparison_period == MAY
    assert result.current_period_source == "question"
    assert result.comparison_period_source == "dashboard"


def test_one_explicit_month_does_not_reuse_a_stale_dashboard_comparison():
    result = resolve_scope(
        "Why did gross revenue change in July 2014?", _overview_context()
    )

    assert isinstance(result, ClarificationRequest)
    assert result.field == "comparison_period"
    assert result.question == "Which comparison period should I use?"


def test_factual_question_with_one_month_does_not_expand_to_comparison():
    result = resolve_scope("What was gross revenue in June 2014?")

    assert isinstance(result, ResolvedScope)
    assert result.current_period == JUNE
    assert result.comparison_period is None
    assert result.requires_comparison is False


def test_two_months_are_a_comparison_even_without_a_comparison_keyword():
    result = resolve_scope("Gross revenue in May 2014 and June 2014")

    assert isinstance(result, ResolvedScope)
    assert result.comparison_period == MAY
    assert result.current_period == JUNE
    assert result.requires_comparison is True


@pytest.mark.parametrize(
    ("question", "context", "field"),
    (
        ("", None, "question"),
        ("Why did gross revenue change?", None, "current_period"),
        (
            "Why did gross revenue change?",
            DashboardContext(
                page="Executive Overview",
                current_period=JUNE,
                primary_metric="Revenue",
                revenue_basis="Gross",
            ),
            "comparison_period",
        ),
        ("Why did revenue change in May 2014 and June 2014?", None, "revenue_basis"),
        (
            "Compare gross revenue and net revenue from May 2014 to June 2014",
            None,
            "revenue_basis",
        ),
        (
            "Compare gross revenue in April 2014, May 2014, and June 2014",
            None,
            "current_period",
        ),
    ),
)
def test_missing_or_conflicting_scope_returns_one_clarification(
    question, context, field
):
    result = resolve_scope(question, context)

    assert isinstance(result, ClarificationRequest)
    assert result.field == field
    assert result.question.count("?") == 1


def test_context_requires_comparison_period_when_comparison_mode_is_selected():
    with pytest.raises(ValueError, match="Comparison period is required"):
        DashboardContext(
            page="Executive Overview",
            current_period=JUNE,
            comparison_mode="Previous period",
        )


def test_context_rejects_period_when_comparison_mode_is_none():
    with pytest.raises(ValueError, match="Comparison period must be absent"):
        DashboardContext(
            page="Executive Overview",
            current_period=JUNE,
            comparison_period=MAY,
        )


def test_context_and_resolved_scope_are_immutable():
    context = _overview_context()
    result = resolve_scope("Why did revenue change here?", context)

    assert isinstance(result, ResolvedScope)
    with pytest.raises(FrozenInstanceError):
        context.page = "Acquisition"
    with pytest.raises(FrozenInstanceError):
        result.revenue_basis = "Net"


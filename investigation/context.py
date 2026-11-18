from __future__ import annotations

from datetime import datetime
import re

from dashboard.models import DatePeriod, FilterSpec
from investigation.models import (
    ClarificationRequest,
    DashboardContext,
    ResolvedScope,
    RevenueBasis,
    ScopeSource,
)


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_MONTH_NAME_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_EXPLICIT_MONTH_PATTERNS = (
    re.compile(
        rf"\b(?P<month>{_MONTH_NAME_PATTERN})\.?\s+(?P<year>20\d{{2}})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<year>20\d{2})-(?P<month>0?[1-9]|1[0-2])\b"),
    re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<month>1[0-2]|0?[1-9])\s*月"),
)

_COMPARISON_TERMS = re.compile(
    r"\b(why|change|changed|compare|comparison|versus|vs\.?|decline|declined|"
    r"decrease|decreased|drop|dropped|increase|increased|grew|growth)\b|"
    r"为什么|变化|对比|比较|下降|下跌|减少|上涨|上升|增长",
    re.IGNORECASE,
)
_GROSS_TERMS = re.compile(r"\bgross\s+revenue\b|毛收入|总收入", re.IGNORECASE)
_NET_TERMS = re.compile(r"\bnet\s+revenue\b|净收入", re.IGNORECASE)


def _explicit_months(question: str) -> tuple[datetime, ...]:
    matches: list[tuple[int, datetime]] = []
    for pattern in _EXPLICIT_MONTH_PATTERNS:
        for match in pattern.finditer(question):
            month_token = match.group("month").lower().rstrip(".")
            month = (
                _MONTHS[month_token]
                if month_token in _MONTHS
                else int(month_token)
            )
            matches.append((match.start(), datetime(int(match.group("year")), month, 1)))

    ordered: list[datetime] = []
    for _, value in sorted(matches):
        if value not in ordered:
            ordered.append(value)
    return tuple(ordered)


def _month_period(value: datetime) -> DatePeriod:
    month = value.strftime("%Y-%m")
    return DatePeriod.from_months(month, month)


def _period_key(period: DatePeriod) -> tuple[datetime, datetime]:
    return period.start, period.end


def _revenue_basis(
    question: str, context: DashboardContext | None
) -> tuple[RevenueBasis | None, ScopeSource | None, ClarificationRequest | None]:
    has_gross = bool(_GROSS_TERMS.search(question))
    has_net = bool(_NET_TERMS.search(question))
    if has_gross and has_net:
        return None, None, ClarificationRequest(
            field="revenue_basis",
            question="Should I investigate Gross Revenue or Net Revenue?",
            reason="The question names both revenue bases.",
        )
    if has_gross:
        return "Gross", "question", None
    if has_net:
        return "Net", "question", None
    if context is not None and context.revenue_basis is not None:
        return context.revenue_basis, "dashboard", None

    metric = context.primary_metric.lower() if context and context.primary_metric else ""
    if metric == "gross revenue":
        return "Gross", "dashboard", None
    if metric == "net revenue":
        return "Net", "dashboard", None
    return None, None, ClarificationRequest(
        field="revenue_basis",
        question="Should I investigate Gross Revenue or Net Revenue?",
        reason="No revenue basis is explicit in the question or dashboard context.",
    )


def resolve_scope(
    question: str, context: DashboardContext | None = None
) -> ResolvedScope | ClarificationRequest:
    """Resolve a revenue question without calculating metrics or invoking a model."""

    normalized_question = " ".join(question.split())
    if not normalized_question:
        return ClarificationRequest(
            field="question",
            question="What revenue question would you like to investigate?",
            reason="The question is blank.",
        )

    basis, basis_source, basis_error = _revenue_basis(normalized_question, context)
    if basis_error is not None:
        return basis_error

    explicit_months = _explicit_months(normalized_question)
    requires_comparison = bool(_COMPARISON_TERMS.search(normalized_question)) or len(
        explicit_months
    ) == 2
    if len(explicit_months) > 2:
        return ClarificationRequest(
            field="current_period",
            question="Which two months should I compare?",
            reason="The question names more than two distinct months.",
        )

    current_period: DatePeriod | None
    comparison_period: DatePeriod | None
    current_source: ScopeSource
    comparison_source: ScopeSource | None

    if len(explicit_months) == 2:
        comparison_month, current_month = sorted(explicit_months)
        comparison_period = _month_period(comparison_month)
        current_period = _month_period(current_month)
        current_source = "question"
        comparison_source = "question"
    elif len(explicit_months) == 1:
        current_period = _month_period(explicit_months[0])
        current_source = "question"
        comparison_period = None
        comparison_source = None
        if requires_comparison:
            context_current_matches = (
                context is not None
                and context.current_period is not None
                and _period_key(context.current_period) == _period_key(current_period)
            )
            if context_current_matches and context.comparison_period is not None:
                comparison_period = context.comparison_period
                comparison_source = "dashboard"
            else:
                return ClarificationRequest(
                    field="comparison_period",
                    question="Which comparison period should I use?",
                    reason=(
                        "The question asks about a change but names only one month, and the "
                        "dashboard comparison does not safely apply to that month."
                    ),
                )
    else:
        if context is None or context.current_period is None:
            return ClarificationRequest(
                field="current_period",
                question="Which current period should I analyze?",
                reason="No current period is explicit or available from the dashboard.",
            )
        current_period = context.current_period
        current_source = "dashboard"
        comparison_period = context.comparison_period if requires_comparison else None
        comparison_source = (
            "dashboard" if requires_comparison and comparison_period is not None else None
        )

    if requires_comparison and comparison_period is None:
        return ClarificationRequest(
            field="comparison_period",
            question="Which comparison period should I use?",
            reason="The question asks about a change, but no comparison period is available.",
        )

    assert basis is not None
    assert basis_source is not None
    assert current_period is not None
    return ResolvedScope(
        question=normalized_question,
        current_period=current_period,
        comparison_period=comparison_period,
        filters=context.filters if context is not None else FilterSpec(),
        revenue_basis=basis,
        metric="net_revenue" if basis == "Net" else "gross_revenue",
        requires_comparison=requires_comparison,
        revenue_basis_source=basis_source,
        current_period_source=current_source,
        comparison_period_source=comparison_source,
    )


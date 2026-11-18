from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dashboard.models import DatePeriod, FilterSpec


ComparisonMode = Literal["None", "Previous period", "Previous year"]
RevenueBasis = Literal["Gross", "Net"]
ScopeSource = Literal["question", "dashboard"]
ClarificationField = Literal[
    "question",
    "revenue_basis",
    "current_period",
    "comparison_period",
]
ClaimLevel = Literal[
    "verified_fact",
    "observed_contribution",
    "interpretation",
    "hypothesis",
    "unknown",
]
FactKind = Literal["revenue_change", "contribution", "primary_contributor"]
FACT_LEVELS: frozenset[ClaimLevel] = frozenset(
    {"verified_fact", "observed_contribution"}
)
StopReason = Literal[
    "supported_conclusion",
    "data_boundary",
    "diminishing_information",
    "tool_budget_reached",
    "timeout",
    "validation_failure",
    "unsupported_capability",
    "minimum_sufficient_answer",
]


@dataclass(frozen=True)
class DashboardContext:
    """The small, read-only subset of dashboard state available to the agent."""

    page: str
    current_period: DatePeriod | None
    comparison_period: DatePeriod | None = None
    comparison_mode: ComparisonMode = "None"
    filters: FilterSpec = field(default_factory=FilterSpec)
    primary_metric: str | None = None
    revenue_basis: RevenueBasis | None = None
    page_controls: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.page.strip():
            raise ValueError("Dashboard context page must not be blank")
        if self.comparison_mode == "None" and self.comparison_period is not None:
            raise ValueError(
                "Comparison period must be absent when comparison mode is None"
            )
        if self.comparison_mode != "None" and self.comparison_period is None:
            raise ValueError(
                "Comparison period is required when a comparison mode is selected"
            )


@dataclass(frozen=True)
class ResolvedScope:
    """A complete revenue scope that deterministic tools can consume."""

    question: str
    current_period: DatePeriod
    comparison_period: DatePeriod | None
    filters: FilterSpec
    revenue_basis: RevenueBasis
    metric: Literal["gross_revenue", "net_revenue"]
    requires_comparison: bool
    revenue_basis_source: ScopeSource
    current_period_source: ScopeSource
    comparison_period_source: ScopeSource | None


@dataclass(frozen=True)
class ClarificationRequest:
    """A single missing or conflicting scope field that blocks safe resolution."""

    field: ClarificationField
    question: str
    reason: str


@dataclass(frozen=True)
class Claim:
    """One typed report statement with explicit evidence references.

    A verified_fact or observed_contribution claim names a fact kind, cites one
    evidence record, and carries no text: code renders its sentence from the
    evidence. Interpretation, hypothesis, and unknown claims carry model-written
    text and no fact kind.
    """

    text: str
    level: ClaimLevel
    evidence_ids: tuple[str, ...] = ()
    fact: FactKind | None = None
    key: str | None = None


@dataclass(frozen=True)
class InvestigationReport:
    """A provider-neutral report that can be validated independently."""

    scope: ResolvedScope
    claims: tuple[Claim, ...]
    stop_reason: StopReason



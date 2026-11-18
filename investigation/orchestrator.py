"""Bounded single-agent loop.

Classify, then either quote Data Guide definitions or resolve scope, call tools, validate,
and stop deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Callable, Literal

from investigation.definitions import Definition, lookup, topic_labels
from investigation.evidence import EvidenceRecord
from investigation.facts import render_claim, render_fact
from investigation.models import (
    Claim,
    ClarificationRequest,
    DashboardContext,
    InvestigationReport,
    ResolvedScope,
)
from investigation.context import resolve_scope
from investigation.providers import (
    ClassifyDecision,
    FinishDecision,
    LookupDecision,
    ModelClient,
    ModelView,
    ProviderError,
    ToolDecision,
)
from investigation.tools import InvestigationTools, ToolInputError, UnsupportedToolError
from investigation.validator import ValidationIssue, validate_report


SUPPORTED_ITEMS = (
    "investigate month-over-month Gross or Net revenue changes: confirm the change, "
    "decompose it into Sessions, Order rate and Gross AOV (plus recorded refunds for Net), "
    "and locate it by traffic source, campaign, device or session type",
    "quote the Data Guide definition of a dashboard metric, traffic source, campaign or table",
)
SUPPORTED_SCOPE = f"I can {SUPPORTED_ITEMS[0]}. I can also {SUPPORTED_ITEMS[1]}."
DEFINITION_MISS_REASON = "The Data Guide has no definition for that."
DEFINITION_ITEMS = (
    "the metrics on each dashboard page",
    "the derived traffic-source and campaign labels",
    "the six source tables",
)
DEFINITION_MISS = (
    f"{DEFINITION_MISS_REASON} It defines the metrics on each dashboard page, "
    "the derived traffic-source and campaign labels, and the six source tables. "
    "Ask about one of those, or ask me to investigate a month-over-month revenue change."
)
REFUSAL_REASONS = {
    "unsupported_capability": (
        "This request needs a capability the investigation tools do not have, such as "
        "significance testing, forecasting or taking an action."
    ),
    "unanswerable_from_data": (
        "The dataset cannot show real-world causes such as competitor pricing, ad budgets, "
        "promotions or site changes, so I will not claim one."
    ),
}
REFUSALS = {
    question_class: f"{reason} {SUPPORTED_SCOPE}"
    for question_class, reason in REFUSAL_REASONS.items()
}
STOP_TEXT = {
    "timeout": "The investigation reached its time limit.",
    "tool_budget_reached": "The investigation reached its tool-call limit.",
    "diminishing_information": "Further steps were adding no new evidence.",
}
ALLOWED_LEVELS = frozenset(
    {"verified_fact", "observed_contribution", "hypothesis", "unknown"}
)
FINISH_STOPS = frozenset(
    {"supported_conclusion", "minimum_sufficient_answer", "data_boundary"}
)


@dataclass(frozen=True)
class Budgets:
    max_tool_calls: int = 6
    max_repeated_calls: int = 1
    max_no_new_evidence: int = 2
    max_iterations: int = 12
    max_seconds: float = 90.0
    max_repairs: int = 1


@dataclass(frozen=True)
class TraceStep:
    index: int
    kind: str
    detail: str
    evidence_id: str | None = None
    new_evidence: bool | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class InvestigationResult:
    status: Literal["report", "definition", "clarification", "refusal", "failure"]
    stop_reason: str
    question_class: str | None
    trace: tuple[TraceStep, ...]
    evidence: tuple[EvidenceRecord, ...] = ()
    report: InvestigationReport | None = None
    sentences: tuple[str, ...] = ()
    clarification: ClarificationRequest | None = None
    refusal: str | None = None
    refusal_reason: str | None = None
    refusal_scope: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    model: str = ""
    definitions: tuple[Definition, ...] = ()


def trace_to_json(result: InvestigationResult) -> str:
    return json.dumps(
        {
            "model": result.model,
            "status": result.status,
            "stop_reason": result.stop_reason,
            "question_class": result.question_class,
            "trace": [step.__dict__ for step in result.trace],
            "issues": [issue.__dict__ for issue in result.issues],
        },
        ensure_ascii=False,
        indent=1,
    )


def _scope_summary(scope: ResolvedScope) -> str:
    comparison = scope.comparison_period.label if scope.comparison_period else "none"
    active = [
        f"{name}={values}"
        for name, values in vars(scope.filters).items()
        if values is not None
    ]
    return (
        f"{scope.revenue_basis} revenue, current {scope.current_period.label}, "
        f"comparison {comparison}, filters {', '.join(active) or 'none'}"
    )


def _describe(record: EvidenceRecord) -> str:
    payload = record.as_dict()
    if record.tool_name == "revenue_summary":
        claim = Claim("", "verified_fact", (record.evidence_id,), "revenue_change")
        return f"{record.evidence_id} (revenue_summary): {render_fact(claim, record)}"
    claim = Claim("", "observed_contribution", (record.evidence_id,), "primary_contributor")
    rows = payload.get("drivers", []) + payload.get("segments", [])
    keys = ", ".join(str(row.get("driver") or row.get("segment")) for row in rows)
    dimension = f", {payload['dimension']}" if "dimension" in payload else ""
    return (
        f"{record.evidence_id} ({record.tool_name}{dimension}): "
        f"{render_fact(claim, record)} Keys: {keys}."
    )


def investigate(
    question: str,
    tools: InvestigationTools,
    client: ModelClient,
    *,
    context: DashboardContext | None = None,
    budgets: Budgets = Budgets(),
    clock: Callable[[], float] = time.monotonic,
) -> InvestigationResult:
    start = clock()
    trace: list[TraceStep] = []
    registry = tools.registry
    seen: set[str] = set()

    def add(kind: str, detail: str, evidence_id=None, new=None) -> None:
        trace.append(
            TraceStep(len(trace) + 1, kind, detail, evidence_id, new, round(clock() - start, 3))
        )

    def result(status, stop_reason, question_class, **fields) -> InvestigationResult:
        return InvestigationResult(
            status,
            stop_reason,
            question_class,
            tuple(trace),
            registry.records,
            model=getattr(client, "name", ""),
            **fields,
        )

    def failure(code: str, question_class, issues=()) -> InvestigationResult:
        add("failure", code)
        return result("failure", code, question_class, issues=tuple(issues))

    def define(page: str | None) -> InvestigationResult:
        """Quote Data Guide definitions: the model picks labels, code supplies every word."""
        labels = topic_labels()
        scope_note = f"Current page: {page}" if page else "Current page: unknown"
        last_error: str | None = None
        for _ in range(budgets.max_repairs + 1):
            try:
                decision = client.decide(
                    ModelView("define", question, scope_note, (), 0, last_error, labels)
                )
            except ProviderError as error:
                add("provider_error", str(error))
                return failure("provider_error", "metric_definition")
            if not isinstance(decision, LookupDecision):
                return failure("unexpected_decision", "metric_definition")
            add("lookup", ", ".join(decision.topics) or "none")
            if not decision.topics:
                break
            found, unknown = lookup(decision.topics)
            if found:
                return result(
                    "definition",
                    "definition_answered",
                    "metric_definition",
                    sentences=tuple(definition.text for definition in found),
                    definitions=found,
                )
            add("lookup_rejected", ", ".join(unknown))
            last_error = (
                f"No Data Guide label matches {', '.join(unknown)}; "
                "copy a label from the list exactly or return no topics."
            )
        add("refusal", "no_matching_definition")
        return result(
            "refusal",
            "no_matching_definition",
            "metric_definition",
            refusal=DEFINITION_MISS,
            refusal_reason=DEFINITION_MISS_REASON,
            refusal_scope=(*DEFINITION_ITEMS, SUPPORTED_ITEMS[0]),
        )

    # 1. classify
    try:
        decision = client.decide(ModelView("classify", question, "", (), budgets.max_tool_calls, None))
    except ProviderError as error:
        add("provider_error", str(error))
        return failure("provider_error", None)
    if not isinstance(decision, ClassifyDecision):
        return failure("unexpected_decision", None)
    question_class = decision.question_class
    add("classify", question_class)
    if question_class in REFUSALS:
        add("refusal", question_class)
        return result(
            "refusal",
            question_class,
            question_class,
            refusal=REFUSALS[question_class],
            refusal_reason=REFUSAL_REASONS[question_class],
            refusal_scope=SUPPORTED_ITEMS,
        )
    if question_class == "metric_definition":
        return define(context.page if context else None)
    if question_class != "supported_investigation":
        return failure("unknown_question_class", question_class)

    # 2. resolve scope deterministically
    scope = resolve_scope(question, context)
    if isinstance(scope, ClarificationRequest):
        add("clarification", scope.field)
        return result("clarification", "needs_clarification", question_class, clarification=scope)
    add("scope", _scope_summary(scope))

    def stopped(reason: str) -> InvestigationResult:
        add("stop", reason)
        claims = [
            Claim("", "verified_fact", (record.evidence_id,), "revenue_change")
            if record.tool_name == "revenue_summary"
            else Claim("", "observed_contribution", (record.evidence_id,), "primary_contributor")
            for record in registry.records
        ]
        claims.append(
            Claim(
                f"{STOP_TEXT[reason]} Branches that were not checked remain unknown.",
                "unknown",
            )
        )
        report = InvestigationReport(scope, tuple(claims), reason)  # type: ignore[arg-type]
        outcome = validate_report(report, registry)
        if not outcome.passed:
            return failure("validation_failure", question_class, outcome.issues)
        return _report_result(report, reason)

    def _report_result(report: InvestigationReport, reason: str) -> InvestigationResult:
        sentences = tuple(render_claim(claim, registry) for claim in report.claims)
        return result("report", reason, question_class, report=report, sentences=sentences)

    # 3. bounded tool loop
    calls: set[tuple] = set()
    tool_calls = repeats = no_new = repairs = 0
    last_error: str | None = None
    for _ in range(budgets.max_iterations):
        if clock() - start > budgets.max_seconds:
            return stopped("timeout")
        view = ModelView(
            "investigate",
            question,
            _scope_summary(scope),
            tuple(_describe(record) for record in registry.records),
            budgets.max_tool_calls - tool_calls,
            last_error,
        )
        last_error = None
        try:
            decision = client.decide(view)
        except ProviderError as error:
            add("provider_error", str(error))
            return failure("provider_error", question_class)

        if isinstance(decision, ToolDecision):
            signature = (decision.tool, tuple(sorted(decision.arguments.items())))
            label = f"{decision.tool} {dict(decision.arguments)}"
            if signature in calls:
                repeats += 1
                no_new += 1
                add("repeated_call", label, new=False)
                if repeats > budgets.max_repeated_calls or no_new >= budgets.max_no_new_evidence:
                    return stopped("diminishing_information")
                last_error = f"{label} was already called; do not repeat calls."
                continue
            if tool_calls >= budgets.max_tool_calls:
                return stopped("tool_budget_reached")
            tool_calls += 1
            calls.add(signature)
            try:
                record = tools.call(decision.tool, scope, **decision.arguments)
            except (ToolInputError, UnsupportedToolError, TypeError) as error:
                no_new += 1
                add("tool_error", f"{label}: {error}", new=False)
                if no_new >= budgets.max_no_new_evidence:
                    return stopped("diminishing_information")
                last_error = f"{label} failed: {error}"
                continue
            is_new = record.evidence_id not in seen
            seen.add(record.evidence_id)
            no_new = 0 if is_new else no_new + 1
            add("tool_call", label, record.evidence_id, is_new)
            if no_new >= budgets.max_no_new_evidence:
                return stopped("diminishing_information")
            continue

        if isinstance(decision, FinishDecision):
            issues = _finish_issues(decision)
            report = InvestigationReport(scope, decision.claims, decision.stop_reason)  # type: ignore[arg-type]
            if not issues:
                issues = list(validate_report(report, registry).issues)
            if not issues:
                add("finish", decision.stop_reason)
                return _report_result(report, decision.stop_reason)
            add("validation_rejected", "; ".join(sorted({issue.code for issue in issues})))
            if repairs >= budgets.max_repairs:
                return failure("validation_failure", question_class, issues)
            repairs += 1
            last_error = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)[:700]
            continue

        return failure("unexpected_decision", question_class)

    return stopped("diminishing_information")


def _finish_issues(decision: FinishDecision) -> list[ValidationIssue]:
    issues = [
        ValidationIssue("claim_level_not_allowed", f"Level {claim.level!r} is not available.")
        for claim in decision.claims
        if claim.level not in ALLOWED_LEVELS
    ]
    if decision.stop_reason not in FINISH_STOPS:
        issues.append(
            ValidationIssue(
                "invalid_stop_reason",
                f"stop_reason must be one of {sorted(FINISH_STOPS)}.",
            )
        )
    return issues

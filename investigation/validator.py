from __future__ import annotations

from calendar import month_abbr, month_name
from dataclasses import dataclass
import math
import re

from investigation.evidence import EvidenceRecord, EvidenceRegistry
from investigation.facts import FACT_TEMPLATES, FactError, render_fact
from investigation.models import FACT_LEVELS, Claim, InvestigationReport, ResolvedScope


# Lexical backstops for free-text interpretation claims. The structural guarantee is
# that fact claims carry no text; these lists only narrow what prose can still say.
_CAUSAL_LANGUAGE = re.compile(
    r"\b(?:caus(?:e|es|ed|ing)|because|due to|owing to|thanks to|on account of|"
    r"as a result|result(?:s|ed|ing)? (?:in|from)|(?:led|leads?|leading) to|"
    r"drives?|drove|driving|driven by|attribut(?:able|ed|es|ing) to|"
    r"explain(?:s|ed|ing)?|reasons?|responsible for|trigger(?:s|ed|ing)?|"
    r"stem(?:s|med|ming)? from)\b|"
    r"导致|造成|因为|由于|因此|原因|归因|归咎|引起|致使|使得|驱动|源于|所致",
    re.IGNORECASE,
)
_RANKING_LANGUAGE = re.compile(
    r"\b(?:largest|biggest|greatest|dominant|principal)\b|最大|首要|最主要",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")
_CONCLUSIVE_STOPS = frozenset({"supported_conclusion", "minimum_sufficient_answer"})
_BOUNDARY_STOPS = frozenset(
    {"data_boundary", "diminishing_information", "tool_budget_reached", "timeout"}
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    evidence_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def _close(left: object, right: object, *, tolerance: float = 0.005) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def validate_evidence(record: EvidenceRecord) -> ValidationResult:
    payload = record.as_dict()
    issues: list[ValidationIssue] = []
    try:
        if record.tool_name == "revenue_summary":
            current = payload["current_revenue"]
            comparison = payload["comparison_revenue"]
            absolute_change = payload["absolute_change"]
            relative_change = payload["relative_change"]
            if comparison is None:
                if absolute_change is not None or relative_change is not None:
                    issues.append(
                        ValidationIssue(
                            "summary_without_comparison",
                            "A single-period summary cannot report comparison changes.",
                            record.evidence_id,
                        )
                    )
            else:
                expected_change = float(current) - float(comparison)
                if not _close(absolute_change, expected_change):
                    issues.append(
                        ValidationIssue(
                            "absolute_change_mismatch",
                            "Revenue change does not equal current minus comparison.",
                            record.evidence_id,
                        )
                    )
                if float(comparison) == 0:
                    if relative_change is not None:
                        issues.append(
                            ValidationIssue(
                                "zero_comparison_relative_change",
                                "Relative change must be unavailable when comparison is zero.",
                                record.evidence_id,
                            )
                        )
                elif not _close(relative_change, expected_change / float(comparison)):
                    issues.append(
                        ValidationIssue(
                            "relative_change_mismatch",
                            "Relative change does not match the period values.",
                            record.evidence_id,
                        )
                    )
        elif record.tool_name in {"revenue_decomposition", "segment_contributions"}:
            if not _close(payload["contribution_sum"], payload["observed_change"]):
                issues.append(
                    ValidationIssue(
                        "contribution_reconciliation_failed",
                        "Contributions do not reconcile to the observed revenue change.",
                        record.evidence_id,
                    )
                )
            expected_error = float(payload["contribution_sum"]) - float(
                payload["observed_change"]
            )
            if not _close(payload["reconciliation_error"], expected_error):
                issues.append(
                    ValidationIssue(
                        "reconciliation_error_mismatch",
                        "Reported reconciliation error is inconsistent with the evidence.",
                        record.evidence_id,
                    )
                )
        else:
            issues.append(
                ValidationIssue(
                    "unregistered_evidence_tool",
                    f"Evidence came from an unregistered tool: {record.tool_name}",
                    record.evidence_id,
                )
            )
    except (KeyError, TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "invalid_evidence_schema",
                "Evidence payload is missing required fields or contains invalid values.",
                record.evidence_id,
            )
        )
    return ValidationResult(tuple(issues))


def _period_tokens(scope: ResolvedScope) -> tuple[str, ...]:
    """Period labels and month names that may appear in prose without being a quantity."""
    tokens: set[str] = set()
    for period in (scope.current_period, scope.comparison_period):
        if period is None:
            continue
        tokens.add(period.label)
        first = period.start.year * 12 + period.start.month - 1
        for index in range(first, first + period.month_count):
            year, zero_based_month = divmod(index, 12)
            month = zero_based_month + 1
            tokens.update(
                {
                    f"{month_name[month]} {year}",
                    f"{month_abbr[month]} {year}",
                    f"{year}-{month:02d}",
                    str(year),
                }
            )
    return tuple(sorted(tokens, key=len, reverse=True))


def _has_uncited_number(text: str, scope: ResolvedScope) -> bool:
    for token in _period_tokens(scope):
        text = re.sub(re.escape(token), " ", text, flags=re.IGNORECASE)
    return _NUMBER.search(text) is not None


def _fact_issues(claim: Claim, records: list[EvidenceRecord]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if claim.text:
        issues.append(
            ValidationIssue(
                "fact_claim_has_free_text",
                "Fact claims carry no text; code renders the sentence from evidence.",
            )
        )
    if len(claim.evidence_ids) > 1:
        issues.append(
            ValidationIssue(
                "fact_requires_single_evidence",
                "A fact claim cites exactly one evidence record.",
            )
        )
    if claim.fact not in FACT_TEMPLATES:
        issues.append(
            ValidationIssue(
                "unknown_fact_kind",
                f"Fact claims must name one of {sorted(FACT_TEMPLATES)}.",
            )
        )
    elif len(claim.evidence_ids) == 1 and len(records) == 1:
        try:
            render_fact(claim, records[0])
        except FactError as error:
            issues.append(ValidationIssue(error.code, str(error), records[0].evidence_id))
    return issues


def _free_text_issues(claim: Claim, scope: ResolvedScope) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if claim.fact is not None or claim.key is not None:
        issues.append(
            ValidationIssue(
                "free_text_claim_has_fact_fields",
                f"{claim.level} claims carry text, not a fact kind or key.",
            )
        )
    if not claim.text.strip():
        issues.append(
            ValidationIssue("empty_claim_text", f"{claim.level} claims need text.")
        )
    if _has_uncited_number(claim.text, scope):
        issues.append(
            ValidationIssue(
                "uncited_number",
                "Numbers appear only in fact claims, which code renders from evidence.",
            )
        )
    if claim.level == "interpretation":
        if _CAUSAL_LANGUAGE.search(claim.text):
            issues.append(
                ValidationIssue(
                    "unsupported_causal_language",
                    "Causal language belongs in a hypothesis, or in an unknown claim "
                    "that denies knowledge.",
                )
            )
        if _RANKING_LANGUAGE.search(claim.text):
            issues.append(
                ValidationIssue(
                    "unsupported_ranking_language",
                    "Rankings are stated with a primary_contributor fact claim.",
                )
            )
    return issues


def _claim_issues(
    claim: Claim, scope: ResolvedScope, registry: EvidenceRegistry
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    is_fact = claim.level in FACT_LEVELS
    if is_fact and not claim.evidence_ids:
        issues.append(
            ValidationIssue(
                "missing_evidence_reference",
                f"{claim.level} claims require an Evidence ID.",
            )
        )
    records: list[EvidenceRecord] = []
    for evidence_id in claim.evidence_ids:
        record = registry.get(evidence_id)
        if record is None:
            issues.append(
                ValidationIssue(
                    "unknown_evidence_reference",
                    f"Claim references unknown evidence: {evidence_id}",
                    evidence_id,
                )
            )
        elif record.scope != scope:
            issues.append(
                ValidationIssue(
                    "evidence_scope_mismatch",
                    "Claim evidence was calculated for a different resolved scope.",
                    evidence_id,
                )
            )
        else:
            records.append(record)
    issues.extend(
        _fact_issues(claim, records) if is_fact else _free_text_issues(claim, scope)
    )
    return issues


def _completeness_issues(report: InvestigationReport) -> list[ValidationIssue]:
    if not report.claims:
        return [ValidationIssue("empty_report", "A report needs at least one claim.")]
    levels = {claim.level for claim in report.claims}
    if report.stop_reason in _CONCLUSIVE_STOPS and not levels & FACT_LEVELS:
        return [
            ValidationIssue(
                "conclusion_without_fact",
                f"A {report.stop_reason} stop needs at least one evidence-backed fact claim.",
            )
        ]
    if report.stop_reason in _BOUNDARY_STOPS and "unknown" not in levels:
        return [
            ValidationIssue(
                "boundary_without_unknown",
                f"A {report.stop_reason} stop must state what remains unknown.",
            )
        ]
    return []


def validate_report(
    report: InvestigationReport, registry: EvidenceRegistry
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    for claim in report.claims:
        issues.extend(_claim_issues(claim, report.scope, registry))
    issues.extend(_completeness_issues(report))

    cited = dict.fromkeys(
        evidence_id for claim in report.claims for evidence_id in claim.evidence_ids
    )
    for evidence_id in cited:
        record = registry.get(evidence_id)
        if record is not None:
            issues.extend(validate_evidence(record).issues)
    return ValidationResult(tuple(issues))


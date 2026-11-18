import pytest

from investigation.context import resolve_scope
from investigation.evidence import EvidenceRegistry
from investigation.models import Claim, InvestigationReport, ResolvedScope
from investigation.tools import InvestigationTools
from investigation.validator import validate_evidence, validate_report


def _scope(
    question: str = "Why did gross revenue change from May 2014 to June 2014?",
) -> ResolvedScope:
    result = resolve_scope(question)
    assert isinstance(result, ResolvedScope)
    return result


def _report(
    *claims: Claim, stop: str = "supported_conclusion", scope: ResolvedScope | None = None
) -> InvestigationReport:
    return InvestigationReport(
        scope=scope or _scope(), claims=claims, stop_reason=stop
    )


def _codes(report: InvestigationReport, registry: EvidenceRegistry) -> set[str]:
    return {issue.code for issue in validate_report(report, registry).issues}


def _text_only(level: str, text: str) -> InvestigationReport:
    # An unsupported_capability stop needs only a non-empty report.
    return _report(Claim(text, level), stop="unsupported_capability")


@pytest.fixture
def grounded(analytics_db):
    registry = EvidenceRegistry()
    tools = InvestigationTools(analytics_db, registry)
    scope = _scope()
    return registry, {
        "summary": tools.revenue_summary(scope).evidence_id,
        "decomposition": tools.revenue_decomposition(scope).evidence_id,
        "segments": tools.segment_contributions(scope, dimension="Device").evidence_id,
    }


def test_validator_accepts_grounded_fact_report(grounded):
    registry, ids = grounded
    segment = registry.get(ids["segments"]).as_dict()["segments"][0]["segment"]
    report = _report(
        Claim("", "verified_fact", (ids["summary"],), "revenue_change"),
        Claim("", "observed_contribution", (ids["decomposition"],), "primary_contributor"),
        Claim("", "observed_contribution", (ids["decomposition"],), "contribution", "Sessions"),
        Claim("", "observed_contribution", (ids["segments"],), "contribution", segment),
        Claim("The change is spread across several measures.", "interpretation"),
        Claim("A campaign change may have caused lower sessions.", "hypothesis"),
        Claim("The dataset has no ad-spend or release calendar.", "unknown"),
    )

    result = validate_report(report, registry)

    assert result.passed
    assert result.issues == ()


def test_validator_rejects_missing_unknown_and_wrong_scope_evidence(grounded):
    registry, ids = grounded
    net_scope = _scope("Why did net revenue change from May 2014 to June 2014?")
    report = _report(
        Claim("", "verified_fact", (), "revenue_change"),
        Claim("", "verified_fact", ("EV-999",), "revenue_change"),
        Claim("", "verified_fact", (ids["summary"],), "revenue_change"),
        stop="validation_failure",
        scope=net_scope,
    )

    codes = _codes(report, registry)

    assert {
        "missing_evidence_reference",
        "unknown_evidence_reference",
        "evidence_scope_mismatch",
    } <= codes


MALFORMED_FACT_CLAIMS = {
    "free text on a fact claim": (
        lambda ids: Claim("Revenue fell.", "verified_fact", (ids["summary"],), "revenue_change"),
        "fact_claim_has_free_text",
    ),
    "fact claim without a kind": (
        lambda ids: Claim("", "verified_fact", (ids["summary"],)),
        "unknown_fact_kind",
    ),
    "level that does not match the kind": (
        lambda ids: Claim("", "observed_contribution", (ids["summary"],), "revenue_change"),
        "fact_level_mismatch",
    ),
    "evidence from the wrong tool": (
        lambda ids: Claim("", "observed_contribution", (ids["summary"],), "primary_contributor"),
        "evidence_tool_mismatch",
    ),
    "contribution without a key": (
        lambda ids: Claim("", "observed_contribution", (ids["decomposition"],), "contribution"),
        "fact_key_required",
    ),
    "key on a kind that takes none": (
        lambda ids: Claim(
            "", "observed_contribution", (ids["decomposition"],), "primary_contributor", "Sessions"
        ),
        "unexpected_fact_key",
    ),
    "key the evidence does not contain": (
        lambda ids: Claim(
            "", "observed_contribution", (ids["decomposition"],), "contribution", "Not a driver"
        ),
        "unknown_fact_key",
    ),
    "several evidence records on one fact": (
        lambda ids: Claim(
            "", "verified_fact", (ids["summary"], ids["decomposition"]), "revenue_change"
        ),
        "fact_requires_single_evidence",
    ),
}


@pytest.mark.parametrize(
    "build, code", MALFORMED_FACT_CLAIMS.values(), ids=MALFORMED_FACT_CLAIMS.keys()
)
def test_malformed_fact_claims_are_rejected(grounded, build, code):
    registry, ids = grounded

    assert code in _codes(_report(build(ids)), registry)


def test_free_text_claims_cannot_carry_fact_fields_or_be_empty(grounded):
    registry, _ = grounded
    fact_fields = _report(
        Claim("Order rate moved.", "interpretation", (), "revenue_change"),
        stop="unsupported_capability",
    )
    key_only = _report(
        Claim("Order rate moved.", "interpretation", (), None, "Sessions"),
        stop="unsupported_capability",
    )

    assert "free_text_claim_has_fact_fields" in _codes(fact_fields, registry)
    assert "free_text_claim_has_fact_fields" in _codes(key_only, registry)
    assert "empty_claim_text" in _codes(_text_only("unknown", "   "), registry)


@pytest.mark.parametrize("level", ["interpretation", "hypothesis", "unknown"])
@pytest.mark.parametrize(
    "text",
    [
        "Revenue fell by $1,234.56.",
        "Revenue is down 40% on the prior period.",
        "Order rate dropped to 3.2 percent.",
        "Three of the 4 segments moved together.",
        "In 2013 revenue was higher.",
        "Q2 looked weak.",
        "下降了４０％。",
    ],
)
def test_numbers_outside_the_scope_periods_are_rejected_in_free_text(grounded, level, text):
    registry, _ = grounded

    assert "uncited_number" in _codes(_text_only(level, text), registry)


@pytest.mark.parametrize(
    "text",
    [
        "Between May 2014 and June 2014 the movement was mostly in conversion.",
        "Jun 1–Jun 30, 2014 is the period under review.",
        "2014-06 is the current month.",
        "The movement is concentrated in conversion rather than traffic.",
    ],
)
def test_period_references_and_plain_prose_are_not_numbers(grounded, text):
    registry, _ = grounded

    assert validate_report(_text_only("interpretation", text), registry).passed


CAUSAL_INTERPRETATIONS = [
    "Lower sessions caused the revenue decline.",
    "Revenue fell because traffic fell.",
    "Revenue fell due to lower paid-search traffic.",
    "Revenue fell as a result of lower traffic.",
    "Revenue declined on account of weaker traffic.",
    "The decline stems from a weaker order rate.",
    "Weaker traffic triggered the drop.",
    "Higher refunds are responsible for the lower net revenue.",
    "The decline resulted from fewer orders.",
    "The decline is attributable to fewer sessions.",
    "Lower traffic explains the decline.",
    "The drop was driven by a weaker order rate.",
    "Lower traffic is the reason revenue fell.",
    "流量下降导致收入下降。",
    "收入下降是由于广告预算减少。",
    "下降的原因是流量减少。",
    "收入下降源于渠道流量减少。",
    "收入下降归因于渠道流量下降。",
]


@pytest.mark.parametrize("text", CAUSAL_INTERPRETATIONS)
def test_causal_language_is_rejected_in_interpretations(grounded, text):
    registry, _ = grounded

    assert "unsupported_causal_language" in _codes(
        _text_only("interpretation", text), registry
    )


@pytest.mark.parametrize("level", ["hypothesis", "unknown"])
@pytest.mark.parametrize(
    "text",
    [
        "A campaign change may have caused lower sessions.",
        "The dataset cannot show what caused the decline.",
        "数据无法说明收入下降的原因。",
    ],
)
def test_hypotheses_and_unknowns_may_name_causes(grounded, level, text):
    registry, _ = grounded

    assert validate_report(_text_only(level, text), registry).passed


@pytest.mark.parametrize(
    "text",
    [
        "Revenue drivers here are accounting contributions, not causal effects.",
        "The change is spread across sessions, order rate, and gross AOV.",
        "Traffic and conversion moved in opposite directions.",
    ],
)
def test_neutral_interpretations_are_not_flagged(grounded, text):
    registry, _ = grounded

    assert validate_report(_text_only("interpretation", text), registry).passed


@pytest.mark.parametrize(
    "text",
    [
        "Sessions was the largest contributor to the change.",
        "The biggest movement was in conversion.",
        "转化率变化最大。",
    ],
)
def test_ranking_language_belongs_in_a_primary_contributor_fact(grounded, text):
    registry, _ = grounded

    assert "unsupported_ranking_language" in _codes(
        _text_only("interpretation", text), registry
    )
    assert validate_report(_text_only("hypothesis", text), registry).passed


def test_reports_need_content_that_matches_their_stop_reason(grounded):
    registry, ids = grounded
    fact = Claim("", "verified_fact", (ids["summary"],), "revenue_change")
    note = Claim("The change is spread across several measures.", "interpretation")
    unknown = Claim("The dataset has no ad-spend data.", "unknown")

    assert "empty_report" in _codes(_report(), registry)
    for stop in ("supported_conclusion", "minimum_sufficient_answer"):
        assert "conclusion_without_fact" in _codes(_report(note, stop=stop), registry)
        assert validate_report(_report(fact, stop=stop), registry).passed
    for stop in (
        "data_boundary",
        "diminishing_information",
        "tool_budget_reached",
        "timeout",
    ):
        assert "boundary_without_unknown" in _codes(_report(fact, stop=stop), registry)
        assert validate_report(_report(fact, unknown, stop=stop), registry).passed
    assert validate_report(_report(unknown, stop="unsupported_capability"), registry).passed


def test_evidence_validator_rejects_tampered_reconciliation():
    registry = EvidenceRegistry()
    record = registry.register(
        "revenue_decomposition",
        _scope(),
        {
            "observed_change": 100.0,
            "contribution_sum": 90.0,
            "reconciliation_error": -10.0,
            "drivers": [],
        },
    )

    result = validate_evidence(record)

    assert not result.passed
    assert {issue.code for issue in result.issues} == {
        "contribution_reconciliation_failed"
    }


def test_evidence_validator_rejects_unregistered_tool():
    registry = EvidenceRegistry()
    record = registry.register("arbitrary_sql", _scope(), {"value": 1})

    result = validate_evidence(record)

    assert not result.passed
    assert result.issues[0].code == "unregistered_evidence_tool"

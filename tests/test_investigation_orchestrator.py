import itertools
import json
from types import SimpleNamespace

import pytest

from dashboard.models import DatePeriod
from investigation.definitions import CATALOG, MAX_DEFINITIONS, topic_labels
from investigation.evidence import EvidenceRegistry
from investigation.models import Claim, DashboardContext
from investigation.orchestrator import (
    DEFINITION_MISS,
    REFUSALS,
    Budgets,
    investigate,
    trace_to_json,
)
from investigation.prompts import build_prompt
from investigation.providers import (
    ClassifyDecision,
    FinishDecision,
    GeminiClient,
    LookupDecision,
    ModelView,
    ProviderError,
    ScriptedClient,
    ToolDecision,
)
from investigation.tools import InvestigationTools

QUESTION = "Why did gross revenue change from May 2014 to June 2014?"
CLASSIFY = ClassifyDecision("supported_investigation")
SUMMARY = ToolDecision("revenue_summary")
DECOMPOSITION = ToolDecision("revenue_decomposition")
SEGMENTS = ToolDecision("segment_contributions", {"dimension": "Device"})
GOOD_FINISH = FinishDecision(
    (
        Claim("", "verified_fact", ("EV-001",), "revenue_change"),
        Claim("", "observed_contribution", ("EV-002",), "primary_contributor"),
        Claim("A campaign change may have lowered sessions.", "hypothesis"),
        Claim("The dataset has no ad-spend data.", "unknown"),
    ),
    "supported_conclusion",
)


def _run(analytics_db, decisions, question=QUESTION, **options):
    client = ScriptedClient(decisions)
    tools = InvestigationTools(analytics_db, EvidenceRegistry())
    return investigate(question, tools, client, **options), client


def _kinds(result):
    return [step.kind for step in result.trace]


def test_supported_investigation_returns_a_validated_report(analytics_db):
    result, client = _run(
        analytics_db, [CLASSIFY, SUMMARY, DECOMPOSITION, GOOD_FINISH]
    )

    assert result.status == "report"
    assert result.stop_reason == "supported_conclusion"
    assert _kinds(result) == ["classify", "scope", "tool_call", "tool_call", "finish"]
    assert result.sentences[0].startswith("Gross revenue was $0.00 in Jun 1")
    assert len(result.sentences) == 4
    assert len(client.views[2].evidence) == 1
    assert client.views[3].tools_left == 4
    assert all(step.new_evidence for step in result.trace if step.kind == "tool_call")


def test_missing_scope_asks_one_question_without_investigating(analytics_db):
    result, client = _run(analytics_db, [CLASSIFY], question="Why did revenue change?")

    assert result.status == "clarification"
    assert result.clarification.field == "revenue_basis"
    assert len(client.views) == 1
    assert result.evidence == ()


@pytest.mark.parametrize("question_class", sorted(REFUSALS))
def test_unsupported_and_unanswerable_questions_get_fixed_refusals(
    analytics_db, question_class
):
    result, client = _run(analytics_db, [ClassifyDecision(question_class)])

    assert result.status == "refusal"
    assert result.refusal == REFUSALS[question_class]
    assert "month-over-month" in result.refusal
    assert result.evidence == ()
    assert len(client.views) == 1


def test_unknown_question_class_is_a_failure(analytics_db):
    result, _ = _run(analytics_db, [ClassifyDecision("write_poetry")])

    assert (result.status, result.stop_reason) == ("failure", "unknown_question_class")


def test_tool_budget_stops_with_a_partial_validated_report(analytics_db):
    result, _ = _run(
        analytics_db,
        [CLASSIFY, SUMMARY, DECOMPOSITION, SEGMENTS],
        budgets=Budgets(max_tool_calls=2),
    )

    assert result.status == "report"
    assert result.stop_reason == "tool_budget_reached"
    assert _kinds(result)[-1] == "stop"
    assert len(result.evidence) == 2
    assert result.report.claims[-1].level == "unknown"
    assert "remain unknown" in result.sentences[-1]


def test_repeated_calls_are_not_executed_and_end_the_run(analytics_db):
    result, client = _run(analytics_db, [CLASSIFY, SUMMARY, SUMMARY, SUMMARY])

    assert result.stop_reason == "diminishing_information"
    assert _kinds(result).count("tool_call") == 1
    assert _kinds(result).count("repeated_call") == 2
    assert "already called" in client.views[3].last_error
    assert len(result.evidence) == 1


def test_bad_tools_and_arguments_are_reported_back_and_recoverable(analytics_db):
    result, client = _run(
        analytics_db,
        [
            CLASSIFY,
            ToolDecision("arbitrary_sql"),
            ToolDecision("segment_contributions", {"dimension": "Zip code"}),
            SUMMARY,
            DECOMPOSITION,
            GOOD_FINISH,
        ],
        budgets=Budgets(max_no_new_evidence=3),
    )

    assert result.status == "report"
    assert _kinds(result).count("tool_error") == 2
    assert "not registered" in client.views[2].last_error
    assert "Unsupported segment dimension" in client.views[3].last_error


def test_consecutive_tool_errors_stop_the_run(analytics_db):
    result, _ = _run(
        analytics_db,
        [CLASSIFY, ToolDecision("arbitrary_sql"), ToolDecision("revenue_summary", {"x": 1})],
    )

    assert result.stop_reason == "diminishing_information"
    assert _kinds(result).count("tool_error") == 2


def test_a_rejected_report_is_repaired_once(analytics_db):
    bad = FinishDecision(
        (Claim("Revenue fell by a lot.", "interpretation"),), "supported_conclusion"
    )
    result, client = _run(
        analytics_db, [CLASSIFY, SUMMARY, DECOMPOSITION, bad, GOOD_FINISH]
    )

    assert result.status == "report"
    assert "validation_rejected" in _kinds(result)
    assert "claim_level_not_allowed" in client.views[4].last_error


def test_a_report_that_stays_invalid_is_withheld(analytics_db):
    bad = FinishDecision(
        (
            Claim("", "verified_fact", ("EV-001",), "revenue_change"),
            Claim("Revenue fell by $1,234.", "unknown"),
        ),
        "data_boundary",
    )
    result, _ = _run(analytics_db, [CLASSIFY, SUMMARY, bad, bad])

    assert result.status == "failure"
    assert result.stop_reason == "validation_failure"
    assert result.report is None
    assert "uncited_number" in {issue.code for issue in result.issues}


def test_finish_stop_reason_must_be_a_finishing_one(analytics_db):
    bad = FinishDecision(GOOD_FINISH.claims, "timeout")
    result, client = _run(
        analytics_db,
        [CLASSIFY, SUMMARY, DECOMPOSITION, bad, GOOD_FINISH],
    )

    assert result.status == "report"
    assert "invalid_stop_reason" in client.views[4].last_error


def test_time_budget_stops_the_run(analytics_db):
    ticks = itertools.count(0, 3)
    result, _ = _run(
        analytics_db,
        [CLASSIFY, SUMMARY, GOOD_FINISH],
        budgets=Budgets(max_seconds=5),
        clock=lambda: float(next(ticks)),
    )

    assert result.stop_reason == "timeout"
    assert result.status == "report"
    assert result.report.claims[-1].level == "unknown"


def test_iteration_budget_ends_a_run_that_never_finishes(analytics_db):
    result, _ = _run(
        analytics_db,
        [CLASSIFY, SUMMARY, DECOMPOSITION, SEGMENTS],
        budgets=Budgets(max_iterations=2),
    )

    assert result.stop_reason == "diminishing_information"
    assert result.status == "report"
    assert len(result.evidence) == 2


def test_provider_errors_become_structured_failures(analytics_db):
    first, _ = _run(analytics_db, [ProviderError("down")])
    later, _ = _run(analytics_db, [CLASSIFY, ProviderError("down")])

    assert (first.status, first.stop_reason) == ("failure", "provider_error")
    assert (later.status, later.stop_reason) == ("failure", "provider_error")


def test_trace_is_serializable_and_names_the_model(analytics_db):
    result, _ = _run(analytics_db, [CLASSIFY, SUMMARY, DECOMPOSITION, GOOD_FINISH])

    saved = json.loads(trace_to_json(result))

    assert saved["model"] == "scripted"
    assert saved["stop_reason"] == "supported_conclusion"
    assert [step["kind"] for step in saved["trace"]][0] == "classify"


class _FakeGenai:
    def __init__(self, text, usage=None):
        self._usage = usage or SimpleNamespace(
            prompt_token_count=11, candidates_token_count=5, thoughts_token_count=7
        )
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._text = text

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            text=self._text,
            usage_metadata=self._usage,
        )


def _decide(text, phase="investigate"):
    fake = _FakeGenai(text)
    client = GeminiClient("project", client=fake)
    view = ModelView(phase, QUESTION, "scope", ("EV-001 (revenue_summary): x",), 5, None)
    return client, fake, client.decide(view)


def test_gemini_client_parses_each_kind_of_step():
    _, fake, classify = _decide('{"action":"classify","question_class":"unsupported_capability"}', "classify")
    _, _, tool = _decide('{"action":"call_tool","tool":"segment_contributions","dimension":"Device"}')
    client, _, finish = _decide(
        '{"action":"finish","stop_reason":"supported_conclusion","claims":['
        '{"level":"verified_fact","fact":"revenue_change","evidence_id":"EV-001"},'
        '{"level":"unknown","text":"No ad data."}]}'
    )

    assert classify == ClassifyDecision("unsupported_capability")
    assert tool == ToolDecision("segment_contributions", {"dimension": "Device"})
    assert finish.claims == (
        Claim("", "verified_fact", ("EV-001",), "revenue_change"),
        Claim("No ad data.", "unknown"),
    )
    assert (client.input_tokens, client.output_tokens) == (11, 5)
    assert (client.thinking_tokens, client.calls, client.usage_missing) == (7, 1, False)
    assert QUESTION in fake.calls[0]["contents"]


def test_gemini_client_flags_missing_usage_instead_of_pretending_it_is_zero():
    fake = _FakeGenai(
        '{"action":"call_tool","tool":"revenue_summary"}',
        usage=SimpleNamespace(prompt_token_count=None, candidates_token_count=None),
    )
    client = GeminiClient("project", client=fake)

    client.decide(ModelView("investigate", QUESTION, "scope", (), 5, None))

    assert client.usage_missing is True


def test_gemini_client_reports_unusable_output_as_provider_error():
    with pytest.raises(ProviderError):
        _decide("not json")


DEFINE = ClassifyDecision("metric_definition")
REVENUE_TOPIC = "Executive Overview / Revenue"
PAGE_CONTEXT = DashboardContext("Acquisition", DatePeriod.from_months("2014-06", "2014-06"))


def test_definition_question_quotes_the_data_guide_without_tools(analytics_db):
    result, client = _run(
        analytics_db,
        [DEFINE, LookupDecision((REVENUE_TOPIC,))],
        question="What is gross revenue?",
        context=PAGE_CONTEXT,
    )

    assert (result.status, result.stop_reason) == ("definition", "definition_answered")
    assert result.sentences == (CATALOG[REVENUE_TOPIC].text,)
    assert [definition.topic for definition in result.definitions] == [REVENUE_TOPIC]
    assert result.evidence == () and result.report is None
    assert _kinds(result) == ["classify", "lookup"]
    view = client.views[1]
    assert view.phase == "define" and REVENUE_TOPIC in view.topics
    assert "Acquisition" in view.scope_summary


def test_an_unknown_topic_label_is_repaired_once(analytics_db):
    result, client = _run(
        analytics_db,
        [DEFINE, LookupDecision(("Gross revenue",)), LookupDecision((REVENUE_TOPIC,))],
    )

    assert result.status == "definition"
    assert "lookup_rejected" in _kinds(result)
    assert "Gross revenue" in client.views[2].last_error


def test_labels_that_never_match_get_the_fixed_miss_text(analytics_db):
    result, _ = _run(
        analytics_db,
        [DEFINE, LookupDecision(("nope",)), LookupDecision(("still nope",))],
    )

    assert (result.status, result.stop_reason) == ("refusal", "no_matching_definition")
    assert result.refusal == DEFINITION_MISS and result.definitions == ()


def test_an_empty_choice_means_the_guide_has_no_answer(analytics_db):
    result, client = _run(analytics_db, [DEFINE, LookupDecision(())])

    assert (result.status, result.stop_reason) == ("refusal", "no_matching_definition")
    assert len(client.views) == 2


def test_only_the_first_few_definitions_are_returned(analytics_db):
    result, _ = _run(
        analytics_db,
        [DEFINE, LookupDecision(topic_labels()[: MAX_DEFINITIONS + 2])],
    )

    assert len(result.definitions) == MAX_DEFINITIONS


def test_definition_route_failures_are_structured(analytics_db):
    broken, _ = _run(analytics_db, [DEFINE, ProviderError("down")])
    wrong, _ = _run(analytics_db, [DEFINE, ToolDecision("revenue_summary")])

    assert (broken.status, broken.stop_reason) == ("failure", "provider_error")
    assert (wrong.status, wrong.stop_reason) == ("failure", "unexpected_decision")


def test_prompts_offer_the_definition_route_and_its_labels():
    classify = build_prompt(ModelView("classify", "What is Order rate?", "", (), 6, None))
    define = build_prompt(
        ModelView(
            "define",
            "What is Order rate?",
            "Current page: X",
            (),
            0,
            None,
            topics=("Executive Overview / Order Rate",),
        )
    )

    assert "metric_definition" in classify
    assert "Executive Overview / Order Rate" in define


def test_gemini_client_parses_a_lookup_step():
    _, _, decision = _decide(
        '{"action":"lookup","topics":["Executive Overview / Revenue"]}', "define"
    )

    assert decision == LookupDecision((REVENUE_TOPIC,))

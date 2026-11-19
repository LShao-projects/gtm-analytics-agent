import pytest
from streamlit.testing.v1 import AppTest

from dashboard.agent_panel import (
    DEMO_MODEL,
    LEVEL_LABELS,
    MEASURES,
    LIVE_MODEL,
    MAX_LIVE_RUNS_PER_SESSION,
    _replay_client,
    build_context,
    claim_rows,
    context_caption,
    evidence_frames,
    page_revenue_basis,
    trace_frame,
)
from dashboard.models import DatePeriod, FilterSpec
from investigation import EvidenceRegistry, InvestigationTools, investigate
from investigation.definitions import CATALOG

JUNE = DatePeriod.from_months("2014-06", "2014-06")
PAGE = "Executive Overview"
QUESTION = "Why did revenue change here?"


def _replay_result(analytics_db):
    context = build_context(PAGE, JUNE, "Previous period", FilterSpec(), "Gross")
    tools = InvestigationTools(analytics_db, EvidenceRegistry())
    return investigate(QUESTION, tools, _replay_client(), context=context)


def _panel_app(analytics_db, controls=None):
    def page(database_path, page_controls):
        from dashboard.agent_panel import render_agent_panel
        from dashboard.models import DatePeriod, FilterSpec

        render_agent_panel(
            database_path,
            "Acquisition",
            DatePeriod.from_months("2014-06", "2014-06"),
            "Previous period",
            FilterSpec(devices=("mobile",)),
            page_controls,
        )

    return AppTest.from_function(
        page, args=(str(analytics_db), controls or {}), default_timeout=30
    )


def test_context_reads_the_current_page_and_filters_without_changing_them():
    filters = FilterSpec(devices=("mobile",))

    context = build_context(PAGE, JUNE, "Previous period", filters, "Net")

    assert context.page == PAGE
    assert context.current_period == JUNE
    assert context.comparison_period == DatePeriod.from_months("2014-05", "2014-05")
    assert context.filters is filters
    assert context.revenue_basis == "Net"
    caption = context_caption(context)
    assert caption.startswith(PAGE) and "devices: mobile" in caption
    assert build_context(PAGE, JUNE, "None", FilterSpec(), "Gross").comparison_period is None
    assert "no comparison" in context_caption(
        build_context(PAGE, JUNE, "None", FilterSpec(), "Gross")
    )


def test_a_short_question_uses_the_dashboard_context_end_to_end(analytics_db):
    result = _replay_result(analytics_db)

    assert result.status == "report"
    assert result.report.scope.current_period == JUNE
    assert result.report.scope.revenue_basis == "Gross"


def test_result_helpers_pair_claims_with_rendered_sentences(analytics_db):
    result = _replay_result(analytics_db)

    rows = claim_rows(result)
    frames = evidence_frames(result)
    trace = trace_frame(result)

    assert [row["Type"] for row in rows] == [
        "Fact",
        "Observed contribution",
        "Observed contribution",
        "Unknown",
    ]
    assert rows[0]["Evidence"] == "EV-001" and rows[-1]["Evidence"] == ""
    assert [title.split(" ")[0] for title, _ in frames] == ["EV-001", "EV-002", "EV-003"]
    assert "Traffic source" in frames[2][0]
    assert list(trace["Kind"])[:2] == ["classify", "scope"]
    assert claim_rows(type(result)("refusal", "x", None, result.trace)) == []


def test_panel_is_open_by_default_and_collapses_to_a_rail_and_back(analytics_db):
    app = _panel_app(analytics_db).run()

    assert not app.exception
    assert [button.label for button in app.button] == [":material/chevron_right:"]
    assert len(app.chat_input) == 1
    assert [radio.label for radio in app.radio] == ["Model"]
    assert not any(caption.value.startswith("Reading:") for caption in app.caption)

    app.button[0].click().run()
    assert not app.exception
    assert [button.label for button in app.button] == [":material/chevron_left:"]
    assert not app.chat_input and not app.radio

    app.button[0].click().run()
    assert [button.label for button in app.button] == [":material/chevron_right:"]
    assert len(app.chat_input) == 1


def test_collapsing_the_panel_keeps_the_thread_and_the_model_choice(analytics_db):
    app = _panel_app(analytics_db).run()
    next(radio for radio in app.radio if radio.label == "Model").set_value(DEMO_MODEL)
    app.chat_input[0].set_value(QUESTION).run()
    assert len(app.session_state["agent_thread"]) == 1

    app.button[0].click().run()
    app.button[0].click().run()

    assert not app.exception
    assert len(app.session_state["agent_thread"]) == 1
    assert next(radio for radio in app.radio if radio.label == "Model").value == DEMO_MODEL
    assert "**Gross revenue was \\$" in " ".join(markdown.value for markdown in app.markdown)


def test_asking_in_the_panel_shows_a_report_for_the_current_page(analytics_db):
    app = _panel_app(analytics_db).run()
    model = next(radio for radio in app.radio if radio.label == "Model")
    assert model.options == [LIVE_MODEL, DEMO_MODEL]
    model.set_value(DEMO_MODEL)
    app.chat_input[0].set_value(QUESTION).run()

    assert not app.exception
    asked, result, caption = app.session_state["agent_thread"][0]
    assert asked == QUESTION
    assert result.status == "report"
    assert caption.startswith("Acquisition") and "devices: mobile" in caption
    assert "Revenue basis: Gross (default; this page has no basis control)" in caption
    shown = " ".join(markdown.value for markdown in app.markdown)
    assert "**Gross revenue was \\$" in shown
    assert "was $" not in shown
    labels = [caption.value for caption in app.caption]
    assert "Fact" in labels and "Unknown" in labels


def _answer_app(analytics_db, scenario):
    """Render one scripted result, so layout is tested for any order or status the model produces."""

    def page(database_path, scenario):
        from dashboard.agent_panel import _render_result, build_context
        from dashboard.models import DatePeriod, FilterSpec
        from investigation import Budgets, EvidenceRegistry, InvestigationTools, investigate
        from investigation.models import Claim
        from investigation.providers import (
            ClassifyDecision,
            FinishDecision,
            LookupDecision,
            ProviderError,
            ScriptedClient,
            ToolDecision,
        )

        classify = ClassifyDecision("supported_investigation")
        scripts = {
            "forced_stop": [
                classify,
                ToolDecision("revenue_summary"),
                ToolDecision("revenue_decomposition"),
            ],
            "shuffled": [
                classify,
                ToolDecision("revenue_summary"),
                ToolDecision("revenue_decomposition"),
                FinishDecision(
                    (
                        Claim("The dataset has no ad-spend data.", "unknown"),
                        Claim("A campaign change may have lowered sessions.", "hypothesis"),
                        Claim("", "observed_contribution", ("EV-002",), "primary_contributor"),
                        Claim("", "verified_fact", ("EV-001",), "revenue_change"),
                    ),
                    "minimum_sufficient_answer",
                ),
            ],
            "refusal": [ClassifyDecision("unsupported_capability")],
            "clarification": [classify],
            "failure": [classify, ProviderError("The model is unavailable")],
            "unanswerable": [ClassifyDecision("unanswerable_from_data")],
            "no_definition": [ClassifyDecision("metric_definition"), LookupDecision(())],
        }
        period = DatePeriod.from_months("2014-06", "2014-06")
        context = (
            None
            if scenario == "clarification"
            else build_context(
                "Executive Overview", period, "Previous period", FilterSpec(), "Gross"
            )
        )
        tools = InvestigationTools(database_path, EvidenceRegistry())
        client = ScriptedClient(scripts[scenario])
        budgets = Budgets(max_tool_calls=1) if scenario == "forced_stop" else Budgets()
        result = investigate(
            "Why did revenue change here?", tools, client, context=context, budgets=budgets
        )
        _render_result(result, 0)

    return AppTest.from_function(
        page, args=(str(analytics_db), scenario), default_timeout=30
    )


def test_claims_are_grouped_by_level_in_a_fixed_order_whatever_order_the_model_gave(
    analytics_db,
):
    app = _answer_app(analytics_db, "shuffled").run()

    assert not app.exception
    answer = [
        (element.type, element.value)
        for element in app.main.children.values()
        if element.type in ("caption", "markdown")
    ]
    assert [value for kind, value in answer if kind == "caption"] == list(
        LEVEL_LABELS.values()
    )
    fact, contribution, hypothesis, unknown = (
        value for kind, value in answer if kind == "markdown"
    )
    assert fact.startswith("**Gross revenue was \\$") and fact.endswith(":gray-badge[EV-001]")
    assert contribution.startswith("- ") and contribution.endswith(":gray-badge[EV-002]")
    assert hypothesis == "- A campaign change may have lowered sessions."
    assert unknown == "- The dataset has no ad-spend data."


def test_a_report_keeps_run_metadata_inside_the_collapsed_trace(analytics_db):
    app = _answer_app(analytics_db, "shuffled").run()

    assert [expander.label for expander in app.expander] == [
        "Evidence (2 records)",
        "Investigation trace",
    ]
    trace_notes = " ".join(caption.value for caption in app.expander[1].caption)
    assert "Stop reason: minimum_sufficient_answer" in trace_notes
    assert "Facts are rendered by code from evidence" in trace_notes
    answer_captions = [
        element.value
        for element in app.main.children.values()
        if element.type == "caption"
    ]
    assert not any(
        "Model:" in caption or "Stopped early" in caption for caption in answer_captions
    )


def test_a_forced_stop_is_stated_as_unknown_in_the_answer_not_as_a_footer(analytics_db):
    app = _answer_app(analytics_db, "forced_stop").run()

    assert not app.exception
    answer = [
        (element.type, element.value)
        for element in app.main.children.values()
        if element.type in ("caption", "markdown")
    ]
    assert [value for kind, value in answer if kind == "caption"] == ["Fact", "Unknown"]
    assert "tool-call limit" in answer[-1][1]
    assert [expander.label for expander in app.expander] == [
        "Evidence (1 record)",
        "Investigation trace",
    ]


@pytest.mark.parametrize("scenario", ["refusal", "clarification", "failure"])
def test_a_result_without_a_code_rendered_body_claims_no_provenance(analytics_db, scenario):
    app = _answer_app(analytics_db, scenario).run()

    assert not app.exception
    captions = " ".join(caption.value for caption in app.caption)
    assert "Model: scripted" in captions
    assert "Facts are rendered" not in captions and "quoted by code" not in captions
    assert [expander.label for expander in app.expander] == ["Investigation trace"]


def test_the_agent_reads_the_revenue_basis_from_the_page_instead_of_asking(analytics_db):
    assert page_revenue_basis({"basis": "Net"}) == ("Net", "")
    assert page_revenue_basis({"basis": "Gross"}) == ("Gross", "")
    assert page_revenue_basis({})[0] == "Gross"

    app = _panel_app(analytics_db, {"basis": "Net", "grain": "Month"}).run()
    next(radio for radio in app.radio if radio.label == "Model").set_value(DEMO_MODEL)
    app.chat_input[0].set_value(QUESTION).run()

    assert not app.exception
    assert [radio.label for radio in app.radio] == ["Model"]
    _, result, caption = app.session_state["agent_thread"][0]
    assert result.report.scope.revenue_basis == "Net"
    assert "Revenue basis: Net." in caption


def _definition_app(analytics_db, topics):
    def page(database_path, topics):
        from dashboard.agent_panel import _render_result
        from investigation import EvidenceRegistry, InvestigationTools, investigate
        from investigation.providers import (
            ClassifyDecision,
            LookupDecision,
            ScriptedClient,
        )

        client = ScriptedClient(
            [ClassifyDecision("metric_definition"), LookupDecision(tuple(topics))]
        )
        tools = InvestigationTools(database_path, EvidenceRegistry())
        _render_result(investigate("What is gross revenue?", tools, client), 0)

    return AppTest.from_function(
        page, args=(str(analytics_db), topics), default_timeout=30
    )


def _definition_elements(definition):
    """The elements one Data Guide entry should render, in order, escaped like the panel does."""
    def plain(text):
        return text.replace("$", "\\$")

    yield "markdown", f"**{plain(definition.name)}** :gray-badge[{plain(definition.context)}]"
    for label, value in definition.fields:
        yield "markdown", f":gray[{label}]  \n{plain(value)}"
    yield "caption", f"Source: {definition.source}"


def test_a_definition_answer_is_quoted_with_its_source(analytics_db):
    app = _definition_app(analytics_db, ["Executive Overview / Revenue"]).run()

    assert not app.exception
    shown = " ".join(markdown.value for markdown in app.markdown)
    captions = " ".join(caption.value for caption in app.caption)
    assert all(value in shown for _, value in CATALOG["Executive Overview / Revenue"].fields)
    assert "Source: Data Guide, Metrics & Charts, Executive Overview" in captions
    assert "quoted by code from the Data Guide" in captions
    assert "Facts are rendered" not in captions


@pytest.mark.parametrize(
    "topics",
    [
        ["Executive Overview / Revenue"],
        ["Products & Refunds / Revenue"],
        ["Traffic source / Direct"],
        ["Campaign / Pilot"],
        ["Table / orders"],
        ["Executive Overview / Revenue", "Executive Overview / Net Revenue"],
    ],
)
def test_a_definition_is_a_title_then_labeled_parts_whatever_the_kind(analytics_db, topics):
    app = _definition_app(analytics_db, topics).run()

    assert not app.exception
    top_level = list(app.main.children.values())
    shown = [(el.type, el.value) for el in top_level if el.type in ("caption", "markdown")]
    assert shown == [
        item for topic in topics for item in _definition_elements(CATALOG[topic])
    ]
    assert sum(el.type == "divider" for el in top_level) == len(topics) - 1


def test_live_model_runs_are_capped_per_session(analytics_db):
    app = _panel_app(analytics_db).run()
    app.session_state["agent_live_runs"] = MAX_LIVE_RUNS_PER_SESSION
    app.chat_input[0].set_value(QUESTION).run()

    assert not app.exception
    assert any("limit of live model runs" in error.value for error in app.error)


@pytest.mark.parametrize("scenario", ["refusal", "unanswerable", "no_definition"])
def test_a_refusal_is_a_short_reason_then_a_list_of_what_the_agent_can_do(
    analytics_db, scenario
):
    app = _answer_app(analytics_db, scenario).run()

    assert not app.exception
    reason = app.warning[0].value
    assert len(reason.split()) < 40 and "I can investigate" not in reason
    top = [e for e in app.main.children.values() if e.type in ("caption", "markdown")]
    assert top[0].value == "I can"
    items = top[1].value.split("\n")
    assert len(items) >= 2 and all(item.startswith("- ") for item in items)
    assert any("month-over-month" in item.lower() for item in items)


def test_every_summary_measure_has_a_display_name(analytics_db):
    from dashboard.metrics import overview_kpis

    kpis = overview_kpis(analytics_db, FilterSpec(), JUNE)

    assert set(kpis) <= set(MEASURES)


def test_evidence_tables_show_display_names_and_formatted_values(analytics_db):
    frames = dict(evidence_frames(_replay_result(analytics_db)))
    summary, decomposition, segments = frames.values()
    assert list(summary.columns) == ["Measure", "Comparison", "Current"]

    for frame in (summary, decomposition, segments):
        cells = [cell for column in frame.columns for cell in frame[column]]
        assert all(isinstance(cell, str) for cell in cells)
        assert not any("_" in cell for cell in cells)
    assert all(value.startswith(("+", "-", "$")) for value in decomposition["Contribution"])
    assert all(" to " in value for value in segments["Comparison to Current"])


def test_dollar_amounts_in_evidence_tables_are_escaped_so_they_are_not_read_as_math(
    analytics_db,
):
    app = _answer_app(analytics_db, "shuffled").run()

    tables = [element.value for element in app.table]
    assert tables
    for table in tables:
        for cell in table.to_numpy().ravel():
            assert "$" not in str(cell).replace("\\$", "")

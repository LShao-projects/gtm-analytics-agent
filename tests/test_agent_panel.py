from streamlit.testing.v1 import AppTest

from dashboard.agent_panel import (
    DEMO_MODEL,
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

JUNE = DatePeriod.from_months("2014-06", "2014-06")
PAGE = "Executive Overview"
QUESTION = "Why did revenue change here?"


def _replay_result(analytics_db):
    context = build_context(PAGE, JUNE, "Previous period", FilterSpec(), "Gross")
    tools = InvestigationTools(analytics_db, EvidenceRegistry())
    return investigate(QUESTION, tools, _replay_client(), context=context)


def _dock_app(analytics_db, controls=None):
    def page(database_path, page_controls):
        from dashboard.agent_panel import render_agent_dock
        from dashboard.models import DatePeriod, FilterSpec

        render_agent_dock(
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
    assert [title.split(":")[0] for title, _ in frames] == ["EV-001", "EV-002", "EV-003"]
    assert "Traffic source" in frames[2][0]
    assert list(trace["Kind"])[:2] == ["classify", "scope"]
    assert claim_rows(type(result)("refusal", "x", None, result.trace)) == []


def test_dock_is_a_collapsed_button_until_opened_and_closes_again(analytics_db):
    app = _dock_app(analytics_db).run()

    assert not app.exception
    assert [button.label for button in app.button] == ["Ask the agent"]
    assert not app.chat_input

    app.button[0].click().run()
    assert not app.exception
    assert [button.label for button in app.button] == [":material/close:"]
    assert len(app.chat_input) == 1
    assert [radio.label for radio in app.radio] == ["Model"]

    app.button[0].click().run()
    assert [button.label for button in app.button] == ["Ask the agent"]
    assert not app.chat_input


def test_asking_in_the_open_dock_shows_a_report_for_the_current_page(analytics_db):
    app = _dock_app(analytics_db).run()
    app.button[0].click().run()
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
    assert "**Fact.** Gross revenue was \\$" in shown
    assert "was $" not in shown
    assert "**Unknown.**" in shown


def test_the_agent_reads_the_revenue_basis_from_the_page_instead_of_asking(analytics_db):
    assert page_revenue_basis({"basis": "Net"}) == ("Net", "")
    assert page_revenue_basis({"basis": "Gross"}) == ("Gross", "")
    assert page_revenue_basis({})[0] == "Gross"

    app = _dock_app(analytics_db, {"basis": "Net", "grain": "Month"}).run()
    app.button[0].click().run()
    next(radio for radio in app.radio if radio.label == "Model").set_value(DEMO_MODEL)
    app.chat_input[0].set_value(QUESTION).run()

    assert not app.exception
    assert [radio.label for radio in app.radio] == ["Model"]
    _, result, caption = app.session_state["agent_thread"][0]
    assert result.report.scope.revenue_basis == "Net"
    assert "Revenue basis: Net." in caption


def test_a_definition_answer_is_quoted_with_its_source(analytics_db):
    def page(database_path):
        from dashboard.agent_panel import _render_result
        from investigation import EvidenceRegistry, InvestigationTools, investigate
        from investigation.providers import (
            ClassifyDecision,
            LookupDecision,
            ScriptedClient,
        )

        client = ScriptedClient(
            [
                ClassifyDecision("metric_definition"),
                LookupDecision(("Executive Overview / Revenue",)),
            ]
        )
        tools = InvestigationTools(database_path, EvidenceRegistry())
        _render_result(investigate("What is gross revenue?", tools, client), 0)

    app = AppTest.from_function(page, args=(str(analytics_db),), default_timeout=30).run()

    assert not app.exception
    shown = " ".join(markdown.value for markdown in app.markdown)
    captions = " ".join(caption.value for caption in app.caption)
    assert "Revenue on Executive Overview: Gross: SUM(orders.price_usd)" in shown
    assert "Source: Data Guide, Metrics & Charts, Executive Overview" in captions
    assert "quoted by code from the Data Guide" in captions
    assert "Facts are rendered" not in captions


def test_live_model_runs_are_capped_per_session(analytics_db):
    app = _dock_app(analytics_db).run()
    app.session_state["agent_live_runs"] = MAX_LIVE_RUNS_PER_SESSION
    app.button[0].click().run()
    app.chat_input[0].set_value(QUESTION).run()

    assert not app.exception
    assert any("limit of live model runs" in error.value for error in app.error)

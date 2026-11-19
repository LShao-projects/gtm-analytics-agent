from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.ui import PAGES, PAGE_NAV_LABELS


APP = Path(__file__).parents[1] / "app.py"


def test_main_shows_friendly_query_error(monkeypatch):
    import app as app_module

    from dashboard.data import DatabaseQueryError

    def fail_render(path, metadata):
        raise DatabaseQueryError("boom")

    messages = []
    monkeypatch.setattr(app_module, "validate_database", lambda path: object())
    monkeypatch.setattr(app_module, "render_app", fail_render)
    monkeypatch.setattr(app_module.st, "error", lambda value: messages.append(value))
    monkeypatch.setattr(app_module.st, "code", lambda value: messages.append(value))
    monkeypatch.setattr(app_module.st, "info", lambda value: messages.append(value))
    monkeypatch.setattr(app_module.st, "stop", lambda: None)

    app_module.main()

    assert messages[0] == "The dashboard query could not be completed."
    assert "boom" in messages[1]
    assert "restart the app" in messages[2]


def test_render_top_navigation_defaults_to_first_page():
    def navigation_test_app():
        from dashboard.ui import render_top_navigation

        render_top_navigation()

    app = AppTest.from_function(navigation_test_app).run()

    assert app.segmented_control(key="top_navigation").value == PAGES[0]
    assert tuple(app.segmented_control(key="top_navigation").options) == tuple(
        PAGE_NAV_LABELS[page] for page in PAGES
    )
    assert not app.exception


def test_overview_metrics_include_comparison_deltas():
    app = AppTest.from_file(APP, default_timeout=30).run()

    assert app.metric[0].label == "Gross Revenue"
    assert app.metric[0].delta
    assert not app.exception


def test_prior_only_slice_keeps_comparison_evidence_visible():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.session_state["global_date_window__value"] = "Custom"
    app.session_state["global_custom_start__value"] = "2014-04"
    app.session_state["global_custom_end__value"] = "2014-04"
    app.session_state["global_compare__value"] = "Previous period"
    app.run()
    app.session_state["global_source__selected"] = ("Paid Social",)
    app.session_state["global_source__all"] = False

    app.run()

    assert [(metric.label, metric.value) for metric in app.metric[:3]] == [
        ("Gross Revenue", "$0.00"),
        ("Orders", "0"),
        ("Sessions", "0"),
    ]
    assert app.metric[0].delta == "-$1,013.78 (-100.00%)"
    assert app.metric[1].delta == "-14 (-100.00%)"
    assert app.metric[2].delta == "-1,240 (-100.00%)"
    markup = " ".join(element.value for element in app.markdown)
    assert "No matching executive overview records" not in markup
    assert "Traffic source: Paid Social" in markup
    assert len(app.get("plotly_chart")) == 3
    assert not app.exception


def test_all_pages_preserve_output_contracts_with_unified_filter_components():
    expected = {
        "Executive Overview": (8, 3, 1),
        "Acquisition": (4, 4, 1),
        "Website Funnel": (3, 3, 1),
        "Products & Refunds": (4, 4, 1),
    }
    app = AppTest.from_file(APP, default_timeout=30).run()

    for page, counts in expected.items():
        app.segmented_control(key="top_navigation").set_value(page).run()
        assert (len(app.metric), len(app.get("plotly_chart")), len(app.dataframe)) == counts
        assert len(app.get("bidi_component")) >= 10
        assert not app.exception

    assert len(app.expander) == 0
    page_markup = " ".join(element.value for element in app.markdown)
    assert '[data-testid="stHeader"], [data-testid="stSidebar"]' in page_markup
    assert "position:fixed" in page_markup
    assert "width:100vw" in page_markup
    assert "--topbar-height:4rem" in page_markup
    assert "--topbar-height:3.15rem" in page_markup
    assert 'max-width:100rem' in page_markup
    assert "justify-content:flex-start" in page_markup
    assert ':has(> .st-key-top_nav_shell)' in page_markup
    assert 'margin:-.56rem -1.25rem -2.5rem' in page_markup
    assert 'grid-template-columns:minmax(0, 1fr) var(--agent-width)' in page_markup
    assert 'grid-template-columns:minmax(0, 1fr) var(--agent-rail-width)' in page_markup
    assert 'position:sticky; top:var(--topbar-height); align-self:start' in page_markup
    assert '@media (max-width: 1279px)' in page_markup
    assert '.st-key-agent_collapse, .st-key-agent_expand' in page_markup
    assert 'position:absolute; left:-10px; top:50%' in page_markup
    assert '.st-key-filter_global, .st-key-filter_page' in page_markup
    assert 'background:var(--white) !important' in page_markup
    assert 'color:#FFFFFF !important; background:var(--navy) !important' in page_markup
    assert ':has(.context-summary)' in page_markup
    assert ".hoverlayer .hovertext path" in page_markup
    assert "filter:drop-shadow" in page_markup
    assert '[data-testid="stPlotlyChart"]:hover svg.main-svg' not in page_markup
    assert "filter-bottom-spacer" not in page_markup
    assert (
        '.st-key-data_guide_workspace div[data-testid="stButtonGroup"] '
        '[role="radio"][aria-checked="true"]'
    ) in page_markup
    assert "max-width: 768px" in page_markup


def test_filter_workspace_does_not_mix_native_widget_design_systems():
    app = AppTest.from_file(APP, default_timeout=30).run()
    filter_bar = app.main.get_by_key("filter_bar")

    assert len(filter_bar.get("bidi_component")) >= 10
    assert len(app.selectbox) == 0
    assert len(app.select_slider) == 0
    assert len(app.checkbox) == 0
    assert len(filter_bar.get("popover")) == 0
    assert not app.exception


def _position(nodes, target):
    return next(index for index, node in enumerate(nodes) if node is target)


def test_filters_sit_above_the_page_and_the_agent_is_the_right_hand_column():
    app = AppTest.from_file(APP, default_timeout=30).run()

    workspace = list(app.main.get_by_key("app_workspace"))
    dashboard = app.main.get_by_key("dashboard_main")
    filter_bar = app.main.get_by_key("filter_bar")
    agent = app.main.get_by_key("agent_panel")
    first_metric = next(node for node in workspace if getattr(node, "type", None) == "metric")

    assert _position(workspace, dashboard) < _position(workspace, agent)
    assert _position(workspace, dashboard) < _position(workspace, filter_bar)
    assert _position(workspace, filter_bar) < _position(workspace, first_metric)
    assert len(agent.chat_input) == 1
    assert not app.exception


def test_each_page_reads_title_then_filter_cards_then_context_then_scorecards():
    app = AppTest.from_file(APP, default_timeout=30).run()

    for page in PAGES[:-1]:
        app.segmented_control(key="top_navigation").set_value(page).run()
        assert not app.exception
        workspace = list(app.main.get_by_key("app_workspace"))

        def markdown_with(text):
            return next(
                node
                for node in workspace
                if getattr(node, "type", None) == "markdown" and text in node.value
            )

        reading_order = [
            markdown_with("page-title"),
            app.main.get_by_key("filter_global"),
            app.main.get_by_key("filter_page"),
            markdown_with("context-summary"),
            next(node for node in workspace if getattr(node, "type", None) == "metric"),
        ]
        positions = [_position(workspace, node) for node in reading_order]
        assert positions == sorted(positions) and len(set(positions)) == len(positions)


def test_the_agent_panel_is_open_on_every_analysis_page_and_absent_from_the_data_guide():
    app = AppTest.from_file(APP, default_timeout=30).run()

    for page in PAGES:
        app.segmented_control(key="top_navigation").set_value(page).run()
        assert not app.exception
        assert len(app.chat_input) == (0 if page == "Data Guide" else 1)


def test_page_switch_keeps_navigation_stable():
    app = AppTest.from_file(APP, default_timeout=30).run()

    app.segmented_control(key="top_navigation").set_value("Acquisition").run()

    assert app.segmented_control(key="top_navigation").value == "Acquisition"
    assert not app.exception


def test_acquisition_defaults_to_session_volume():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.segmented_control(key="top_navigation").set_value("Acquisition").run()

    assert app.session_state["acq_metric__value"] == "Sessions"
    assert any("UTM Source Volume" in element.value for element in app.markdown)
    assert any("Traffic-Source Detail" in element.value for element in app.markdown)
    assert app.dataframe[0].value.columns.tolist() == [
        "Segment",
        "Sessions",
        "Orders",
        "Revenue",
        "Gross Margin",
        "Conversion Rate (%)",
        "Revenue per Session",
        "Margin per Session",
    ]
    assert not app.exception


def test_funnel_detail_preserves_stage_specific_information():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.segmented_control(key="top_navigation").set_value("Website Funnel").run()

    assert app.dataframe[0].value.columns.tolist() == [
        "Stage",
        "Transition",
        "Sessions",
        "Step Conversion (%)",
        "Total Conversion (%)",
        "Drop-Off",
        "Previous Period Total (%)",
    ]
    assert len(app.dataframe[0].value) == 7
    assert app.dataframe[0].value.iloc[0]["Transition"] == "Starting Stage"
    assert not app.exception


def test_product_detail_preserves_multi_metric_product_information():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.segmented_control(key="top_navigation").set_value("Products & Refunds").run()

    assert app.dataframe[0].value.columns.tolist() == [
        "Product",
        "Units",
        "Revenue",
        "COGS",
        "Add-On Units",
        "Refund Units",
        "Refund $",
        "Gross Margin",
        "Net Revenue",
        "Refund Rate (%)",
        "Add-On Share (%)",
    ]
    assert len(app.get("plotly_chart")) == 4
    assert any(
        "Product-Scoped Monthly Revenue" in element.value
        for element in app.markdown
    )
    assert not app.exception


def test_overview_without_comparison_does_not_claim_contribution_detail():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.session_state["global_compare__value"] = "None"

    app.run()

    section_markup = tuple(element.value for element in app.markdown)
    assert any("Current-Period Segment Detail" in value for value in section_markup)
    assert not any(">Contribution Detail<" in value for value in section_markup)
    assert not any("Observed Revenue-Change Contributions" in value for value in section_markup)
    assert not any("Contribution: Traffic source" in value for value in section_markup)
    assert app.dataframe[0].value.columns.tolist() == ["Segment", "Current"]
    assert not app.exception


def test_refund_date_basis_uses_event_ratio_copy_everywhere():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.segmented_control(key="top_navigation").set_value("Products & Refunds").run()
    app.session_state["product_basis__value"] = "Refund date"
    app.session_state["product_metric__value"] = "Refund Event Ratio"

    app.run()

    assert app.metric[3].label == "Refund Event Ratio"
    assert any(
        "Product-Scoped Monthly Refund Event Ratio" in element.value
        for element in app.markdown
    )
    assert any("event ratio rather than" in element.value for element in app.info)
    assert not app.exception


def test_page_context_reports_every_fact_table_used_by_each_workspace():
    app = AppTest.from_file(APP, default_timeout=30).run()

    app.segmented_control(key="top_navigation").set_value("Acquisition").run()
    acquisition_context = " ".join(element.value for element in app.markdown)
    assert "Last observed sessions" in acquisition_context
    assert "Last observed pageviews" in acquisition_context
    assert "Last observed orders" in acquisition_context

    app.segmented_control(key="top_navigation").set_value("Products & Refunds").run()
    product_context = " ".join(element.value for element in app.markdown)
    assert "Last observed sessions" in product_context
    assert "Last observed orders" in product_context
    assert "Last observed items" in product_context
    assert "Last observed refund events" in product_context
    assert not app.exception


def test_funnel_controls_explain_stage_scope_and_non_experiment_status():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.segmented_control(key="top_navigation").set_value("Website Funnel").run()

    copy = " ".join(element.value for element in app.markdown)
    assert "do not filter the Landing cohort" in copy
    assert "are not experiment treatments" in copy
    assert not app.exception

from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.ui import PAGES


APP = Path(__file__).parents[1] / "app.py"


def test_render_top_navigation_defaults_to_first_page():
    def navigation_test_app():
        from dashboard.ui import render_top_navigation

        render_top_navigation()

    app = AppTest.from_function(navigation_test_app).run()

    assert app.segmented_control(key="top_navigation").value == PAGES[0]
    assert tuple(app.segmented_control(key="top_navigation").options) == PAGES
    assert not app.exception


def test_overview_metrics_include_comparison_deltas():
    app = AppTest.from_file(APP, default_timeout=30).run()

    assert app.metric[0].label == "Revenue"
    assert app.metric[0].delta
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


def test_filter_workspace_does_not_mix_native_widget_design_systems():
    app = AppTest.from_file(APP, default_timeout=30).run()

    assert len(app.get("bidi_component")) >= 10
    assert len(app.selectbox) == 0
    assert len(app.select_slider) == 0
    assert len(app.checkbox) == 0
    assert len(app.get("popover")) == 0
    assert not app.exception


def test_page_switch_keeps_navigation_stable():
    app = AppTest.from_file(APP, default_timeout=30).run()

    app.segmented_control(key="top_navigation").set_value("Acquisition").run()

    assert app.segmented_control(key="top_navigation").value == "Acquisition"
    assert not app.exception

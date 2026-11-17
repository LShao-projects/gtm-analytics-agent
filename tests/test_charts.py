import pandas as pd

from dashboard.charts import (
    comparison_bar,
    contribution_bar,
    funnel_chart,
    ranked_bar,
    trend_chart,
)
from dashboard.theme import (
    CHART_HEIGHT,
    COMPARISON,
    GOLD,
    MUTED,
    NAVY,
    NEGATIVE,
    POSITIVE,
)


def test_funnel_chart_preserves_business_stage_order():
    frame = pd.DataFrame(
        {
            "stage": ["Landing", "Products", "Product detail", "Cart", "Shipping", "Billing", "Thank-you"],
            "sessions": [100, 80, 60, 40, 30, 25, 20],
            "step_conversion": [1.0, 0.8, 0.75, 2 / 3, 0.75, 5 / 6, 0.8],
            "total_conversion": [1.0, 0.8, 0.6, 0.4, 0.3, 0.25, 0.2],
            "drop_off": [0, 20, 20, 20, 10, 5, 5],
        }
    )

    figure = funnel_chart(frame)

    assert list(figure.data[0].y) == frame["stage"].tolist()
    assert "Sessions: %{x:,.0f}" in figure.data[0].hovertemplate
    assert "Total conversion: %{customdata:.2%}" in figure.data[0].hovertemplate
    assert figure.layout.height <= 330
    assert list(figure.data[0].marker.color)[:2] == [NAVY, GOLD]
    assert len(figure.data[0].y) == 7


def test_ranked_financial_bar_has_exact_hover_and_uses_descending_order():
    frame = pd.DataFrame({"segment": ["Small", "Large"], "revenue": [10.0, 30.0]})

    figure = ranked_bar(frame, "segment", "revenue", "Revenue", value_format="currency")

    assert list(figure.data[0].y) == ["Large", "Small"]
    assert "Revenue: %{x:$,.2f}" in figure.data[0].hovertemplate
    assert figure.layout.xaxis.tickformat == "$,.0f"
    assert figure.layout.height == CHART_HEIGHT
    assert figure.data[0].marker.color == NAVY


def test_trend_chart_returns_annotated_empty_state():
    figure = trend_chart(pd.DataFrame(), "period", "revenue", "Revenue", value_format="currency")

    assert len(figure.data) == 0
    assert figure.layout.annotations[0].text == "No data for the selected filters"
    assert figure.layout.height <= 300


def test_single_period_trend_hover_names_scope_and_metric():
    frame = pd.DataFrame({"period": ["2014-10"], "revenue": [103905.98]})

    figure = trend_chart(
        frame,
        "period",
        "revenue",
        "Total Revenue",
        value_format="currency",
        hover_context="All products<br>All item roles<br>All order sizes",
    )

    assert figure.data[0].customdata[0][0] == "Oct 2014"
    assert figure.data[0].customdata[0][1] == "All products<br>All item roles<br>All order sizes"
    assert figure.data[0].customdata[0][2] == "$103,905.98"
    assert "Total Revenue" in figure.data[0].hovertemplate
    assert figure.layout.yaxis.tickformat == "$,.0f"


def test_comparison_hover_uses_lines_instead_of_middle_dot_separators():
    frame = pd.DataFrame({"period": ["2014-02"], "revenue": [12.0]})
    comparison = pd.DataFrame({"period": ["2014-01"], "revenue": [10.0]})

    figure = trend_chart(
        frame,
        "period",
        "revenue",
        "Revenue",
        value_format="currency",
        comparison=comparison,
        comparison_label="Previous period",
    )

    assert "<b>Current</b><br>Period:" in figure.data[0].hovertemplate
    assert "<b>Previous period</b><br>Period:" in figure.data[0].hovertemplate
    assert f" {chr(183)} " not in figure.data[0].hovertemplate


def test_trend_chart_uses_compact_shared_theme_and_comparison_color():
    frame = pd.DataFrame({"period": ["2014-01", "2014-02"], "revenue": [10.0, 12.0]})
    comparison = pd.DataFrame({"period": ["2013-11", "2013-12"], "revenue": [8.0, 9.0]})

    figure = trend_chart(
        frame,
        "period",
        "revenue",
        "Revenue",
        value_format="currency",
        comparison=comparison,
        comparison_label="Previous period",
    )

    assert figure.data[0].line.color == NAVY
    assert figure.data[1].line.color == COMPARISON
    assert tuple(figure.data[0].x) == (1, 2)
    assert tuple(figure.data[1].x) == (1, 2)
    assert figure.data[0].name == "Current"
    assert figure.data[1].name == "Previous period"
    assert figure.data[0].customdata[0][0] == "Jan 2014"
    assert figure.data[0].customdata[0][2] == "Nov 2013"
    assert "Relative change" in figure.data[0].hovertemplate
    assert tuple(figure.layout.xaxis.ticktext) == ("Jan 14", "Feb 14")
    assert not figure.layout.annotations
    assert 280 <= figure.layout.height <= 330
    assert figure.layout.margin.l <= 20
    assert figure.layout.margin.r <= 20
    assert figure.layout.margin.t <= 44
    assert figure.layout.margin.b <= 20
    assert POSITIVE not in (figure.data[0].line.color, figure.data[1].line.color)
    assert NEGATIVE not in (figure.data[0].line.color, figure.data[1].line.color)


def test_comparison_trend_uses_one_compact_row_of_current_months():
    frame = pd.DataFrame(
        {
            "period": [f"2014-{month:02d}" for month in range(1, 13)],
            "revenue": list(range(12)),
        }
    )
    comparison = pd.DataFrame(
        {
            "period": [f"2013-{month:02d}" for month in range(1, 13)],
            "revenue": list(range(12)),
        }
    )

    figure = trend_chart(
        frame,
        "period",
        "revenue",
        "Revenue",
        comparison=comparison,
        display_title=False,
    )

    assert tuple(figure.layout.xaxis.tickvals) == tuple(range(1, 13))
    assert tuple(figure.layout.xaxis.ticktext) == tuple(
        f"{pd.Timestamp(2014, month, 1):%b %y}"
        for month in range(1, 13)
    )
    assert not figure.layout.annotations
    assert figure.layout.margin.b == 44


def test_trend_chart_keeps_comparison_evidence_when_current_is_empty():
    comparison = pd.DataFrame(
        {"period": ["2014-01", "2014-02"], "revenue": [10.0, 12.0]}
    )

    figure = trend_chart(
        pd.DataFrame(columns=["period", "revenue"]),
        "period",
        "revenue",
        "Revenue",
        value_format="currency",
        comparison=comparison,
        comparison_label="Previous period",
        display_title=False,
    )

    assert len(figure.data) == 1
    assert figure.data[0].name == "Previous period"
    assert tuple(figure.data[0].y) == (10.0, 12.0)
    assert tuple(figure.layout.xaxis.ticktext) == ("Jan 14", "Feb 14")
    assert not figure.layout.annotations


def test_trend_chart_keeps_comparison_evidence_when_current_rate_is_unavailable():
    frame = pd.DataFrame(
        {"period": ["2014-03", "2014-04"], "rate": [pd.NA, pd.NA]}
    )
    comparison = pd.DataFrame(
        {"period": ["2014-01", "2014-02"], "rate": [0.1, 0.2]}
    )

    figure = trend_chart(
        frame,
        "period",
        "rate",
        "Rate",
        value_format="percent",
        comparison=comparison,
        comparison_label="Previous period",
        display_title=False,
    )

    assert len(figure.data) == 1
    assert figure.data[0].name == "Previous period"
    assert tuple(figure.layout.xaxis.ticktext) == ("Mar 14", "Apr 14")
    assert not figure.layout.annotations


def test_four_category_ranked_bar_uses_shared_row_height():
    frame = pd.DataFrame(
        {"segment": ["A", "B", "C", "D"], "revenue": [40.0, 30.0, 20.0, 10.0]}
    )

    figure = ranked_bar(frame, "segment", "revenue", "Revenue", value_format="currency")

    assert figure.layout.height == CHART_HEIGHT
    assert list(figure.data[0].y) == ["A", "B", "C", "D"]
    assert "Revenue: %{x:$,.2f}" in figure.data[0].hovertemplate


def test_ranked_bar_handles_signed_values_around_zero():
    frame = pd.DataFrame({"segment": ["Gain", "Loss"], "delta": [30.0, -20.0]})

    figure = ranked_bar(frame, "segment", "delta", "Revenue change", value_format="currency")

    assert figure.layout.xaxis.range[0] < 0 < figure.layout.xaxis.range[1]
    assert figure.layout.xaxis.zeroline
    assert figure.layout.xaxis.tickformat == "$,.0f"


def test_ranked_bar_filters_missing_values_and_keeps_negative_zero_baseline():
    frame = pd.DataFrame(
        {"segment": ["Missing", "Loss"], "delta": [pd.NA, -20.0]}
    )

    figure = ranked_bar(
        frame,
        "segment",
        "delta",
        "Revenue change",
        value_format="currency",
    )

    assert list(figure.data[0].y) == ["Loss"]
    assert figure.layout.xaxis.zeroline
    empty = ranked_bar(
        pd.DataFrame({"segment": ["Missing"], "delta": [pd.NA]}),
        "segment",
        "delta",
        "Revenue change",
    )
    assert len(empty.data) == 0


def test_contribution_bar_uses_signed_semantic_colors_and_exact_values():
    frame = pd.DataFrame(
        {"driver": ["Sessions", "Conversion rate"], "contribution": [1250.25, -500.5]}
    )

    figure = contribution_bar(
        frame,
        "driver",
        "contribution",
        "Observed revenue contribution",
    )

    assert list(figure.data[0].marker.color) == [POSITIVE, NEGATIVE]
    assert figure.layout.xaxis.zeroline
    assert figure.data[0].customdata[0] == "$1,250.25"
    assert figure.data[0].customdata[1] == "-$500.50"


def test_contribution_bar_filters_missing_and_uses_neutral_zero_color():
    frame = pd.DataFrame(
        {
            "driver": ["Missing", "No change"],
            "contribution": [pd.NA, 0.0],
        }
    )

    figure = contribution_bar(frame, "driver", "contribution", "Contribution")

    assert list(figure.data[0].y) == ["No change"]
    assert list(figure.data[0].marker.color) == [MUTED]
    assert figure.data[0].customdata[0] == "$0.00"


def test_trend_chart_treats_missing_values_as_gaps_without_nan_copy():
    frame = pd.DataFrame(
        {"period": ["2014-01", "2014-02"], "revenue": [10.0, pd.NA]}
    )
    comparison = pd.DataFrame(
        {"period": ["2013-01", "2013-02"], "revenue": [8.0, pd.NA]}
    )

    figure = trend_chart(
        frame,
        "period",
        "revenue",
        "Revenue",
        value_format="currency",
        comparison=comparison,
    )

    assert figure.data[0].customdata[1][1] == "Not available"
    assert figure.data[0].customdata[1][3] == "Not available"


def test_comparison_bar_reports_rate_point_change_and_denominators():
    frame = pd.DataFrame(
        {
            "segment": ["Desktop", "Mobile"],
            "current": [0.08, 0.05],
            "comparison": [0.07, 0.06],
            "absolute_delta": [0.01, -0.01],
            "current_sessions": [1000, 200],
            "comparison_sessions": [900, 250],
        }
    )

    figure = comparison_bar(
        frame,
        "segment",
        label="Conversion rate",
        value_format="percent",
        comparison_label="Previous period",
        current_denominator="current_sessions",
        comparison_denominator="comparison_sessions",
    )

    assert len(figure.data) == 2
    assert list(figure.data[0].y) == ["Desktop", "Mobile"]
    assert figure.data[0].customdata[0][2] == "+1.00 pp"
    assert figure.data[0].customdata[0][4] == "1,000"
    assert "Current denominator" in figure.data[0].hovertemplate
    assert f" {chr(183)} " not in figure.data[0].hovertemplate
    assert figure.layout.xaxis.tickformat == ".1%"
    assert figure.data[0].marker.color == NAVY
    assert figure.data[1].marker.color == COMPARISON
    assert figure.layout.height == CHART_HEIGHT


def test_comparison_bar_preserves_segments_missing_from_one_period():
    frame = pd.DataFrame(
        {
            "segment": ["New", "Exited"],
            "current": [100.0, float("nan")],
            "comparison": [float("nan"), 80.0],
            "absolute_delta": [100.0, -80.0],
        }
    )

    figure = comparison_bar(frame, "segment", label="Revenue", value_format="currency")

    assert set(figure.data[0].y) == {"New", "Exited"}
    first_by_segment = dict(zip(figure.data[0].y, figure.data[0].customdata))
    assert first_by_segment["New"][1] == "Not available"
    assert first_by_segment["Exited"][0] == "Not available"
    assert first_by_segment["New"][2] == "+$100.00"
    assert first_by_segment["Exited"][2] == "-$80.00"


def test_comparison_bar_zero_values_remain_visible_and_all_missing_is_empty():
    zero = comparison_bar(
        pd.DataFrame(
            {
                "segment": ["No change"],
                "current": [0.0],
                "comparison": [0.0],
                "absolute_delta": [0.0],
            }
        ),
        "segment",
        label="Orders",
        value_format="integer",
    )

    assert zero.layout.xaxis.zeroline
    assert list(zero.data[0].text) == ["0"]
    assert list(zero.data[1].text) == ["0"]

    empty = comparison_bar(
        pd.DataFrame(
            {
                "segment": ["Missing"],
                "current": [pd.NA],
                "comparison": [pd.NA],
            }
        ),
        "segment",
        label="Orders",
    )
    assert len(empty.data) == 0

import pandas as pd

from dashboard.charts import funnel_chart, ranked_bar, trend_chart
from dashboard.theme import GOLD, MUTED, NAVY, NEGATIVE, POSITIVE


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
    assert figure.data[0].hoverinfo == "skip"
    assert figure.layout.height <= 330
    assert list(figure.data[0].marker.color)[:2] == [NAVY, GOLD]
    assert len(figure.data[0].y) == 7


def test_ranked_financial_bar_disables_redundant_hover_and_uses_descending_order():
    frame = pd.DataFrame({"segment": ["Small", "Large"], "revenue": [10.0, 30.0]})

    figure = ranked_bar(frame, "segment", "revenue", "Revenue", value_format="currency")

    assert list(figure.data[0].y) == ["Large", "Small"]
    assert figure.data[0].hoverinfo == "skip"
    assert 280 <= figure.layout.height <= 330
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
    assert figure.data[0].customdata[0][2] == "$103.91K"
    assert "Total Revenue" in figure.data[0].hovertemplate


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
    assert figure.data[1].line.color in (MUTED, GOLD)
    assert tuple(figure.data[0].x) == (1, 2)
    assert tuple(figure.data[1].x) == (1, 2)
    assert figure.data[0].name == "Current"
    assert figure.data[1].name == "Previous period"
    assert figure.data[0].customdata[0][0] == "Jan 2014"
    assert figure.data[0].customdata[0][2] == "Nov 2013"
    assert "Relative change" in figure.data[0].hovertemplate
    assert tuple(figure.layout.xaxis.ticktext) == ("Jan 14<br>Nov 13", "Feb 14<br>Dec 13")
    assert [annotation.text for annotation in figure.layout.annotations] == [
        "Current",
        "Compare",
    ]
    assert 280 <= figure.layout.height <= 330
    assert figure.layout.margin.l <= 20
    assert figure.layout.margin.r <= 20
    assert figure.layout.margin.t <= 44
    assert figure.layout.margin.b <= 20
    assert POSITIVE not in (figure.data[0].line.color, figure.data[1].line.color)
    assert NEGATIVE not in (figure.data[0].line.color, figure.data[1].line.color)


def test_comparison_trend_uses_two_rows_of_every_month():
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
        f"{pd.Timestamp(2014, month, 1):%b %y}<br>{pd.Timestamp(2013, month, 1):%b %y}"
        for month in range(1, 13)
    )
    assert figure.layout.margin.b == 76


def test_four_category_ranked_bar_stays_compact():
    frame = pd.DataFrame(
        {"segment": ["A", "B", "C", "D"], "revenue": [40.0, 30.0, 20.0, 10.0]}
    )

    figure = ranked_bar(frame, "segment", "revenue", "Revenue", value_format="currency")

    assert 280 <= figure.layout.height <= 330
    assert list(figure.data[0].y) == ["A", "B", "C", "D"]
    assert figure.data[0].hoverinfo == "skip"

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.theme import (
    BORDER,
    CHART_HEIGHT,
    CHART_PALETTE,
    EMPTY_CHART_HEIGHT,
    FUNNEL_CHART_HEIGHT,
    INK,
    MUTED,
    NAVY,
    WHITE,
)


def _base_layout(figure: go.Figure, *, height: int = CHART_HEIGHT) -> go.Figure:
    figure.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=44, b=20),
        dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, ui-sans-serif, system-ui", color=INK, size=12),
        hoverlabel=dict(bgcolor=WHITE, font_color=INK, bordercolor=BORDER),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    figure.update_xaxes(
        showgrid=True,
        gridcolor=BORDER,
        zeroline=False,
        title=None,
        fixedrange=True,
    )
    figure.update_yaxes(showgrid=False, zeroline=False, title=None, fixedrange=True)
    return figure


def empty_figure(
    message: str = "No data for the selected filters", *, height: int = EMPTY_CHART_HEIGHT
) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=14, color=MUTED),
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return _base_layout(figure, height=height)


def _hover_format(value_format: str) -> str:
    return {
        "currency": "$%{y:,.2f}<extra></extra>",
        "percent": "%{y:.2%}<extra></extra>",
        "integer": "%{y:,.0f}<extra></extra>",
        "decimal": "%{y:,.2f}<extra></extra>",
    }.get(value_format, "%{y}<extra></extra>")


def _display_period(value: object) -> str:
    text = str(value)
    try:
        if len(text) == 7 and text[4] == "-":
            return pd.Timestamp(text).strftime("%b %Y")
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return pd.Timestamp(text).strftime("%b %d, %Y")
    except ValueError:
        pass
    return text


def _display_axis_period(value: object) -> str:
    text = str(value)
    try:
        if len(text) == 7 and text[4] == "-":
            return pd.Timestamp(text).strftime("%b %y")
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return pd.Timestamp(text).strftime("%b %d, %y")
    except ValueError:
        pass
    return text


def _display_hover_value(value: float, value_format: str) -> str:
    if value_format == "currency":
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if abs(value) >= 1_000:
            return f"${value / 1_000:.2f}K"
        return f"${value:,.2f}"
    if value_format == "percent":
        return f"{value:.2%}"
    if value_format == "integer":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def trend_chart(
    frame: pd.DataFrame,
    x: str,
    y: str,
    label: str,
    *,
    value_format: str = "decimal",
    comparison: pd.DataFrame | None = None,
    comparison_label: str = "Comparison",
    hover_context: str | None = None,
    display_title: bool = True,
) -> go.Figure:
    if frame.empty or x not in frame or y not in frame:
        return empty_figure()
    figure = go.Figure()
    has_comparison = comparison is not None and not comparison.empty and x in comparison and y in comparison
    if has_comparison:
        point_count = max(len(frame), len(comparison))
        pair_data: list[list[str]] = []
        for index in range(point_count):
            current_exists = index < len(frame)
            comparison_exists = index < len(comparison)
            current_value = float(frame[y].iloc[index]) if current_exists else None
            comparison_value = float(comparison[y].iloc[index]) if comparison_exists else None
            relative_change = (
                f"{(current_value - comparison_value) / abs(comparison_value):+.2%}"
                if current_value is not None and comparison_value not in (None, 0)
                else "Not available"
            )
            pair_data.append(
                [
                    _display_period(frame[x].iloc[index]) if current_exists else "Not available",
                    _display_hover_value(current_value, value_format) if current_value is not None else "Not available",
                    _display_period(comparison[x].iloc[index]) if comparison_exists else "Not available",
                    _display_hover_value(comparison_value, value_format) if comparison_value is not None else "Not available",
                    relative_change,
                ]
            )
        hover = (
            "<b>Current</b><br>"
            "Period: %{customdata[0]}<br>"
            f"{label}: %{{customdata[1]}}<br>"
            f"<b>{comparison_label}</b><br>"
            "Period: %{customdata[2]}<br>"
            f"{label}: %{{customdata[3]}}<br>"
            "Relative change: %{customdata[4]}<extra></extra>"
        )
        figure.add_trace(
            go.Scatter(
                x=list(range(1, len(frame) + 1)),
                y=frame[y],
                mode="lines+markers",
                name="Current",
                line=dict(color=NAVY, width=3),
                marker=dict(size=6),
                customdata=pair_data[: len(frame)],
                hovertemplate=hover,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=list(range(1, len(comparison) + 1)),
                y=comparison[y],
                mode="lines+markers",
                name=comparison_label,
                line=dict(color=MUTED, width=2, dash="dot"),
                marker=dict(size=5),
                customdata=pair_data[: len(comparison)],
                hovertemplate=hover,
            )
        )
        figure.update_layout(hovermode="closest", spikedistance=-1)
    else:
        customdata = None
        hovertemplate = f"%{{x}}<br>{label}: {_hover_format(value_format)}"
        if hover_context:
            customdata = [
                [
                    _display_period(period),
                    hover_context,
                    _display_hover_value(float(value), value_format),
                ]
                for period, value in zip(frame[x], frame[y])
            ]
            hovertemplate = (
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]}<br>"
                f"{label}: %{{customdata[2]}}<extra></extra>"
            )
        figure.add_trace(
            go.Scatter(
                x=frame[x],
                y=frame[y],
                mode="lines+markers",
                name=label,
                line=dict(color=NAVY, width=3),
                marker=dict(size=6),
                customdata=customdata,
                hovertemplate=hovertemplate,
            )
        )
    figure.update_layout(title=dict(text=label, font=dict(size=16)) if display_title else None)
    figure = _base_layout(figure)
    figure.update_xaxes(automargin=True)
    figure.update_yaxes(automargin=True)
    if has_comparison:
        tick_indices = list(range(point_count))
        tick_labels = [
            (
                f"{_display_axis_period(frame[x].iloc[index]) if index < len(frame) else '—'}<br>"
                f"{_display_axis_period(comparison[x].iloc[index]) if index < len(comparison) else '—'}"
            )
            for index in tick_indices
        ]
        figure.update_xaxes(
            tickmode="array",
            tickvals=[index + 1 for index in tick_indices],
            ticktext=tick_labels,
            range=[0.7, point_count + 0.3],
            showgrid=False,
            showspikes=True,
            spikecolor=MUTED,
            spikedash="dot",
            spikethickness=1,
            spikemode="across",
        )
        figure.add_annotation(
            text="Current",
            x=0,
            y=-0.16,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            font=dict(color=INK, size=12),
        )
        figure.add_annotation(
            text="Compare",
            x=0,
            y=-0.28,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            font=dict(color=MUTED, size=12),
        )
    if not display_title:
        figure.update_layout(margin=dict(l=68, r=28, t=22, b=76 if has_comparison else 44))
    return figure


def ranked_bar(
    frame: pd.DataFrame,
    category: str,
    value: str,
    label: str,
    *,
    value_format: str = "decimal",
    color: str = NAVY,
    display_title: bool = True,
) -> go.Figure:
    if frame.empty or category not in frame or value not in frame:
        return empty_figure()
    ordered = frame.sort_values(value, ascending=False)
    if value_format == "currency":
        text = [
            f"${number / 1_000_000:.2f}M"
            if abs(number) >= 1_000_000
            else f"${number / 1_000:.2f}K"
            if abs(number) >= 1_000
            else f"${number:,.2f}"
            for number in ordered[value]
        ]
    elif value_format == "percent":
        text = [f"{number:.2%}" for number in ordered[value]]
    elif value_format == "integer":
        text = [f"{number:,.0f}" for number in ordered[value]]
    else:
        text = [f"{number:,.2f}" for number in ordered[value]]
    figure = go.Figure(
        go.Bar(
            x=ordered[value],
            y=ordered[category],
            orientation="h",
            marker=dict(color=color, cornerradius=5),
            hoverinfo="skip",
            text=text,
            textposition="outside",
            cliponaxis=False,
        )
    )
    figure.update_layout(
        title=dict(text=label, font=dict(size=16)) if display_title else None,
        showlegend=False,
    )
    figure.update_yaxes(
        categoryorder="array",
        categoryarray=ordered[category].tolist()[::-1],
        automargin=True,
    )
    height = min(420, max(280, 92 + len(ordered) * 34))
    figure = _base_layout(figure, height=height)
    longest_label = max((len(str(item)) for item in ordered[category]), default=0)
    figure.update_layout(
        margin=dict(
            l=min(170, max(54, 7 * longest_label + 14)),
            r=58,
            t=44 if display_title else 22,
            b=32,
        )
    )
    figure.update_xaxes(automargin=True)
    maximum = float(ordered[value].max()) if not ordered.empty else 0
    if maximum > 0:
        figure.update_xaxes(range=[0, maximum * 1.24])
    if value_format == "percent":
        figure.update_xaxes(tickformat=".2%")
    return figure


def funnel_chart(frame: pd.DataFrame) -> go.Figure:
    if frame.empty:
        return empty_figure()
    figure = go.Figure(
        go.Funnel(
            x=frame["sessions"],
            y=frame["stage"],
            marker=dict(color=CHART_PALETTE[: len(frame)]),
            customdata=frame["total_conversion"],
            hoverinfo="skip",
            text=[
                f"{value:,.0f}<br>{rate:.2%}"
                for value, rate in zip(frame["sessions"], frame["total_conversion"])
            ],
            textinfo="text",
            connector=dict(line=dict(color=BORDER, width=1)),
        )
    )
    figure.update_layout(showlegend=False)
    figure = _base_layout(figure, height=FUNNEL_CHART_HEIGHT)
    figure.update_layout(margin=dict(l=92, r=30, t=22, b=26))
    figure.update_yaxes(automargin=True)
    return figure


def grouped_bar(
    frame: pd.DataFrame,
    x: str,
    series: dict[str, str],
    *,
    title: str,
    value_format: str = "decimal",
) -> go.Figure:
    if frame.empty:
        return empty_figure()
    figure = go.Figure()
    for index, (column, label) in enumerate(series.items()):
        figure.add_trace(
            go.Bar(
                x=frame[x],
                y=frame[column],
                name=label,
                marker_color=CHART_PALETTE[index % len(CHART_PALETTE)],
                hovertemplate=f"%{{x}}<br>{label}: {_hover_format(value_format)}",
            )
        )
    figure.update_layout(title=dict(text=title, font=dict(size=16)), barmode="group")
    return _base_layout(figure)

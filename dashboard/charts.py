from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dashboard.theme import (
    BORDER,
    CHART_HEIGHT,
    CHART_PALETTE,
    COMPARISON,
    EMPTY_CHART_HEIGHT,
    FUNNEL_CHART_HEIGHT,
    INK,
    MUTED,
    NAVY,
    NEGATIVE,
    POSITIVE,
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


def _hover_format(value_format: str, *, axis: str = "y") -> str:
    return {
        "currency": f"%{{{axis}:$,.2f}}<extra></extra>",
        "percent": f"%{{{axis}:.2%}}<extra></extra>",
        "integer": f"%{{{axis}:,.0f}}<extra></extra>",
        "decimal": f"%{{{axis}:,.2f}}<extra></extra>",
    }.get(value_format, f"%{{{axis}}}<extra></extra>")


def _axis_style(value_format: str) -> dict[str, str]:
    if value_format == "currency":
        return {"tickformat": "$,.0f"}
    if value_format == "percent":
        return {"tickformat": ".1%"}
    if value_format == "integer":
        return {"tickformat": ",.0f"}
    return {"tickformat": ",.2f"}


def _numeric_range(values: pd.Series, *, label_padding: float = 0.24) -> list[float] | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if minimum == maximum == 0:
        return [0, 1]
    if minimum >= 0 and maximum > 0:
        return [0, maximum * (1 + label_padding)]
    if maximum <= 0 and minimum < 0:
        return [minimum * (1 + label_padding), 0]
    extent = max(abs(minimum), abs(maximum)) * (1 + label_padding / 2)
    return [-extent, extent]


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
        return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"
    if value_format == "percent":
        return f"{value:.2%}"
    if value_format == "integer":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _display_bar_value(value: float, value_format: str) -> str:
    if value_format == "currency":
        sign = "-" if value < 0 else ""
        magnitude = abs(value)
        if magnitude >= 1_000_000:
            return f"{sign}${magnitude / 1_000_000:.2f}M"
        if magnitude >= 1_000:
            return f"{sign}${magnitude / 1_000:.2f}K"
        return f"{sign}${magnitude:,.2f}"
    return _display_hover_value(value, value_format)


def _safe_number(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or not np.isfinite(float(number)):
        return None
    return float(number)


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    result = frame.copy()
    result[column] = pd.to_numeric(result[column], errors="coerce")
    result.loc[~np.isfinite(result[column]), column] = np.nan
    return result


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
    current_has_columns = not frame.empty and x in frame and y in frame
    comparison_has_columns = (
        comparison is not None
        and not comparison.empty
        and x in comparison
        and y in comparison
    )
    if not current_has_columns and not comparison_has_columns:
        return empty_figure()
    frame = (
        _numeric_column(frame, y)
        if current_has_columns
        else pd.DataFrame(columns=[x, y])
    )
    current_has_numeric = bool(frame[y].notna().sum())
    if comparison_has_columns:
        assert comparison is not None
        comparison = _numeric_column(comparison, y)
        if comparison[y].notna().sum() == 0:
            comparison = None
    else:
        comparison = None
    if not current_has_numeric and comparison is None:
        return empty_figure("No numeric evidence is available")
    figure = go.Figure()
    has_comparison = comparison is not None
    if has_comparison:
        point_count = max(len(frame), len(comparison))
        pair_data: list[list[str]] = []
        for index in range(point_count):
            current_exists = index < len(frame)
            comparison_exists = index < len(comparison)
            current_value = _safe_number(frame[y].iloc[index]) if current_exists else None
            comparison_value = (
                _safe_number(comparison[y].iloc[index])
                if comparison_exists
                else None
            )
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
        if current_has_numeric:
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
                line=dict(color=COMPARISON, width=2, dash="dot"),
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
                    (
                        _display_hover_value(number, value_format)
                        if (number := _safe_number(value)) is not None
                        else "Not available"
                    ),
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
    figure.update_yaxes(automargin=True, **_axis_style(value_format))
    if has_comparison:
        tick_indices = list(range(point_count))
        tick_source = frame if not frame.empty else comparison
        assert tick_source is not None
        tick_labels = [
            _display_axis_period(tick_source[x].iloc[index])
            if index < len(tick_source)
            else "—"
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
    if not display_title:
        figure.update_layout(margin=dict(l=68, r=28, t=22, b=44))
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
    frame = _numeric_column(frame, value).dropna(subset=[value])
    if frame.empty:
        return empty_figure("No numeric evidence is available")
    ordered = frame.sort_values(value, ascending=False)
    text = [_display_bar_value(float(number), value_format) for number in ordered[value]]
    figure = go.Figure(
        go.Bar(
            x=ordered[value],
            y=ordered[category],
            orientation="h",
            marker=dict(color=color, cornerradius=5),
            hovertemplate=f"<b>%{{y}}</b><br>{label}: {_hover_format(value_format, axis='x')}",
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
    figure = _base_layout(figure)
    longest_label = max((len(str(item)) for item in ordered[category]), default=0)
    figure.update_layout(
        margin=dict(
            l=min(170, max(54, 7 * longest_label + 14)),
            r=58,
            t=44 if display_title else 22,
            b=32,
        )
    )
    axis_range = _numeric_range(ordered[value])
    figure.update_xaxes(
        automargin=True,
        range=axis_range,
        zeroline=bool(axis_range and axis_range[0] <= 0 <= axis_range[1]),
        zerolinecolor=MUTED,
        **_axis_style(value_format),
    )
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
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Sessions: %{x:,.0f}<br>"
                "Total conversion: %{customdata:.2%}<extra></extra>"
            ),
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


def contribution_bar(
    frame: pd.DataFrame,
    category: str,
    value: str,
    label: str,
    *,
    value_format: str = "currency",
    display_title: bool = False,
) -> go.Figure:
    """Render signed accounting contributions around an explicit zero line."""
    if frame.empty or category not in frame or value not in frame:
        return empty_figure("No comparison evidence is available")
    frame = _numeric_column(frame, value).dropna(subset=[value])
    if frame.empty:
        return empty_figure("No numeric comparison evidence is available")
    ordered = frame.assign(_magnitude=frame[value].abs()).sort_values(
        "_magnitude", ascending=False
    )
    colors = [
        POSITIVE if number > 0 else NEGATIVE if number < 0 else MUTED
        for number in ordered[value]
    ]
    figure = go.Figure(
        go.Bar(
            x=ordered[value],
            y=ordered[category],
            orientation="h",
            marker=dict(color=colors, cornerradius=5),
            customdata=[
                _display_hover_value(float(number), value_format)
                for number in ordered[value]
            ],
            hovertemplate=f"<b>%{{y}}</b><br>{label}: %{{customdata}}<extra></extra>",
            text=[_display_hover_value(float(number), value_format) for number in ordered[value]],
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
    figure = _base_layout(figure)
    figure.update_layout(margin=dict(l=130, r=72, t=44 if display_title else 22, b=32))
    figure.update_xaxes(
        range=_numeric_range(ordered[value]),
        zeroline=True,
        zerolinecolor=MUTED,
        zerolinewidth=1,
        **_axis_style(value_format),
    )
    return figure


def _optional_display_value(value: object, value_format: str) -> str:
    number = _safe_number(value)
    if number is None:
        return "Not available"
    return _display_hover_value(number, value_format)


def _absolute_change_display(difference: float, value_format: str) -> str:
    if value_format == "percent":
        return f"{difference * 100:+.2f} pp"
    absolute = _display_hover_value(difference, value_format)
    return f"+{absolute}" if difference > 0 else absolute


def _change_display(current: object, comparison: object, value_format: str) -> tuple[str, str]:
    if current is None or comparison is None or pd.isna(current) or pd.isna(comparison):
        return "Not available", "Not available"
    current_number = float(current)
    comparison_number = float(comparison)
    difference = current_number - comparison_number
    absolute = _absolute_change_display(difference, value_format)
    relative = (
        f"{difference / abs(comparison_number):+.2%}"
        if comparison_number != 0
        else "Not available"
    )
    return absolute, relative


def comparison_bar(
    frame: pd.DataFrame,
    category: str,
    *,
    current: str = "current",
    comparison: str = "comparison",
    label: str,
    value_format: str = "decimal",
    comparison_label: str = "Comparison",
    current_denominator: str | None = None,
    comparison_denominator: str | None = None,
    display_title: bool = False,
) -> go.Figure:
    """Compare aligned current/prior segments with exact values and optional sample sizes."""
    required = {category, current, comparison}
    if frame.empty or not required.issubset(frame.columns):
        return empty_figure("No comparison evidence is available")
    frame = frame.copy()
    for column in (current, comparison):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame.loc[~np.isfinite(frame[column]), column] = np.nan
    if frame[[current, comparison]].notna().sum().sum() == 0:
        return empty_figure("No numeric comparison evidence is available")
    if "absolute_delta" in frame:
        frame["absolute_delta"] = pd.to_numeric(
            frame["absolute_delta"], errors="coerce"
        )
        frame.loc[~np.isfinite(frame["absolute_delta"]), "absolute_delta"] = np.nan
    sort_values = (
        frame["absolute_delta"].abs()
        if "absolute_delta" in frame
        else pd.to_numeric(frame[current], errors="coerce").abs()
    )
    ordered = frame.assign(_sort_value=sort_values).sort_values(
        "_sort_value", ascending=False
    )
    customdata: list[list[str]] = []
    for _, row in ordered.iterrows():
        absolute, relative = _change_display(row[current], row[comparison], value_format)
        provided_delta = _safe_number(row.get("absolute_delta"))
        if absolute == "Not available" and provided_delta is not None:
            absolute = _absolute_change_display(provided_delta, value_format)
        current_n = (
            _optional_display_value(row[current_denominator], "integer")
            if current_denominator and current_denominator in ordered
            else "Not provided"
        )
        comparison_n = (
            _optional_display_value(row[comparison_denominator], "integer")
            if comparison_denominator and comparison_denominator in ordered
            else "Not provided"
        )
        customdata.append(
            [
                _optional_display_value(row[current], value_format),
                _optional_display_value(row[comparison], value_format),
                absolute,
                relative,
                current_n,
                comparison_n,
            ]
        )
    denominator_lines = ""
    if current_denominator or comparison_denominator:
        denominator_lines = (
            "<br>Current denominator: %{customdata[4]}"
            "<br>Comparison denominator: %{customdata[5]}"
        )
    hover = (
        "<b>%{y}</b><br>"
        f"Current {label}: %{{customdata[0]}}<br>"
        f"{comparison_label} {label}: %{{customdata[1]}}<br>"
        "Absolute change: %{customdata[2]}<br>"
        "Relative change: %{customdata[3]}"
        f"{denominator_lines}<extra></extra>"
    )
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=ordered[current],
            y=ordered[category],
            orientation="h",
            name="Current",
            marker_color=NAVY,
            customdata=customdata,
            hovertemplate=hover,
            text=[
                ""
                if _safe_number(value) is None
                else _display_bar_value(float(value), value_format)
                for value in ordered[current]
            ],
            textposition="outside",
            cliponaxis=False,
        )
    )
    figure.add_trace(
        go.Bar(
            x=ordered[comparison],
            y=ordered[category],
            orientation="h",
            name=comparison_label,
            marker_color=COMPARISON,
            customdata=customdata,
            hovertemplate=hover,
            text=[
                ""
                if _safe_number(value) is None
                else _display_bar_value(float(value), value_format)
                for value in ordered[comparison]
            ],
            textposition="outside",
            cliponaxis=False,
        )
    )
    figure.update_layout(
        title=dict(text=label, font=dict(size=16)) if display_title else None,
        barmode="group",
    )
    figure.update_yaxes(
        categoryorder="array",
        categoryarray=ordered[category].tolist()[::-1],
        automargin=True,
    )
    values = pd.concat(
        [
            pd.to_numeric(ordered[current], errors="coerce"),
            pd.to_numeric(ordered[comparison], errors="coerce"),
        ]
    )
    figure = _base_layout(figure)
    figure.update_layout(margin=dict(l=130, r=32, t=44 if display_title else 30, b=32))
    figure.update_xaxes(
        range=_numeric_range(values, label_padding=0.12),
        zeroline=True,
        zerolinecolor=MUTED,
        **_axis_style(value_format),
    )
    return figure

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from html import escape
import hashlib
import re
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit_shadcn_ui as ui

from dashboard.charts import (
    funnel_chart,
    grouped_bar,
    ranked_bar,
    trend_chart,
)
from dashboard.data import DatabaseMetadata
from dashboard.display import dataframe_column_config
from dashboard.filters import comparison_period
from dashboard.guide import render_data_guide
from dashboard.labels import display_label
from dashboard.metrics import (
    acquisition_performance,
    aggregate_product_trend,
    basket_mix,
    funnel_breakdown,
    funnel_summary,
    overview_drivers,
    overview_kpis,
    overview_trend,
    product_performance,
    product_trend,
)
from dashboard.models import DatePeriod, FilterSpec
from dashboard.options import (
    acquisition_filter_options,
    funnel_filter_options,
    product_filter_options,
    session_dimension_values,
)
from dashboard.theme import BACKGROUND, BORDER, GOLD, INK, MUTED, NAVY, NEGATIVE, WHITE


PAGES = ("Executive Overview", "Acquisition", "Website Funnel", "Products & Refunds", "Data Guide")

PAGE_COPY = {
    "Executive Overview": (
        "Executive Overview",
        "A concise read on revenue health, demand, conversion, margin, and refunds.",
    ),
    "Acquisition": (
        "Acquisition",
        "Compare the quality—not just the volume—of channels, campaigns, and devices.",
    ),
    "Website Funnel": (
        "Website Funnel",
        "See how session cohorts move from their landing page through order confirmation.",
    ),
    "Products & Refunds": (
        "Products & Refunds",
        "Track product economics, basket composition, attach behavior, and refund exposure.",
    ),
}

METRIC_META = {
    "revenue": ("Revenue", "currency"),
    "gross_revenue": ("Gross revenue", "currency"),
    "net_revenue": ("Net revenue", "currency"),
    "orders": ("Orders", "integer"),
    "sessions": ("Sessions", "integer"),
    "conversion_rate": ("Conversion rate", "percent"),
    "aov": ("Average order value", "currency"),
    "gross_margin": ("Gross margin", "currency"),
    "refund_rate": ("Refund rate", "percent"),
    "refund_amount": ("Refunded amount", "currency"),
    "revenue_per_session": ("Revenue / session", "currency"),
    "margin_per_session": ("Margin / session", "currency"),
    "units": ("Units sold", "integer"),
    "refunded_amount": ("Refunded amount", "currency"),
    "attachment_rate": ("Attachment rate", "percent"),
}

CARD_FORMULAS = {
    "overview": {
        "orders": "Orders = count of orders placed in the selected period",
        "sessions": "Sessions = count of website sessions started in the selected period",
        "conversion_rate": "Conversion rate = orders ÷ sessions × 100%",
        "aov": "Average order value = gross order revenue ÷ orders",
        "refund_rate": "Refund rate = refund events recorded in the selected period ÷ items sold in the selected period × 100%",
        "net_revenue": "Net revenue = gross order revenue − refund amount",
    },
    "acquisition": {
        "sessions": "Sessions = count of sessions in the selected acquisition cohort",
        "orders": "Orders = count of orders linked to those sessions",
        "conversion_rate": "Conversion rate = linked orders ÷ selected sessions × 100%",
        "revenue_per_session": "Revenue per session = revenue from linked orders ÷ selected sessions",
    },
    "funnel": {
        "sessions": "Sessions = count of selected-cohort sessions reaching the landing stage",
        "orders": "Orders = count of selected-cohort sessions reaching the Thank-you stage",
        "conversion_rate": "Conversion rate = Thank-you-stage sessions ÷ landing-stage sessions × 100%",
    },
    "products": {
        "revenue": "Revenue = sum of selected order-item prices",
        "units": "Units sold = count of selected order items",
        "gross_margin": "Gross margin = selected item revenue − selected item COGS",
    },
}

def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root { --navy:__NAVY__; --gold:__GOLD__; --ink:__INK__; --muted:__MUTED__; --line:__BORDER__; --soft:__BACKGROUND__; --white:__WHITE__; }
        [data-testid="stHeader"], [data-testid="stSidebar"] { display:none; }
        .stApp { background: var(--soft); color: var(--ink); }
        .block-container { max-width:1600px; padding:1rem 1.25rem 2.5rem; }
        .brand { display:flex; align-items:center; min-height:2.55rem; min-width:0; transform:translateY(-.45rem); }
        .brand-name { color:var(--ink); font-size:1.02rem; font-weight:780; line-height:1.2; letter-spacing:-.025em; white-space:nowrap; }
        .page-title { font-size:1.75rem; line-height:1.12; letter-spacing:-.035em; color:var(--ink); font-weight:780; margin:0; }
        .page-subtitle { color:var(--muted); font-size:.9rem; margin:.3rem 0 .58rem; max-width:54rem; }
        .context-chip { display:inline-flex; align-items:center; padding:.28rem .58rem; border:1px solid #DDE3F3; border-radius:999px; background:#F8F7FF; color:#4D4A68; font-size:.72rem; font-weight:600; margin:0 .28rem .25rem 0; }
        .section-title { font-size:.96rem; font-weight:740; color:var(--ink); margin:.82rem 0 .06rem; letter-spacing:-.01em; }
        .section-note { color:var(--muted); font-size:.76rem; margin:.08rem 0 .28rem; }
        .section-chip-row { display:flex; flex-wrap:wrap; gap:.3rem; margin:.14rem 0 0; padding-bottom:.62rem; }
        .section-chip { display:inline-flex; align-items:center; padding:.24rem .5rem; border:1px solid #DDE3F3; border-radius:7px; background:#F8F7FF; color:#4D4A68; font-size:.7rem; font-weight:600; line-height:1.2; }
        .empty-state { background:var(--white); border:1px solid var(--line); border-radius:14px; padding:2rem 1.5rem; text-align:center; box-shadow:0 6px 20px rgba(24,39,75,.045); margin-top:.6rem; }
        .empty-state-title { color:var(--ink); font-size:1.05rem; font-weight:760; }
        .empty-state-copy { color:var(--muted); font-size:.84rem; margin-top:.3rem; }
        [data-testid="stMetric"] { background:var(--white); border:1px solid var(--line); border-radius:12px; padding:.72rem .82rem; box-shadow:0 4px 14px rgba(24,39,75,.045); }
        [data-testid="stMetricLabel"] { color:var(--muted); }
        [data-testid="stMetricValue"] { color:var(--ink); font-weight:730; letter-spacing:-.035em; }
        [data-testid="stTooltipContent"] {
          width:min(23rem, calc(100vw - 2rem)) !important; box-sizing:border-box;
          max-height:none !important; overflow:visible !important;
          padding:.82rem .9rem !important; background:#F8FAFD !important;
          border:1px solid #D9E0EA; border-radius:12px !important;
          box-shadow:0 14px 34px rgba(24,39,75,.16);
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] h5 {
          margin:.72rem 0 .3rem; color:#667085; font-size:.67rem; line-height:1.25;
          font-weight:760; letter-spacing:.075em; text-transform:uppercase;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] h5:first-child { margin-top:0; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] p { margin:0; line-height:1.42; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] blockquote {
          margin:0; padding:.5rem .62rem; background:#FFFFFF; border-left:3px solid var(--gold);
          border-radius:0 7px 7px 0; color:var(--ink);
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] blockquote p {
          color:var(--ink) !important; font-size:.82rem;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] table {
          width:100%; margin:0; border:1px solid #DDE3EC; border-radius:8px;
          border-spacing:0; overflow:hidden; background:#FFFFFF; font-size:.73rem;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] th {
          padding:.34rem .42rem; background:#EEF2F7; color:#667085; font-size:.62rem;
          font-weight:750; letter-spacing:.04em; text-transform:uppercase; text-align:left;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] td {
          padding:.4rem .42rem; border-top:1px solid #E6EAF0; vertical-align:top; line-height:1.3;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] th:last-child,
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] td:last-child { text-align:right; white-space:nowrap; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] em {
          display:block; margin-top:.38rem; color:#667085; font-size:.7rem; line-height:1.35;
        }
        [data-testid="stPlotlyChart"] { background:var(--white); border:1px solid var(--line); border-radius:14px; padding:0; overflow:hidden !important; box-sizing:border-box; box-shadow:0 6px 20px rgba(24,39,75,.045); }
        [data-testid="stElementContainer"]:has([data-testid="stPlotlyChart"]) { overflow:hidden !important; }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line); background:var(--white); border-radius:14px; box-shadow:0 5px 18px rgba(24,39,75,.04); }
        .st-key-top_nav_shell {
          padding:.42rem 1.25rem 0 !important; margin:-1rem -1.25rem 0 !important;
          background:#E9EDF5 !important; border:0 !important; border-bottom:1px solid #D8DEE8 !important;
          border-radius:0 !important; box-shadow:none !important;
        }
        .st-key-app_workspace { margin:0 -1.25rem -2.5rem !important; }
        .st-key-app_workspace > div[data-testid="stVerticalBlock"] { gap:0 !important; }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child {
          background:var(--white); border-right:1px solid var(--line); padding:.85rem 1rem 2rem 1.25rem;
          min-height:calc(100vh - 3.25rem);
        }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child:has(.page-title) {
          padding:.85rem 1.25rem 2.5rem 1rem;
        }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:0 4px 14px rgba(24,39,75,.035); }
        .st-key-data_guide_workspace {
          width:100%; max-width:1440px; margin:0 auto;
          padding:1.05rem clamp(1.75rem, 4vw, 4rem) 2.5rem;
          box-sizing:border-box;
        }
        .st-key-data_guide_workspace > div[data-testid="stVerticalBlock"] { gap:.72rem; }
        .st-key-data_guide_workspace [data-testid="stMetric"] { padding:.65rem .75rem; }
        .st-key-data_guide_workspace [data-testid="stMetricValue"] {
          font-size:1.22rem; font-weight:660; letter-spacing:-.018em;
        }
        div[class*="st-key-guide_fields_"] {
          background:#F2EFFF; border:1px solid #DDD6FE; border-radius:13px;
          padding:.72rem .78rem .82rem; margin:.28rem 0 .5rem;
        }
        div[class*="st-key-guide_sample_"] {
          background:#F0F7FF; border:1px solid #D6E7F7; border-radius:13px;
          padding:.72rem .78rem .82rem; margin:.28rem 0 .2rem;
        }
        div[class*="st-key-guide_fields_"] h5,
        div[class*="st-key-guide_sample_"] h5 { margin:.05rem 0 .28rem; color:var(--ink); }
        .erd-wrap {
          margin:.12rem 0 1.2rem; padding:.7rem .7rem .55rem; overflow-x:auto;
          border:1px solid var(--line); border-radius:12px; background:var(--white);
        }
        .erd-svg {
          display:block; width:100%; min-width:40rem; max-width:44rem;
          height:auto; margin:0 auto;
        }
        .erd-entity-box { fill:#FFFFFF; stroke:#D9DFE9; stroke-width:1.5; }
        .erd-entity-header { fill:#EDE9FE; }
        .erd-row-line { stroke:#E8ECF2; stroke-width:1; }
        .erd-title { fill:#342B61; font-size:14px; font-weight:740; }
        .erd-key { fill:#6D5BD0; font-size:10px; font-weight:780; }
        .erd-field { fill:#344054; font-size:13px; font-weight:520; }
        .erd-links path { fill:none; stroke:#98A2B3; stroke-width:2; }
        .erd-links text { fill:#475467; font-size:11px; font-weight:760; }
        .erd-legend {
          display:flex; flex-wrap:wrap; gap:.45rem 1rem; padding:.35rem .2rem 0;
          color:#667085; font-size:.7rem; line-height:1.35;
        }
        .erd-legend b { color:#5E4FC4; font-weight:780; }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] [data-baseweb="button-group"],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radiogroup"] {
          width:fit-content !important; justify-content:flex-start !important; align-items:flex-end !important;
          background:transparent !important; border:0 !important; border-radius:0 !important;
          padding:0 !important; gap:.12rem; box-shadow:none !important;
        }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button,
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"] {
          flex:0 0 auto !important; width:auto !important; min-height:2.55rem; border:0 !important;
          border-radius:11px 11px 0 0 !important; background:transparent !important; color:#596273 !important;
          font-size:.84rem; font-weight:590; padding:.48rem .88rem .52rem; box-shadow:none !important;
          transition:background-color .16s ease, color .16s ease, box-shadow .16s ease !important;
        }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button:hover,
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"]:hover { background:rgba(255,255,255,.48) !important; color:var(--ink) !important; }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"][data-selected],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"][aria-checked="true"] {
          color:var(--ink) !important; background:var(--soft) !important; font-weight:700;
          box-shadow:0 -1px 0 rgba(255,255,255,.45), 1px 0 0 rgba(16,24,40,.035), -1px 0 0 rgba(16,24,40,.035) !important;
        }
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"]:focus-visible { outline:2px solid #1A73E8 !important; outline-offset:2px; }
        div[data-testid="stSegmentedControl"] button:focus-visible,
        div[data-testid="stButtonGroup"] [role="radio"]:focus-visible,
        div[data-testid="stPopover"] button:focus-visible,
        input:focus-visible, [role="combobox"]:focus-visible {
          outline:2px solid var(--navy) !important; outline-offset:2px;
        }
        [data-testid="stPopover"] button { width:100%; justify-content:space-between; min-height:2.08rem; border-radius:9px; border-color:var(--line); }
        [data-testid="stPopoverBody"] { max-height:min(62vh, 30rem); overflow-y:auto; }
        [data-testid="stVerticalBlock"] { gap:.56rem; }
        [data-testid="stSelectbox"] label, [data-testid="stSlider"] label { color:#475467; font-size:.76rem; font-weight:680; }
        [data-testid="stSelectSlider"] label { color:#475467; font-size:.76rem; font-weight:680; }
        hr { margin:.35rem 0 .6rem !important; border-color:var(--line) !important; }
        @media (min-width: 769px) {
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child > div {
            position:sticky; top:.65rem; align-self:flex-start;
          }
        }
        @media (max-width: 768px) {
          .block-container { padding:.55rem .8rem 1.5rem; }
          .page-title { font-size:1.5rem; }
          .brand { min-height:2.2rem; padding-bottom:.15rem; }
          div[data-testid="stSegmentedControl"] [data-baseweb="button-group"],
          div[data-testid="stButtonGroup"] [role="radiogroup"] { overflow-x:auto; justify-content:flex-start; }
          div[data-testid="stSegmentedControl"] button,
          div[data-testid="stButtonGroup"] [role="radio"] { flex:0 0 auto; white-space:nowrap; }
          [data-testid="stPopoverBody"] { max-width:calc(100vw - 2rem); max-height:55vh; }
          .st-key-data_guide_workspace { padding:.8rem 1rem 1.5rem; }
        }
        </style>
        """
        .replace("__NAVY__", NAVY)
        .replace("__GOLD__", GOLD)
        .replace("__INK__", INK)
        .replace("__MUTED__", MUTED)
        .replace("__BORDER__", BORDER)
        .replace("__BACKGROUND__", BACKGROUND)
        .replace("__WHITE__", WHITE),
        unsafe_allow_html=True,
    )


def _option_state_key(key: str, option: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", option.lower()).strip("_")[:28]
    digest = hashlib.sha1(option.encode("utf-8")).hexdigest()[:8]
    return f"{key}__item__{slug}__{digest}"


def format_filter_option(option: str) -> str:
    return display_label(option)


def _plural_filter_label(label: str) -> str:
    return {
        "Traffic source": "traffic sources",
        "Campaign": "campaigns",
        "Device": "devices",
        "Session type": "session types",
        "Ad content": "ad content values",
        "Referrer type": "referrer types",
        "Landing page": "landing pages",
        "Product page": "product pages",
        "Product": "products",
        "Item role": "item roles",
        "Order size": "order sizes",
    }.get(label, f"{label.lower()} values")


def selection_summary(
    label: str,
    options: tuple[str, ...],
    selected: tuple[str, ...],
    *,
    all_label: str,
) -> str:
    plural = _plural_filter_label(label)
    if not options:
        return f"No compatible {plural}"
    selected_set = set(selected)
    selected_values = tuple(option for option in options if option in selected_set)
    if not selected_values:
        return f"No {plural}"
    if len(selected_values) == len(options):
        return all_label
    formatted = tuple(format_filter_option(option) for option in selected_values)
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        joined = " + ".join(formatted)
        return joined if len(joined) <= 26 else "2 selected"
    return f"{len(formatted)} selected"


def _filter_accessible_description(label: str, summary: str) -> str:
    return f"{label} filter. Current selection: {summary}."


def filter_trigger_label(label: str, summary: str) -> str:
    return f"{label}: {summary}"


def checkbox_group(
    label: str,
    options: tuple[str, ...],
    key: str,
    *,
    all_label: str,
) -> tuple[str, ...]:
    generation = int(st.session_state.get("filter_reset_generation", 0))
    state_key = f"{key}__selected"
    if not options:
        empty_summary = selection_summary(label, options, (), all_label=all_label)
        ui.combobox(
            label,
            (),
            value=(),
            selection_mode="multiple",
            placeholder=empty_summary,
            key=f"{key}__empty__{generation}",
            disabled=True,
            width="stretch",
        )
        return ()
    previous = tuple(st.session_state.get(state_key, ()))
    selected_default = tuple(option for option in previous if option in options)
    removed = tuple(option for option in previous if option not in options)
    if removed:
        removed_copy = ", ".join(format_filter_option(value) for value in removed)
        st.toast(
            f"Unavailable {label.lower()} selection removed: {removed_copy}",
            icon="🔄",
        )
    explicit = tuple(
        ui.combobox(
            label,
            options,
            value=selected_default,
            selection_mode="multiple",
            clearable=True,
            placeholder=all_label,
            format_func=format_filter_option,
            key=f"{key}__{generation}",
            width="stretch",
        )
    )
    st.session_state[state_key] = explicit
    return explicit or options


def _ui_select(
    label: str,
    options: tuple[str, ...],
    key: str,
    *,
    default: str | None = None,
    format_func=lambda value: value,
) -> str:
    generation = int(st.session_state.get("filter_reset_generation", 0))
    state_key = f"{key}__value"
    fallback = default or options[0]
    current = st.session_state.get(state_key, fallback)
    if current not in options:
        current = fallback
    selected = ui.select(
        label,
        options,
        value=current,
        format_func=format_func,
        key=f"{key}__{generation}",
        width="stretch",
    )
    st.session_state[state_key] = selected
    return selected


@st.cache_data(show_spinner=False, ttl=3600)
def cached_session_dimension_values(
    path: str,
    period: DatePeriod,
    filters: FilterSpec,
    dimension: str,
) -> tuple[str, ...]:
    return session_dimension_values(path, period, filters, dimension)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_acquisition_filter_options(
    path: str, period: DatePeriod, filters: FilterSpec
) -> dict[str, tuple[str, ...]]:
    return acquisition_filter_options(path, period, filters)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_funnel_filter_options(
    path: str, period: DatePeriod, filters: FilterSpec
) -> dict[str, tuple[str, ...]]:
    return funnel_filter_options(path, period, filters)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_product_filter_options(
    path: str, period: DatePeriod, filters: FilterSpec
) -> dict[str, tuple[str, ...]]:
    return product_filter_options(path, period, filters)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_overview_kpis(path: str, filters: FilterSpec, period: DatePeriod, basis: str):
    return overview_kpis(path, filters, period, revenue_basis=basis)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_overview_trend(path: str, filters: FilterSpec, period: DatePeriod, grain: str, basis: str):
    return overview_trend(path, filters, period, grain=grain, revenue_basis=basis)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_acquisition(path: str, filters: FilterSpec, period: DatePeriod, dimension: str, landings):
    return acquisition_performance(path, filters, period, dimension=dimension, landing_pages=landings)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_funnel(path: str, filters: FilterSpec, period: DatePeriod, landings, products, version):
    return funnel_summary(path, filters, period, landing_pages=landings, product_pages=products, funnel_version=version)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_funnel_breakdown(path: str, filters: FilterSpec, period: DatePeriod, dimension: str, landings, products, version):
    return funnel_breakdown(
        path,
        filters,
        period,
        compare_by=dimension,
        landing_pages=landings,
        product_pages=products,
        funnel_version=version,
    )


@st.cache_data(show_spinner=False, ttl=3600)
def cached_products(path: str, filters: FilterSpec, period: DatePeriod, products, roles, sizes, basis):
    return product_performance(path, filters, period, products=products, item_roles=roles, order_sizes=sizes, date_basis=basis)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_product_trend(path: str, filters: FilterSpec, period: DatePeriod, products, roles, sizes, basis):
    return product_trend(path, filters, period, products=products, item_roles=roles, order_sizes=sizes, date_basis=basis)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_basket(path: str, filters: FilterSpec, period: DatePeriod, products, roles, sizes):
    return basket_mix(path, filters, period, products=products, item_roles=roles, order_sizes=sizes)


def _months(metadata: DatabaseMetadata) -> tuple[str, ...]:
    if not metadata.session_min or not metadata.session_max:
        return ()
    current = datetime.strptime(metadata.session_min[:7], "%Y-%m")
    final = datetime.strptime(metadata.session_max[:7], "%Y-%m")
    values = []
    while current <= final:
        values.append(current.strftime("%Y-%m"))
        index = current.year * 12 + current.month
        current = datetime(index // 12, index % 12 + 1, 1)
    return tuple(values)


def _reporting_window_months(
    months: tuple[str, ...],
    window: str,
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> tuple[str, str]:
    if not months:
        raise ValueError("Reporting windows require at least one month.")
    lengths = {
        "Latest 12 months": 12,
        "Latest 6 months": 6,
        "Latest 3 months": 3,
    }
    if window == "All history":
        return months[0], months[-1]
    if window == "Custom":
        if custom_start not in months or custom_end not in months:
            raise ValueError("Custom reporting months must exist in the dataset.")
        return tuple(sorted((custom_start, custom_end)))
    if window not in lengths:
        raise ValueError(f"Unknown reporting window: {window}")
    length = lengths[window]
    return months[max(0, len(months) - length)], months[-1]


def _format_value(value: float | int, value_format: str) -> str:
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


def _delta(current: float, previous: float | None) -> str | None:
    if previous is None or previous == 0:
        return None
    return f"{(current - previous) / abs(previous):+.2%}"


def _metric_formula(scope: str, key: str, context: dict[str, str] | None = None) -> str:
    context = context or {}
    if scope == "overview" and key == "revenue":
        if context.get("revenue_basis") == "Net":
            return "Revenue (net basis) = gross order revenue − refund amount"
        return "Revenue (gross basis) = sum of order revenue (orders.price_usd)"
    if scope == "overview" and key == "gross_margin":
        if context.get("revenue_basis") == "Net":
            return "Gross margin (net basis) = gross order revenue − order COGS − refund amount"
        return "Gross margin = gross order revenue − order COGS"
    if scope == "products" and key == "refund_rate":
        if context.get("date_basis") == "Refund date":
            return "Refund rate = refund events in the selected period ÷ units purchased in the same calendar period × 100%"
        return "Refund rate = items from the selected purchase cohort that were later refunded ÷ units in that purchase cohort × 100%"
    try:
        return CARD_FORMULAS[scope][key]
    except KeyError as error:
        raise ValueError(f"No card formula is defined for {scope}.{key}") from error


def _comparison_rule(compare: str, period: DatePeriod) -> str:
    if compare == "Previous period":
        unit = "month" if period.month_count == 1 else "months"
        return f"Immediately preceding {period.month_count} calendar {unit}, matching the current window length."
    if compare == "Previous year":
        return "The same calendar window one year earlier."
    if compare == "None":
        return "No comparison selected; no relative change is shown."
    raise ValueError(f"Unsupported comparison mode: {compare}")


def _metric_help(
    key: str,
    current: float,
    prior: float | None,
    value_format: str,
    compare: str,
    period: DatePeriod,
    prior_period: DatePeriod | None,
    scope: str,
    context: dict[str, str] | None = None,
) -> str:
    table = [
        "| Window | Period | Value |",
        "| --- | --- | ---: |",
        f"| Current | {period.label} | **{_format_value(current, value_format)}** |",
    ]
    if prior is not None and prior_period is not None:
        table.append(
            f"| {compare} | {prior_period.label} | **{_format_value(prior, value_format)}** |"
        )

    details = [
        "##### Metric formula",
        f"> {_metric_formula(scope, key, context)}",
        "##### Values by period",
        "\n".join(table),
    ]
    details.append(f"*{_comparison_rule(compare, period)}*")
    if prior == 0:
        details.append("*Relative change is not shown because the comparison value is zero.*")
    return "\n\n".join(details)


def _format_detail_table(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    percent_columns = {
        "conversion_rate",
        "step_conversion",
        "total_conversion",
        "total_conversion_comparison",
        "refund_rate",
        "attachment_rate",
    }
    integer_columns = {
        "sessions",
        "orders",
        "units",
        "units_refunded",
        "drop_off",
    }
    renamed = {}
    for column in display.columns:
        if column in percent_columns:
            display[column] = (display[column] * 100).round(2)
            renamed[column] = f"{column.replace('_', ' ').title()} (%)"
        elif column in integer_columns:
            display[column] = display[column].round(0).astype("Int64")
            renamed[column] = column.replace("_", " ").title()
        elif pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].round(2)
            renamed[column] = column.replace("_", " ").title()
        else:
            renamed[column] = column.replace("_", " ").title()
    return display.rename(columns=renamed)


def _render_detail_table(frame: pd.DataFrame) -> None:
    display = _format_detail_table(frame)
    display_names = {source: target for source, target in zip(frame.columns, display.columns)}
    st.dataframe(
        display,
        column_config=dataframe_column_config(frame, display_names),
        width="stretch",
        hide_index=True,
    )


def render_metrics(
    current: dict,
    previous: dict | None,
    keys: tuple[str, ...],
    compare: str,
    period: DatePeriod,
    prior_period: DatePeriod | None,
    scope: str,
    context: dict[str, str] | None = None,
) -> None:
    for row_start in range(0, len(keys), 4):
        row_keys = keys[row_start : row_start + 4]
        columns = st.columns(len(row_keys), gap="small")
        for column, key in zip(columns, row_keys):
            label, value_format = METRIC_META[key]
            value = float(current.get(key, 0))
            prior = float(previous.get(key, 0)) if previous else None
            delta = _delta(value, prior)
            column.metric(
                label,
                _format_value(value, value_format),
                delta,
                help=_metric_help(
                    key,
                    value,
                    prior,
                    value_format,
                    compare,
                    period,
                    prior_period,
                    scope,
                    context,
                ),
                delta_description=f"vs. {compare.lower()}" if delta else None,
            )


def _context_chips(period: DatePeriod, compare: str, filters: FilterSpec, metadata: DatabaseMetadata) -> None:
    chips = [period.label, compare]
    explicit_sources = tuple(st.session_state.get("global_source__selected", ()))
    explicit_devices = tuple(st.session_state.get("global_device__selected", ()))
    if explicit_sources:
        chips.append(" + ".join(explicit_sources))
    if explicit_devices:
        chips.append(" + ".join(value.title() for value in explicit_devices))
    if metadata.session_max:
        chips.append(f"Data through {datetime.fromisoformat(metadata.session_max).strftime('%b %d, %Y')}")
    st.markdown(
        "".join(f"<span class='context-chip'>{chip}</span>" for chip in chips),
        unsafe_allow_html=True,
    )


def _page_header(page: str, period: DatePeriod, compare: str, filters: FilterSpec, metadata: DatabaseMetadata) -> None:
    title, subtitle = PAGE_COPY[page]
    st.markdown(f"<h1 class='page-title'>{title}</h1>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-subtitle'>{subtitle}</div>", unsafe_allow_html=True)
    _context_chips(period, compare, filters, metadata)


def _section(title: str, note: str = "", *, chips: tuple[str, ...] = ()) -> None:
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    if chips:
        chip_markup = "".join(
            f"<span class='section-chip'>{escape(chip)}</span>" for chip in chips
        )
        st.markdown(
            f"<div class='section-chip-row'>{chip_markup}</div>",
            unsafe_allow_html=True,
        )
    elif note:
        st.markdown(f"<div class='section-note'>{note}</div>", unsafe_allow_html=True)


def _reset_analysis_filters() -> None:
    prefixes = ("global_", "overview_", "acq_", "funnel_", "product_")
    for key in tuple(st.session_state):
        if key.startswith(prefixes):
            del st.session_state[key]
    st.session_state["filter_reset_generation"] = int(
        st.session_state.get("filter_reset_generation", 0)
    ) + 1


def _empty_state(page: str) -> None:
    st.markdown(
        f"<div class='empty-state'><div class='empty-state-title'>No matching {page.lower()} records</div>"
        "<div class='empty-state-copy'>The filters are valid, but this page has no business records in the selected window. "
        "Reset the workspace or choose a broader reporting window.</div></div>",
        unsafe_allow_html=True,
    )
    ui.button(
        "Reset analysis filters",
        key=f"empty_reset_{page}",
        variant="outline",
        on_click=_reset_analysis_filters,
        width="stretch",
    )


def _global_filters(path: str, metadata: DatabaseMetadata) -> tuple[DatePeriod, str, FilterSpec]:
    _section("Global filters", "Shared across every analysis workspace")
    months = _months(metadata)
    if not months:
        st.error("The session table is empty.")
        st.stop()
    window = _ui_select(
        "Reporting window",
        ("Latest 12 months", "Latest 6 months", "Latest 3 months", "All history", "Custom"),
        key="global_date_window",
    )
    if window == "All history":
        chosen = _reporting_window_months(months, window)
    elif window == "Custom":
        custom_start = _ui_select(
            "Start month",
            months,
            default=months[max(0, len(months) - 12)],
            format_func=lambda value: datetime.strptime(value, "%Y-%m").strftime("%b %Y"),
            key="global_custom_start",
        )
        custom_end = _ui_select(
            "End month",
            months,
            default=months[-1],
            format_func=lambda value: datetime.strptime(value, "%Y-%m").strftime("%b %Y"),
            key="global_custom_end",
        )
        chosen = _reporting_window_months(months, window, custom_start, custom_end)
    else:
        chosen = _reporting_window_months(months, window)
    compare = _ui_select(
        "Compare with",
        ("Previous period", "Previous year", "None"),
        key="global_compare",
    )
    period = DatePeriod.from_months(chosen[0], chosen[1])
    source_options = cached_session_dimension_values(
        path, period, FilterSpec(), "traffic_source"
    )
    sources = checkbox_group(
        "Traffic source",
        source_options,
        "global_source",
        all_label="All traffic sources",
    )
    source_filters = FilterSpec(traffic_sources=sources)
    campaign_options = cached_session_dimension_values(
        path, period, source_filters, "campaign"
    )
    campaigns = checkbox_group(
        "Campaign", campaign_options, "global_campaign", all_label="All campaigns"
    )
    campaign_filters = FilterSpec(traffic_sources=sources, campaigns=campaigns)
    device_options = cached_session_dimension_values(
        path, period, campaign_filters, "device"
    )
    devices = checkbox_group(
        "Device", device_options, "global_device", all_label="All devices"
    )
    device_filters = FilterSpec(
        traffic_sources=sources,
        campaigns=campaigns,
        devices=devices,
    )
    session_type_options = cached_session_dimension_values(
        path, period, device_filters, "session_type"
    )
    session_types = checkbox_group(
        "Session type",
        session_type_options,
        "global_session_type",
        all_label="All session types",
    )
    ui.button(
        "Reset analysis filters",
        key="reset_analysis_filters",
        variant="outline",
        on_click=_reset_analysis_filters,
        width="stretch",
    )
    return (
        period,
        compare,
        FilterSpec(
            traffic_sources=sources,
            campaigns=campaigns,
            devices=devices,
            session_types=session_types,
        ),
    )


def _render_overview_filters() -> dict:
    _section("Overview controls")
    return {
        "grain": _ui_select("Time grain", ("Month", "Week", "Day", "Quarter"), key="overview_grain"),
        "basis": _ui_select("Revenue basis", ("Gross", "Net"), key="overview_basis"),
        "primary": _ui_select(
            "Primary KPI",
            ("Revenue", "Orders", "Sessions", "Conversion rate", "Average order value", "Gross margin", "Refund rate"),
            key="overview_primary",
        ),
    }


def _render_acquisition_filters(options: dict) -> dict:
    _section("Acquisition controls")
    ad_contents = checkbox_group(
        "Ad content", options["ad"], "acq_ad", all_label="All ad content"
    )
    referrers = checkbox_group(
        "Referrer type",
        options["referrer"],
        "acq_referrer",
        all_label="All referrer types",
    )
    landings = checkbox_group(
        "Landing page", options["landing"], "acq_landing", all_label="All landing pages"
    )
    metric = _ui_select(
        "Metric",
        ("Sessions", "Orders", "Conversion rate", "Revenue per session", "Gross margin per session"),
        key="acq_metric",
    )
    return {"ad_contents": ad_contents, "referrers": referrers, "landings": landings, "metric": metric}


def _render_funnel_filters(options: dict) -> dict:
    _section("Funnel controls")
    landings = checkbox_group(
        "Landing page", options["landing"], "funnel_landing", all_label="All landing pages"
    )
    selected_products = checkbox_group(
        "Product page",
        options["product_page"],
        "funnel_product",
        all_label="All product pages",
    )
    products = None if selected_products == options["product_page"] else selected_products
    version = _ui_select("Funnel version", ("All", "Original", "Optimized"), key="funnel_version")
    compare_by = _ui_select(
        "Compare by", ("Device", "Traffic source", "Campaign", "Landing page"), key="funnel_compare"
    )
    return {"landings": landings, "products": products, "version": version, "compare_by": compare_by}


def _render_product_filters(options: dict) -> dict:
    _section("Product controls")
    products = checkbox_group(
        "Product", options["product"], "product_names", all_label="All products"
    )
    roles = checkbox_group(
        "Item role", options["item_role"], "product_role", all_label="All item roles"
    )
    sizes = checkbox_group(
        "Order size",
        options["order_size"],
        "product_size",
        all_label="All order sizes",
    )
    basis = _ui_select("Date basis", ("Purchase date", "Refund date"), key="product_basis")
    metric = _ui_select(
        "Metric",
        ("Revenue", "Units sold", "Gross margin", "Refund rate", "Refunded amount", "Attachment rate"),
        key="product_metric",
    )
    return {
        "products": products,
        "roles": roles,
        "sizes": sizes,
        "basis": basis,
        "metric": metric,
        "product_scope": selection_summary(
            "Product", options["product"], products, all_label="All products"
        ),
        "role_scope": selection_summary(
            "Item role", options["item_role"], roles, all_label="All item roles"
        ),
        "size_scope": selection_summary(
            "Order size", options["order_size"], sizes, all_label="All order sizes"
        ),
    }


def render_overview(path: str, metadata: DatabaseMetadata, period: DatePeriod, compare: str, filters: FilterSpec, controls: dict) -> None:
    _page_header("Executive Overview", period, compare, filters, metadata)
    prior_period = comparison_period(period, compare)
    current = cached_overview_kpis(path, filters, period, controls["basis"])
    prior = cached_overview_kpis(path, filters, prior_period, controls["basis"]) if prior_period else None
    if not current.get("sessions") and not current.get("orders"):
        _empty_state("overview")
        return
    render_metrics(
        current,
        prior,
        ("revenue", "orders", "sessions", "conversion_rate", "aov", "gross_margin", "refund_rate", "net_revenue"),
        compare,
        period,
        prior_period,
        "overview",
        {"revenue_basis": controls["basis"]},
    )

    primary_map = {
        "Revenue": "revenue", "Orders": "orders", "Sessions": "sessions",
        "Conversion rate": "conversion_rate", "Average order value": "aov",
        "Gross margin": "gross_margin", "Refund rate": "refund_rate",
    }
    metric = primary_map[controls["primary"]]
    label, value_format = METRIC_META[metric]
    trend = cached_overview_trend(path, filters, period, controls["grain"], controls["basis"])
    comparison = cached_overview_trend(path, filters, prior_period, controls["grain"], controls["basis"]) if prior_period else None
    trend_chips = (label, f"Current: {period.label}")
    if prior_period:
        trend_chips += (f"{compare}: {prior_period.label}",)
    _section("Performance trend", chips=trend_chips)
    st.plotly_chart(
        trend_chart(
            trend,
            "period",
            metric,
            label,
            value_format=value_format,
            comparison=comparison,
            comparison_label=compare,
            display_title=False,
        ),
        width="stretch",
        key="overview_trend",
    )

    left, right = st.columns(2)
    with left:
        _section("Revenue drivers", "Revenue = sessions × conversion rate × average order value")
        driver_frame = pd.DataFrame(
            {
                "driver": ["Sessions", "Conversion rate", "Average order value"],
                "current": [current["sessions"], current["conversion_rate"], current["aov"]],
                "index": [
                    current["sessions"] / prior["sessions"] if prior and prior["sessions"] else 1,
                    current["conversion_rate"] / prior["conversion_rate"] if prior and prior["conversion_rate"] else 1,
                    current["aov"] / prior["aov"] if prior and prior["aov"] else 1,
                ],
            }
        )
        st.plotly_chart(ranked_bar(driver_frame, "driver", "index", "Current vs comparison index", value_format="decimal", display_title=False), width="stretch", key="overview_drivers")
    with right:
        _section("Channel contribution", "Gross revenue by traffic-source category")
        drivers = overview_drivers(path, filters, period, dimension="Traffic source")
        st.plotly_chart(
            ranked_bar(
                drivers,
                "segment",
                "revenue",
                "Revenue by source",
                value_format="currency",
                display_title=False,
            ),
            width="stretch",
            key="overview_channels",
        )

    _section("Driver detail", "All values are aggregated at session/order grain before display.")
    _render_detail_table(drivers)


def _acquisition_totals(frame: pd.DataFrame) -> dict[str, float]:
    sessions = float(frame["sessions"].sum()) if not frame.empty else 0
    orders = float(frame["orders"].sum()) if not frame.empty else 0
    revenue = float(frame["revenue"].sum()) if not frame.empty else 0
    margin = float(frame["gross_margin"].sum()) if not frame.empty else 0
    return {
        "sessions": sessions,
        "orders": orders,
        "conversion_rate": orders / sessions if sessions else 0,
        "revenue_per_session": revenue / sessions if sessions else 0,
        "margin_per_session": margin / sessions if sessions else 0,
    }


def render_acquisition(path: str, metadata: DatabaseMetadata, period: DatePeriod, compare: str, filters: FilterSpec, controls: dict) -> None:
    scoped = replace(filters, ad_contents=controls["ad_contents"], referrer_types=controls["referrers"])
    _page_header("Acquisition", period, compare, scoped, metadata)
    prior_period = comparison_period(period, compare)
    sources = cached_acquisition(path, scoped, period, "Traffic source", controls["landings"])
    prior_sources = cached_acquisition(path, scoped, prior_period, "Traffic source", controls["landings"]) if prior_period else None
    if sources.empty or not float(sources["sessions"].sum()):
        _empty_state("acquisition")
        return
    render_metrics(
        _acquisition_totals(sources),
        _acquisition_totals(prior_sources) if prior_sources is not None else None,
        ("sessions", "orders", "conversion_rate", "revenue_per_session"),
        compare,
        period,
        prior_period,
        "acquisition",
    )

    metric_map = {
        "Sessions": ("sessions", "integer"), "Orders": ("orders", "integer"),
        "Conversion rate": ("conversion_rate", "percent"),
        "Revenue per session": ("revenue_per_session", "currency"),
        "Gross margin per session": ("margin_per_session", "currency"),
    }
    metric, value_format = metric_map[controls["metric"]]
    left, right = st.columns(2)
    with left:
        _section(
            "Traffic-source quality",
            chips=(controls["metric"], "Sorted high to low"),
        )
        st.plotly_chart(
            ranked_bar(
                sources,
                "segment",
                metric,
                controls["metric"],
                value_format=value_format,
                display_title=False,
            ),
            width="stretch",
            key="acq_sources",
        )
    with right:
        _section(
            "Campaign quality",
            chips=(controls["metric"], "Sorted high to low"),
        )
        campaigns = cached_acquisition(path, scoped, period, "Campaign", controls["landings"])
        campaigns = campaigns.copy()
        campaigns["segment"] = campaigns["segment"].map(format_filter_option)
        st.plotly_chart(ranked_bar(campaigns, "segment", metric, controls["metric"], value_format=value_format, display_title=False), width="stretch", key="acq_campaigns")
    left, right = st.columns(2)
    with left:
        _section(
            "Device comparison",
            chips=(controls["metric"], "Sorted high to low"),
        )
        devices = cached_acquisition(path, scoped, period, "Device", controls["landings"])
        devices = devices.copy()
        devices["segment"] = devices["segment"].map(format_filter_option)
        st.plotly_chart(ranked_bar(devices, "segment", metric, controls["metric"], value_format=value_format, display_title=False), width="stretch", key="acq_devices")
    with right:
        _section(
            "Landing-page quality",
            chips=(controls["metric"], "Sorted high to low"),
        )
        landings = cached_acquisition(path, scoped, period, "Landing page", controls["landings"])
        landings = landings.copy()
        landings["segment"] = landings["segment"].map(format_filter_option)
        st.plotly_chart(ranked_bar(landings.head(10), "segment", metric, controls["metric"], value_format=value_format, display_title=False), width="stretch", key="acq_landings")
    _section("Acquisition detail", "Revenue per session is not ROAS because the dataset has no spend.")
    _render_detail_table(sources)


def render_funnel(path: str, metadata: DatabaseMetadata, period: DatePeriod, compare: str, filters: FilterSpec, controls: dict) -> None:
    _page_header("Website Funnel", period, compare, filters, metadata)
    current = cached_funnel(path, filters, period, controls["landings"], controls["products"], controls["version"])
    prior_period = comparison_period(period, compare)
    prior = cached_funnel(path, filters, prior_period, controls["landings"], controls["products"], controls["version"]) if prior_period else None
    if current.empty or not float(current.iloc[0]["sessions"]):
        _empty_state("funnel")
        return
    current_final = float(current.iloc[-1]["total_conversion"]) if not current.empty else 0
    prior_final = float(prior.iloc[-1]["total_conversion"]) if prior is not None and not prior.empty else None
    kpis = {
        "sessions": float(current.iloc[0]["sessions"]) if not current.empty else 0,
        "conversion_rate": current_final,
        "orders": float(current.iloc[-1]["sessions"]) if not current.empty else 0,
    }
    prior_kpis = None if prior_final is None else {
        "sessions": float(prior.iloc[0]["sessions"]), "conversion_rate": prior_final, "orders": float(prior.iloc[-1]["sessions"])
    }
    render_metrics(
        kpis,
        prior_kpis,
        ("sessions", "orders", "conversion_rate"),
        compare,
        period,
        prior_period,
        "funnel",
    )
    left, right = st.columns([1.35, 1])
    with left:
        _section("Ordered funnel", "Sessions reaching each stage")
        st.plotly_chart(funnel_chart(current), width="stretch", key="funnel_main")
    with right:
        _section("Stage drop-off", "Sessions lost before the next stage")
        drop = current.loc[current["stage"] != "Landing"] if not current.empty else current
        st.plotly_chart(ranked_bar(drop, "stage", "drop_off", "Sessions lost", value_format="integer", color=NEGATIVE, display_title=False), width="stretch", key="funnel_dropoff")
    _section(f"Final conversion by {controls['compare_by'].lower()}", "Order confirmation is the observed final event.")
    breakdown = cached_funnel_breakdown(
        path, filters, period, controls["compare_by"], controls["landings"], controls["products"], controls["version"]
    )
    if controls["compare_by"] == "Landing page":
        breakdown = breakdown.copy()
        breakdown["segment"] = breakdown["segment"].map(format_filter_option)
    st.plotly_chart(ranked_bar(breakdown, "segment", "conversion_rate", "Final conversion", value_format="percent", display_title=False), width="stretch", key="funnel_breakdown")
    detail = current.copy()
    if prior is not None and not prior.empty:
        detail = detail.merge(prior[["stage", "total_conversion"]], on="stage", how="left", suffixes=("", "_comparison"))
    _render_detail_table(detail)


def _product_totals(frame: pd.DataFrame) -> dict[str, float]:
    units = float(frame["units"].sum()) if not frame.empty else 0
    refunded = float(frame["units_refunded"].sum()) if not frame.empty else 0
    return {
        "revenue": float(frame["revenue"].sum()) if not frame.empty else 0,
        "units": units,
        "gross_margin": float(frame["gross_margin"].sum()) if not frame.empty else 0,
        "refund_rate": refunded / units if units else 0,
        "refunded_amount": float(frame["refunded_amount"].sum()) if not frame.empty else 0,
    }


def render_products(path: str, metadata: DatabaseMetadata, period: DatePeriod, compare: str, filters: FilterSpec, controls: dict) -> None:
    _page_header("Products & Refunds", period, compare, filters, metadata)
    current = cached_products(path, filters, period, controls["products"], controls["roles"], controls["sizes"], controls["basis"])
    prior_period = comparison_period(period, compare)
    prior = cached_products(path, filters, prior_period, controls["products"], controls["roles"], controls["sizes"], controls["basis"]) if prior_period else None
    if current.empty or not float(current["units"].sum()):
        _empty_state("product")
        return
    render_metrics(
        _product_totals(current),
        _product_totals(prior) if prior is not None else None,
        ("revenue", "units", "gross_margin", "refund_rate"),
        compare,
        period,
        prior_period,
        "products",
        {"date_basis": controls["basis"]},
    )
    if controls["basis"] == "Refund date":
        st.info("Refund events use refund timestamps; sales and the rate denominator use purchases in the same displayed calendar period.")

    metric_map = {
        "Revenue": ("revenue", "currency"), "Units sold": ("units", "integer"),
        "Gross margin": ("gross_margin", "currency"), "Refund rate": ("refund_rate", "percent"),
        "Refunded amount": ("refunded_amount", "currency"), "Attachment rate": ("attachment_rate", "percent"),
    }
    metric, value_format = metric_map[controls["metric"]]
    performance_column, refunds_column, basket_column = st.columns(3)
    with performance_column:
        _section(
            "Product performance",
            chips=(controls["metric"], "Sorted high to low"),
        )
        st.plotly_chart(
            ranked_bar(
                current,
                "product",
                metric,
                controls["metric"],
                value_format=value_format,
                display_title=False,
            ),
            width="stretch",
            key="product_performance",
        )
    with refunds_column:
        _section(
            "Refund exposure",
            chips=("Refund rate", "Sorted high to low"),
        )
        st.plotly_chart(ranked_bar(current, "product", "refund_rate", "Refund rate", value_format="percent", color=NEGATIVE, display_title=False), width="stretch", key="product_refunds")
    with basket_column:
        _section("Basket mix", "Orders by basket size")
        basket = cached_basket(path, filters, period, controls["products"], controls["roles"], controls["sizes"])
        st.plotly_chart(ranked_bar(basket, "order_size", "orders", "Orders by basket size", value_format="integer", display_title=False), width="stretch", key="product_basket")
    trend_scope = (
        controls["product_scope"],
        controls["role_scope"],
        controls["size_scope"],
    )
    trend_context = "<br>".join(trend_scope)
    _section(
        f"Monthly {controls['metric']}",
        chips=("Current period", *trend_scope, f"{controls['basis']} basis"),
    )
    trend = cached_product_trend(path, filters, period, controls["products"], controls["roles"], controls["sizes"], controls["basis"])
    trend_label = f"Total {controls['metric']}" if len(controls["products"]) > 1 else controls["metric"]
    if trend.empty:
        st.plotly_chart(trend_chart(trend, "period", metric, trend_label, value_format=value_format, hover_context=trend_context, display_title=False), width="stretch", key="product_trend")
    else:
        aggregate = aggregate_product_trend(trend, metric)
        st.plotly_chart(trend_chart(aggregate, "period", metric, trend_label, value_format=value_format, hover_context=trend_context, display_title=False), width="stretch", key="product_trend")
    _section("Product detail", "Attachment rate is the share of selected product units sold as add-ons.")
    _render_detail_table(current)


def render_top_navigation() -> str:
    return st.segmented_control(
        "Page",
        PAGES,
        default="Executive Overview",
        key="top_navigation",
        label_visibility="collapsed",
        width="stretch",
    ) or "Executive Overview"


def render_app(path: str | Path, metadata: DatabaseMetadata) -> None:
    inject_css()
    path_string = str(path)
    with st.container(border=False, key="top_nav_shell"):
        brand, nav = st.columns([0.18, 0.82], gap="large", vertical_alignment="center")
        with brand:
            st.markdown(
                "<div class='brand'><span class='brand-name'>Maven Revenue Intelligence</span></div>",
                unsafe_allow_html=True,
            )
        with nav:
            page = render_top_navigation()

    if page == "Data Guide":
        with st.container(key="data_guide_workspace"):
            render_data_guide(path_string, metadata)
        return

    with st.container(key="app_workspace"):
        filter_column, content_column = st.columns([0.18, 0.82], gap="medium")
        with filter_column:
            period, compare, filters = _global_filters(path_string, metadata)
            if page == "Executive Overview":
                controls = _render_overview_filters()
            elif page == "Acquisition":
                options = cached_acquisition_filter_options(path_string, period, filters)
                controls = _render_acquisition_filters(options)
            elif page == "Website Funnel":
                options = cached_funnel_filter_options(path_string, period, filters)
                controls = _render_funnel_filters(options)
            else:
                options = cached_product_filter_options(path_string, period, filters)
                controls = _render_product_filters(options)

        with content_column:
            with st.spinner("Calculating from the local database…"):
                if page == "Executive Overview":
                    render_overview(path_string, metadata, period, compare, filters, controls)
                elif page == "Acquisition":
                    render_acquisition(path_string, metadata, period, compare, filters, controls)
                elif page == "Website Funnel":
                    render_funnel(path_string, metadata, period, compare, filters, controls)
                else:
                    render_products(path_string, metadata, period, compare, filters, controls)


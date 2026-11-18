from __future__ import annotations

from calendar import monthrange
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
    comparison_bar,
    contribution_bar,
    funnel_chart,
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
    revenue_driver_contributions,
    segment_contributions,
)
from dashboard.models import DatePeriod, FilterSpec
from dashboard.options import (
    acquisition_filter_options,
    funnel_filter_options,
    product_filter_options,
    session_dimension_values,
)
from dashboard.theme import (
    BACKGROUND,
    BORDER,
    GOLD,
    INK,
    MUTED,
    NAVY,
    REPORT_BACKGROUND,
    REPORT_BORDER,
    WHITE,
)


PAGES = ("Executive Overview", "Acquisition", "Website Funnel", "Products & Refunds", "Data Guide")

PAGE_NAV_LABELS = {
    "Executive Overview": "Overview",
    "Acquisition": "Acquisition",
    "Website Funnel": "Funnel",
    "Products & Refunds": "Products",
    "Data Guide": "Data Guide",
}

PAGE_COPY = {
    "Executive Overview": (
        "Executive Overview",
        "A concise read on revenue health, demand, order yield, margin, and refunds.",
    ),
    "Acquisition": (
        "Acquisition",
        "Compare traffic volume and on-site yield by source, campaign, device, and landing page; spend is unavailable.",
    ),
    "Website Funnel": (
        "Website Funnel",
        "See how session cohorts move from their landing page through order confirmation.",
    ),
    "Products & Refunds": (
        "Products & Refunds",
        "Track product economics, basket composition, add-on mix, and refund exposure.",
    ),
}

METRIC_META = {
    "revenue": ("Revenue", "currency"),
    "gross_revenue": ("Gross Revenue", "currency"),
    "net_revenue": ("Net Revenue", "currency"),
    "orders": ("Orders", "integer"),
    "sessions": ("Sessions", "integer"),
    "conversion_rate": ("Conversion Rate", "percent"),
    "aov": ("Average Order Value", "currency"),
    "gross_margin": ("Gross Margin", "currency"),
    "margin_after_recorded_refunds": ("Margin After Recorded Refunds", "currency"),
    "refund_rate": ("Refund Event Ratio", "percent"),
    "revenue_per_session": ("Revenue per Session", "currency"),
    "margin_per_session": ("Margin per Session", "currency"),
    "units": ("Units Sold", "integer"),
    "refunded_amount": ("Refunded Amount", "currency"),
    "addon_unit_share": ("Add-On Unit Share", "percent"),
}

CARD_FORMULAS = {
    "overview": {
        "gross_revenue": "Gross revenue = sum of order revenue recorded in the selected period",
        "orders": "Orders = count of orders placed in the selected period",
        "sessions": "Sessions = count of website sessions started in the selected period",
        "conversion_rate": "Order rate = order events ÷ session events × 100%",
        "aov": "Average order value = gross order revenue ÷ orders",
        "gross_margin": "Gross margin = gross order revenue − order COGS",
        "margin_after_recorded_refunds": "Margin after recorded refunds = gross margin − refund amount recorded in the selected period",
        "refund_rate": "Refund event ratio = refund events recorded in the selected period ÷ items sold in the selected period × 100%",
        "net_revenue": "Net revenue = gross order revenue − refund amount",
    },
    "acquisition": {
        "sessions": "Sessions = count of sessions started in the selected period",
        "orders": "Orders = count of orders recorded in the selected period, attributed to their original sessions",
        "conversion_rate": "Order rate = event-period order events ÷ event-period session events × 100%",
        "revenue_per_session": "Revenue per session = event-period gross revenue ÷ event-period sessions",
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
        "addon_unit_share": "Add-on unit share = selected add-on units ÷ selected units × 100%",
    },
}

def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root { --navy:__NAVY__; --gold:__GOLD__; --ink:__INK__; --muted:__MUTED__; --line:__BORDER__; --soft:__BACKGROUND__; --white:__WHITE__; }
        :root { --topbar-height:4rem; }
        [data-testid="stHeader"], [data-testid="stSidebar"] { display:none; }
        .stApp { background: var(--soft); color: var(--ink); }
        .block-container { max-width:1600px; padding:var(--topbar-height) 1.25rem 2.5rem; }
        .brand { display:flex; align-items:center; min-height:var(--topbar-height); min-width:0; }
        .brand-name { color:var(--ink); font-size:1.25rem; font-weight:780; line-height:1.15; letter-spacing:-.035em; white-space:nowrap; }
        .page-title { font-size:1.75rem !important; line-height:1.12 !important; letter-spacing:-.035em; color:var(--ink); font-weight:780; margin:0 !important; padding:0 !important; }
        .page-subtitle { color:var(--muted); font-size:.9rem; margin:.3rem 0 .58rem; max-width:54rem; }
        .context-summary {
          margin:.25rem 0 .9rem; padding:.55rem .7rem; border-left:3px solid var(--gold);
          border-radius:0 9px 9px 0; background:#F2EFFF; color:#475467;
          font-size:.7rem; line-height:1.35;
        }
        [data-testid="stElementContainer"]:has(.context-summary) { margin-bottom:.5rem !important; }
        .context-periods { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:.35rem 1rem; }
        .context-field { display:grid; grid-template-columns:5.3rem minmax(0, 1fr); gap:.45rem; min-width:0; }
        .context-field + .context-field-detail { margin-top:.22rem; }
        .context-field-detail { grid-template-columns:5.3rem minmax(0, 1fr); }
        .context-label { color:#667085; font-size:.62rem; font-weight:760; letter-spacing:.045em; text-transform:uppercase; }
        .context-value { color:#344054; font-weight:560; min-width:0; overflow-wrap:anywhere; }
        .section-title { font-size:.96rem; font-weight:740; color:var(--ink); margin:.82rem 0 .06rem; letter-spacing:-.01em; }
        .section-note { color:var(--muted); font-size:.76rem; margin:.08rem 0 .28rem; }
        .section-chip-row { display:flex; flex-wrap:wrap; gap:.3rem; margin:.14rem 0 0; padding-bottom:.62rem; }
        .section-chip { display:inline-flex; align-items:center; padding:.24rem .5rem; border:1px solid #DCD5F5; border-radius:7px; background:#F2EFFF; color:#51467E; font-size:.7rem; font-weight:600; line-height:1.2; }
        .empty-state { background:var(--white); border:1px solid var(--line); border-radius:14px; padding:2rem 1.5rem; text-align:center; box-shadow:0 6px 20px rgba(24,39,75,.045); margin-top:.6rem; }
        .empty-state-title { color:var(--ink); font-size:1.05rem; font-weight:760; }
        .empty-state-copy { color:var(--muted); font-size:.84rem; margin-top:.3rem; }
        [data-testid="stMetric"] { background:var(--white); border:1px solid var(--line); border-radius:12px; padding:.72rem .82rem; box-shadow:0 4px 14px rgba(24,39,75,.045); }
        [data-testid="stMetricLabel"] { color:var(--muted); }
        [data-testid="stMetricValue"] { color:var(--ink); font-weight:730; letter-spacing:-.035em; }
        [data-testid="stTooltipContent"] {
          width:min(31rem, calc(100vw - 1rem)) !important; box-sizing:border-box;
          max-height:none !important; overflow:visible !important;
          padding:.62rem .7rem .72rem !important; background:__REPORT_BACKGROUND__ !important;
          border:1px solid __REPORT_BORDER__; border-radius:12px !important;
          box-shadow:0 14px 34px rgba(24,39,75,.16);
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] h5 {
          margin:.46rem 0 .22rem; color:#667085; font-size:.64rem; line-height:1.2;
          font-weight:760; letter-spacing:.075em; text-transform:uppercase;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] h5:first-child { margin-top:0; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] { padding-bottom:.55rem; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] p { margin:0; line-height:1.32; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] blockquote {
          margin:0; padding:.38rem .5rem; background:#FFFFFF; border-left:3px solid var(--gold);
          border-radius:0 7px 7px 0; color:var(--ink);
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] blockquote p {
          color:var(--ink) !important; font-size:.76rem;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] table {
          width:100%; margin:0; border:1px solid #DDE3EC; border-radius:8px;
          border-spacing:0; overflow:hidden; background:#FFFFFF; font-size:.69rem;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] th {
          padding:.27rem .35rem; background:#EEF2F7; color:#667085; font-size:.59rem;
          font-weight:750; letter-spacing:.04em; text-transform:uppercase; text-align:left;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] td {
          padding:.3rem .35rem; border-top:1px solid #E6EAF0; vertical-align:top; line-height:1.24;
        }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] th:last-child,
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] td:last-child { text-align:right; white-space:nowrap; }
        [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] em {
          display:block; margin-top:.28rem; color:#667085; font-size:.66rem; line-height:1.28;
        }
        [data-testid="stPlotlyChart"] { background:var(--white); border:1px solid var(--line); border-radius:14px; padding:0; overflow:hidden !important; box-sizing:border-box; box-shadow:0 6px 20px rgba(24,39,75,.045); }
        [data-testid="stElementContainer"]:has([data-testid="stPlotlyChart"]) { overflow:hidden !important; }
        [data-testid="stPlotlyChart"] .hoverlayer .hovertext path {
          stroke:__REPORT_BORDER__ !important; stroke-width:1px;
          filter:drop-shadow(0 4px 9px rgba(24,39,75,.14));
        }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line); background:var(--white); border-radius:14px; box-shadow:0 5px 18px rgba(24,39,75,.04); }
        .stMain div[data-testid="stVerticalBlock"] > div:has(> .st-key-top_nav_shell) {
          position:fixed; top:0; left:0; z-index:1050; width:100vw;
          height:var(--topbar-height); min-height:var(--topbar-height);
        }
        .st-key-top_nav_shell {
          position:relative !important; width:100vw !important;
          height:var(--topbar-height); padding:0 1.75rem !important; margin:0 !important;
          box-sizing:border-box;
          background:#E9EDF5 !important; border:0 !important; border-bottom:1px solid #D8DEE8 !important;
          border-radius:0 !important; box-shadow:none !important;
        }
        .st-key-top_nav_shell > div[data-testid="stLayoutWrapper"] {
          width:100%; max-width:100rem; height:100%; margin:0 auto 0 0;
          align-items:center;
        }
        .st-key-top_nav_shell > div[data-testid="stLayoutWrapper"] > div[data-testid="stHorizontalBlock"] {
          height:100%; align-items:center !important;
        }
        .st-key-app_workspace {
          margin:-.56rem -1.25rem -2.5rem !important;
        }
        .st-key-app_workspace > div[data-testid="stVerticalBlock"] { gap:0 !important; }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child {
          position:sticky; top:var(--topbar-height); align-self:flex-start;
          height:calc(100vh - var(--topbar-height)); min-height:0; overflow:hidden;
          background:#F3F3FA; border-right:0; padding:1.25rem 1rem 2rem 1.75rem;
          box-sizing:border-box;
        }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child > div[data-testid="stVerticalBlock"] {
          height:100%; min-height:0; padding-right:.75rem; box-sizing:border-box;
          overflow-y:auto; overflow-x:hidden; scrollbar-width:thin; scrollbar-gutter:stable;
          overscroll-behavior:contain;
        }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:first-child .section-title {
          margin-top:0;
        }
        .filter-bottom-spacer { height:3rem; min-height:3rem; }
        .st-key-app_workspace div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child:has(.page-title) {
          padding:1.25rem 1.25rem 2.5rem 1rem;
        }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:0 4px 14px rgba(24,39,75,.035); }
        .st-key-data_guide_workspace {
          width:100%; max-width:1440px; margin:0 auto;
          padding:1.05rem clamp(1.75rem, 4vw, 4rem) 2.5rem;
          box-sizing:border-box;
        }
        .st-key-data_guide_workspace > div[data-testid="stVerticalBlock"] { gap:.72rem; }
        .st-key-data_guide_workspace .page-title,
        .st-key-data_guide_workspace h3,
        .st-key-data_guide_workspace h4 { color:var(--ink); }
        .st-key-data_guide_workspace div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
        .st-key-data_guide_workspace div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        .st-key-data_guide_workspace div[data-testid="stButtonGroup"] [role="radio"][aria-checked="true"] {
          color:var(--ink) !important;
        }
        .st-key-data_guide_workspace [data-testid="stMetric"] {
          padding:.65rem .75rem; background:#F2EFFF; border-color:#DDD6FE; box-shadow:none;
        }
        .st-key-data_guide_workspace div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(even) [data-testid="stMetric"] {
          background:#F0F7FF; border-color:#D6E7F7;
        }
        .st-key-data_guide_workspace [data-testid="stMetricValue"] {
          font-size:1.22rem; font-weight:660; letter-spacing:-.018em;
        }
        .st-key-data_guide_workspace [data-testid="stExpander"] {
          border-color:#DDD6FE; background:rgba(255,255,255,.68);
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
        .erd-title { fill:var(--ink); font-size:14px; font-weight:740; }
        .erd-key { fill:#475467; font-size:10px; font-weight:780; }
        .erd-field { fill:#344054; font-size:13px; font-weight:520; }
        .erd-links path { fill:none; stroke:#98A2B3; stroke-width:2; }
        .erd-links text { fill:#475467; font-size:11px; font-weight:760; }
        .erd-legend {
          display:flex; flex-wrap:wrap; gap:.45rem 1rem; padding:.35rem .2rem 0;
          color:#667085; font-size:.7rem; line-height:1.35;
        }
        .erd-legend b { color:var(--ink); font-weight:780; }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] [data-baseweb="button-group"],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radiogroup"] {
          width:100% !important; justify-content:flex-start !important; align-items:center !important;
          background:transparent !important; border:0 !important; border-radius:0 !important;
          padding:0 !important; gap:clamp(.35rem, 1.35vw, 1.35rem); box-shadow:none !important;
        }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button,
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"] {
          flex:0 0 auto !important; width:auto !important; min-height:2.45rem; border:1px solid transparent !important;
          border-radius:10px !important; background:transparent !important; color:#596273 !important;
          font-size:.98rem; font-weight:590; padding:.55rem .85rem; box-shadow:none !important;
          transition:background-color .16s ease, color .16s ease, box-shadow .16s ease !important;
        }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button:hover,
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"]:hover { background:rgba(255,255,255,.6) !important; color:var(--ink) !important; }
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
        .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"][data-selected],
        .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"][aria-checked="true"] {
          color:#FFFFFF !important; background:var(--navy) !important; font-weight:700;
          border-color:var(--navy) !important; box-shadow:0 2px 5px rgba(41,35,92,.22) !important;
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
        @media (max-width: 1100px) {
          .brand-name { font-size:.88rem; }
          .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button,
          .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"] {
            font-size:.77rem; padding:.42rem .55rem;
          }
        }
        @media (max-width: 768px) {
          .block-container { padding:var(--topbar-height) .8rem 1.5rem; }
          .page-title { font-size:1.5rem !important; }
          :root { --topbar-height:3.15rem; }
          .st-key-app_workspace { margin:-.56rem -.8rem -1.5rem !important; }
          .st-key-top_nav_shell {
            width:100vw !important; min-width:100vw !important; max-width:none !important;
            padding:0 .75rem !important; margin:0 !important;
          }
          .st-key-top_nav_shell div[data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:.3rem !important; }
          .st-key-top_nav_shell div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child {
            flex:0 0 30% !important; width:30% !important;
          }
          .st-key-top_nav_shell div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child {
            flex:1 1 70% !important; width:70% !important;
          }
          .brand { transform:none; min-height:var(--topbar-height); }
          .brand-name { font-size:.86rem; letter-spacing:-.025em; }
          .st-key-top_nav_shell div[data-testid="stSegmentedControl"] [data-baseweb="button-group"],
          .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radiogroup"] {
            width:100% !important; flex-wrap:nowrap !important; overflow:visible; justify-content:space-between !important;
          }
          .st-key-top_nav_shell div[data-testid="stSegmentedControl"] button,
          .st-key-top_nav_shell div[data-testid="stButtonGroup"] [role="radio"] {
            flex:0 0 auto !important; min-height:2.2rem; padding:.38rem .16rem; font-size:.62rem; white-space:nowrap;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) > div[data-testid="stColumn"]:first-child {
            position:sticky; top:var(--topbar-height); align-self:flex-start;
            flex:0 0 11.9rem !important; width:11.9rem !important;
            height:calc(100vh - var(--topbar-height)); overflow:hidden;
            padding-left:.75rem; padding-right:.75rem;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:has(.page-title) {
            flex-wrap:nowrap !important; align-items:flex-start !important;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child:has(.page-title) {
            flex:1 1 0 !important; width:auto !important; min-width:0 !important;
            padding:1.25rem .8rem 1.5rem .7rem;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:not(:has(.page-title)):has([data-testid="stMetric"]) {
            flex-wrap:wrap !important;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:not(:has(.page-title)):has([data-testid="stMetric"]) > div[data-testid="stColumn"] {
            flex:1 1 calc(50% - .55rem) !important; width:calc(50% - .55rem) !important;
            min-width:calc(50% - .55rem) !important; max-width:calc(50% - .55rem) !important;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:not(:has(.page-title)):has([data-testid="stPlotlyChart"]) {
            flex-wrap:wrap !important;
          }
          .st-key-app_workspace div[data-testid="stHorizontalBlock"]:not(:has(.page-title)):has([data-testid="stPlotlyChart"]) > div[data-testid="stColumn"] {
            flex:1 1 100% !important; width:100% !important;
          }
          [data-testid="stMetric"] { padding:.62rem .68rem; }
          [data-testid="stPopoverBody"] { max-width:calc(100vw - 2rem); max-height:55vh; }
          .st-key-data_guide_workspace { padding:.8rem 1rem 1.5rem; }
          .context-periods { grid-template-columns:1fr; gap:.2rem; }
          .context-field, .context-field-detail { grid-template-columns:4.7rem minmax(0, 1fr); }
        }
        </style>
        """
        .replace("__NAVY__", NAVY)
        .replace("__GOLD__", GOLD)
        .replace("__INK__", INK)
        .replace("__MUTED__", MUTED)
        .replace("__BORDER__", BORDER)
        .replace("__BACKGROUND__", BACKGROUND)
        .replace("__REPORT_BACKGROUND__", REPORT_BACKGROUND)
        .replace("__REPORT_BORDER__", REPORT_BORDER)
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
        "Product-detail page": "product-detail pages",
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


def _active_selection_scope(
    label: str,
    options: tuple[str, ...],
    selected: tuple[str, ...],
    *,
    all_label: str,
) -> str | None:
    if set(selected) == set(options):
        return None
    return f"{label}: {selection_summary(label, options, selected, all_label=all_label)}"


def _effective_filter_values(
    options: tuple[str, ...], selected: tuple[str, ...]
) -> tuple[str, ...] | None:
    """Use None for a true all-values filter while preserving an empty result set."""
    if not options:
        return ()
    if set(selected) == set(options):
        return None
    return selected


def _filter_accessible_description(label: str, summary: str) -> str:
    return f"{label} filter. Current selection: {summary}."


def filter_trigger_label(label: str, summary: str) -> str:
    return f"{label}: {summary}"


def _filter_selection_default(
    options: tuple[str, ...],
    previous: tuple[str, ...],
    previous_options: tuple[str, ...],
    stored_all_mode: bool | None,
) -> tuple[tuple[str, ...], bool, tuple[str, ...]]:
    """Resolve a durable All mode separately from an explicit value subset."""

    selected = tuple(option for option in previous if option in options)
    removed = tuple(option for option in previous if option not in options)
    if stored_all_mode is None:
        all_mode = (
            not previous
            or set(previous) == set(options)
            or bool(previous_options) and set(previous) == set(previous_options)
        )
    else:
        all_mode = stored_all_mode
    return (() if all_mode else selected), all_mode, removed


def checkbox_group(
    label: str,
    options: tuple[str, ...],
    key: str,
    *,
    all_label: str,
) -> tuple[str, ...]:
    generation = int(st.session_state.get("filter_reset_generation", 0))
    state_key = f"{key}__selected"
    all_mode_key = f"{key}__all"
    options_key = f"{key}__options"
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
        st.session_state[state_key] = ()
        st.session_state[all_mode_key] = True
        st.session_state[options_key] = ()
        return ()
    previous = tuple(st.session_state.get(state_key, ()))
    previous_options = tuple(st.session_state.get(options_key, ()))
    stored_all_mode = st.session_state.get(all_mode_key)
    selected_default, _, removed = _filter_selection_default(
        options,
        previous,
        previous_options,
        stored_all_mode,
    )
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
    all_mode = not explicit or set(explicit) == set(options)
    st.session_state[state_key] = () if all_mode else explicit
    st.session_state[all_mode_key] = all_mode
    st.session_state[options_key] = options
    return options if all_mode else explicit


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
    first_timestamp = datetime.fromisoformat(metadata.session_min)
    core_maxima = tuple(
        datetime.fromisoformat(value)
        for value in (
            metadata.session_max,
            metadata.pageview_max,
            metadata.order_max,
            metadata.item_max,
        )
        if value is not None
    )
    final_timestamp = min(core_maxima)
    current = datetime(first_timestamp.year, first_timestamp.month, 1)
    final = datetime(final_timestamp.year, final_timestamp.month, 1)
    values = []
    while current <= final:
        values.append(current.strftime("%Y-%m"))
        index = current.year * 12 + current.month
        current = datetime(index // 12, index % 12 + 1, 1)
    if values and first_timestamp.day > 1:
        values = values[1:]
    if values and final_timestamp.day < monthrange(final_timestamp.year, final_timestamp.month)[1]:
        values = values[:-1]
    return tuple(values)


def _excluded_partial_month(metadata: DatabaseMetadata) -> str | None:
    if not metadata.session_min or not metadata.session_max:
        return None
    first = datetime.fromisoformat(metadata.session_min)
    core_maxima = tuple(
        datetime.fromisoformat(value)
        for value in (
            metadata.session_max,
            metadata.pageview_max,
            metadata.order_max,
            metadata.item_max,
        )
        if value is not None
    )
    final = min(core_maxima)
    final_day = monthrange(final.year, final.month)[1]
    excluded: list[str] = []
    if first.day > 1:
        excluded.append(
            f"{first.strftime('%b %Y')} (source starts {first.strftime('%b %d')})"
        )
    if final.day < final_day:
        excluded.append(
            f"{final.strftime('%b %Y')} (core facts end {final.strftime('%b %d')})"
        )
    return "; ".join(excluded) or None


def _reporting_window_months(
    months: tuple[str, ...],
    window: str,
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> tuple[str, str]:
    if not months:
        raise ValueError("Reporting windows require at least one month.")
    lengths = {
        "Latest 12 covered months": 12,
        "Latest 6 covered months": 6,
        "Latest 3 covered months": 3,
    }
    if window == "All covered history":
        return months[0], months[-1]
    if window == "Custom":
        if custom_start not in months or custom_end not in months:
            raise ValueError("Custom reporting months must exist in the dataset.")
        return tuple(sorted((custom_start, custom_end)))
    if window not in lengths:
        raise ValueError(f"Unknown reporting window: {window}")
    length = lengths[window]
    return months[max(0, len(months) - length)], months[-1]


def _comparison_option_periods(
    period: DatePeriod, compare: str
) -> tuple[DatePeriod, ...]:
    prior = comparison_period(period, compare)
    if prior is None:
        return (period,)
    return (period, prior)


def _merge_options(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for group in groups for value in group))


def _merge_option_dicts(*groups: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    if not groups:
        return {}
    return {
        key: _merge_options(*(group[key] for group in groups))
        for key in groups[0]
    }


def _available_comparison_modes(
    period: DatePeriod, first_complete_month: str
) -> tuple[str, ...]:
    first_complete = datetime.strptime(first_complete_month, "%Y-%m")
    available = tuple(
        mode
        for mode in ("Previous period", "Previous year")
        if comparison_period(period, mode).start >= first_complete
        and not (mode == "Previous year" and period.month_count > 12)
    )
    return (*available, "None")


def _format_value(value: float | int | None, value_format: str) -> str:
    if value is None or pd.isna(value):
        return "Not available"
    if value_format == "currency":
        sign = "-" if value < 0 else ""
        magnitude = abs(value)
        if magnitude >= 1_000_000:
            return f"{sign}${magnitude / 1_000_000:.2f}M"
        if magnitude >= 1_000:
            return f"{sign}${magnitude / 1_000:.2f}K"
        return f"{sign}${magnitude:,.2f}"
    if value_format == "percent":
        return f"{value:.2%}"
    if value_format == "integer":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _format_exact_value(value: float | int | None, value_format: str) -> str:
    if value is None or pd.isna(value):
        return "Not available"
    if value_format == "currency":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):,.2f}"
    if value_format == "percent":
        return f"{value:.2%}"
    if value_format == "integer":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _delta(
    current: float | None,
    previous: float | None,
    value_format: str = "decimal",
) -> str | None:
    if current is None or previous is None or pd.isna(previous) or pd.isna(current):
        return None
    difference = current - previous
    relative = None if previous == 0 else difference / abs(previous)
    if value_format == "percent":
        absolute = f"{difference * 100:+.2f} pp"
    elif value_format == "currency":
        absolute = f"{difference:+,.2f}"
        absolute = f"+${absolute[1:]}" if absolute.startswith("+") else f"-${absolute[1:]}"
    elif value_format == "integer":
        absolute = f"{difference:+,.0f}"
    else:
        absolute = f"{difference:+,.2f}"
    return absolute if relative is None else f"{absolute} ({relative:+.2%})"


def _metric_formula(scope: str, key: str, context: dict[str, str] | None = None) -> str:
    context = context or {}
    if scope == "overview" and key == "revenue":
        if context.get("revenue_basis") == "Net":
            return "Revenue (net basis) = gross order revenue − refund amount"
        return "Revenue (gross basis) = sum of order revenue (orders.price_usd)"
    if scope == "products" and key == "refund_rate":
        if context.get("date_basis") == "Refund date":
            return "Refund event ratio = refund events in the selected period ÷ units purchased in the same calendar period × 100%"
        return "Purchase-cohort refund rate = items from the selected purchase cohort that were later refunded ÷ units in that purchase cohort × 100%"
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
    current: float | None,
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
        f"| Current | {period.label} | **{_format_exact_value(current, value_format)}** |",
    ]
    if prior is not None and prior_period is not None:
        table.append(
            f"| {compare} | {prior_period.label} | **{_format_exact_value(prior, value_format)}** |"
        )

    details = [
        "##### Metric formula",
        f"> {_metric_formula(scope, key, context)}",
        "##### Values by period",
        "\n".join(table),
    ]
    notes = [f"Comparison: {_comparison_rule(compare, period)}"]
    if prior is not None:
        if value_format == "percent":
            notes.append("Delta: percentage-point change first; relative change in parentheses.")
        else:
            notes.append("Delta: absolute change first; relative change in parentheses.")
    if prior == 0:
        notes.append("Relative change is unavailable when the comparison value is zero.")
    details.append(f"*{' '.join(notes)}*")
    return "\n\n".join(details)


def _title_case(text: str) -> str:
    """Use readable title case while keeping short connector words lowercase."""
    titled = text.replace("_", " ").strip().title()
    for word in ("And", "As", "At", "By", "For", "From", "In", "Of", "On", "Or", "Per", "The", "To", "Vs."):
        titled = titled.replace(f" {word} ", f" {word.lower()} ")
    for source, target in (("Utm", "UTM"), ("Cogs", "COGS"), ("Aov", "AOV"), ("Kpi", "KPI"), ("Id", "ID")):
        titled = titled.replace(source, target)
    return titled


def _format_detail_table(
    frame: pd.DataFrame,
    column_formats: dict[str, str] | None = None,
) -> pd.DataFrame:
    display = frame.copy()
    column_formats = column_formats or {}
    percent_columns = {
        "conversion_rate",
        "step_conversion",
        "total_conversion",
        "total_conversion_comparison",
        "refund_rate",
        "addon_unit_share",
        "share_of_total_delta",
    } | {column for column, value in column_formats.items() if value == "percent"}
    integer_columns = {
        "sessions",
        "orders",
        "units",
        "units_refunded",
        "drop_off",
    } | {column for column, value in column_formats.items() if value == "integer"}
    renamed = {}
    for column in display.columns:
        if column in percent_columns:
            display[column] = (display[column] * 100).round(2)
            suffix = "pp" if column == "absolute_delta" else "%"
            renamed[column] = f"{_title_case(column)} ({suffix})"
        elif column in integer_columns:
            display[column] = display[column].round(0).astype("Int64")
            renamed[column] = _title_case(column)
        elif pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].round(2)
            renamed[column] = _title_case(column)
        else:
            renamed[column] = _title_case(column)
    return display.rename(columns=renamed)


def _render_detail_table(
    frame: pd.DataFrame,
    column_formats: dict[str, str] | None = None,
    column_labels: dict[str, str] | None = None,
    column_widths: dict[str, int] | None = None,
) -> None:
    column_formats = column_formats or {}
    column_labels = column_labels or {}
    column_widths = column_widths or {}
    display = _format_detail_table(frame, column_formats)
    display_names = {source: target for source, target in zip(frame.columns, display.columns)}
    display = display.rename(
        columns={
            display_names[source]: label
            for source, label in column_labels.items()
            if source in display_names
        }
    )
    display_names.update(
        {
            source: label
            for source, label in column_labels.items()
            if source in display_names
        }
    )
    column_config = dataframe_column_config(frame, display_names)
    for source, value_format in column_formats.items():
        if source not in frame or source not in display_names:
            continue
        if value_format == "currency":
            column_config[display_names[source]] = st.column_config.NumberColumn(
                alignment="left",
                format="dollar",
                width="small",
            )
    for source, width in column_widths.items():
        if source not in frame or source not in display_names:
            continue
        label = display_names[source]
        if pd.api.types.is_numeric_dtype(frame[source]):
            options: dict[str, object] = {
                "alignment": "left",
                "width": width,
            }
            if column_formats.get(source) == "currency":
                options["format"] = "dollar"
            column_config[label] = st.column_config.NumberColumn(**options)
        else:
            column_config[label] = st.column_config.TextColumn(
                alignment="left",
                width=width,
            )
    st.dataframe(
        display,
        column_config=column_config,
        width="stretch",
        hide_index=True,
    )


def _fact_freshness(label: str, timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    return (
        f"Last observed {label.lower()}: "
        f"{datetime.fromisoformat(timestamp).strftime('%b %d, %Y')}"
    )


def _freshness_scope(
    metadata: DatabaseMetadata, *facts: str
) -> tuple[str, ...]:
    values = {
        "sessions": _fact_freshness("Sessions", metadata.session_max),
        "pageviews": _fact_freshness("Pageviews", metadata.pageview_max),
        "orders": _fact_freshness("Orders", metadata.order_max),
        "items": _fact_freshness("Items", metadata.item_max),
        "refunds": _fact_freshness("Refund events", metadata.refund_max),
    }
    return tuple(values[fact] for fact in facts if values.get(fact) is not None)


def _refund_measure_label(date_basis: str) -> str:
    if date_basis == "Purchase date":
        return "Purchase-Cohort Refund Rate"
    if date_basis == "Refund date":
        return "Refund Event Ratio"
    raise ValueError(f"Unsupported refund basis: {date_basis}")


def _segment_comparison_frame(
    current: pd.DataFrame,
    prior: pd.DataFrame | None,
    metric: str,
    *,
    segment_column: str = "segment",
    denominator: str | None = "sessions",
) -> pd.DataFrame:
    columns = [
        segment_column,
        "current",
        "comparison",
        "absolute_delta",
    ]
    include_denominator = bool(denominator and denominator != metric)
    if include_denominator:
        columns.extend(["current_denominator", "comparison_denominator"])
    if prior is None:
        return pd.DataFrame(columns=columns)
    current_columns = [segment_column, metric]
    prior_columns = [segment_column, metric]
    if include_denominator and denominator in current:
        current_columns.append(denominator)
    if include_denominator and denominator in prior:
        prior_columns.append(denominator)
    current_rename = {metric: "current"}
    prior_rename = {metric: "comparison"}
    if include_denominator:
        current_rename[denominator] = "current_denominator"
        prior_rename[denominator] = "comparison_denominator"
    current_frame = current[current_columns].rename(columns=current_rename)
    prior_frame = prior[prior_columns].rename(columns=prior_rename)
    frame = current_frame.merge(prior_frame, on=segment_column, how="outer")
    additive_metrics = {
        "sessions",
        "orders",
        "units",
        "revenue",
        "gross_revenue",
        "net_revenue",
        "gross_margin",
        "refunded_amount",
        "drop_off",
    }
    if metric in additive_metrics:
        frame[["current", "comparison"]] = frame[
            ["current", "comparison"]
        ].fillna(0)
    frame["absolute_delta"] = frame["current"] - frame["comparison"]
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    return frame[columns]


def _render_comparison_or_current_bar(
    current: pd.DataFrame,
    prior: pd.DataFrame | None,
    *,
    category: str,
    metric: str,
    label: str,
    value_format: str,
    compare: str,
    key: str,
    denominator: str | None = "sessions",
) -> pd.DataFrame:
    if prior is None:
        chart_frame = current.dropna(subset=[metric])
        st.plotly_chart(
            ranked_bar(
                chart_frame,
                category,
                metric,
                label,
                value_format=value_format,
                display_title=False,
            ),
            width="stretch",
            key=key,
        )
        detail_columns = [category, metric]
        include_denominator = bool(
            denominator and denominator != metric and denominator in current
        )
        if include_denominator:
            detail_columns.append(denominator)
        detail = current[detail_columns].rename(
            columns={
                metric: "current",
                **(
                    {denominator: "current_denominator"}
                    if include_denominator
                    else {}
                ),
            }
        )
        detail["comparison"] = pd.NA
        detail["absolute_delta"] = pd.NA
        if include_denominator:
            detail["comparison_denominator"] = pd.NA
        return detail
    comparison = _segment_comparison_frame(
        current, prior, metric, segment_column=category, denominator=denominator
    )
    chart_frame = comparison.copy()
    for column in ("current", "comparison"):
        chart_frame[column] = pd.to_numeric(
            chart_frame[column], errors="coerce"
        ).astype(float)
    st.plotly_chart(
        comparison_bar(
            chart_frame,
            category,
            label=label,
            value_format=value_format,
            comparison_label=compare,
            current_denominator=(
                "current_denominator" if denominator and denominator != metric else None
            ),
            comparison_denominator=(
                "comparison_denominator"
                if denominator and denominator != metric
                else None
            ),
            display_title=False,
        ),
        width="stretch",
        key=key,
    )
    return comparison


def render_metrics(
    current: dict,
    previous: dict | None,
    keys: tuple[str, ...],
    compare: str,
    period: DatePeriod,
    prior_period: DatePeriod | None,
    scope: str,
    context: dict[str, str] | None = None,
    label_overrides: dict[str, str] | None = None,
) -> None:
    label_overrides = label_overrides or {}
    for row_start in range(0, len(keys), 4):
        row_keys = keys[row_start : row_start + 4]
        columns = st.columns(len(row_keys), gap="small")
        for column, key in zip(columns, row_keys):
            default_label, value_format = METRIC_META[key]
            label = label_overrides.get(key, default_label)
            raw_current = current.get(key, 0)
            value = (
                None
                if raw_current is None or pd.isna(raw_current)
                else float(raw_current)
            )
            raw_prior = previous.get(key) if previous else None
            prior = None if raw_prior is None or pd.isna(raw_prior) else float(raw_prior)
            delta = _delta(value, prior, value_format)
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
                delta_color="inverse" if key == "refund_rate" else "normal",
            )


def _context_chips(
    period: DatePeriod,
    prior_period: DatePeriod | None,
    compare: str,
    global_scope: tuple[str, ...],
    page_scope: tuple[str, ...],
    freshness: tuple[str, ...],
) -> None:
    comparison = (
        f"{prior_period.label} ({compare})" if prior_period is not None else "None"
    )
    scope = ", ".join((*global_scope, *page_scope))
    observed = ", ".join(freshness) if freshness else "Not available"
    st.markdown(
        "<div class='context-summary'>"
        "<div class='context-periods'>"
        f"<div class='context-field'><span class='context-label'>Current</span><span class='context-value'>{escape(period.label)}</span></div>"
        f"<div class='context-field'><span class='context-label'>Compare</span><span class='context-value'>{escape(comparison)}</span></div>"
        "</div>"
        f"<div class='context-field context-field-detail'><span class='context-label'>Scope</span><span class='context-value'>{escape(scope)}</span></div>"
        f"<div class='context-field context-field-detail'><span class='context-label'>Freshness</span><span class='context-value'>{escape(observed)}</span></div>"
        "<div class='context-field context-field-detail'><span class='context-label'>Calendar</span><span class='context-value'>Core-fact month-coverage heuristic</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _page_header(
    page: str,
    period: DatePeriod,
    prior_period: DatePeriod | None,
    compare: str,
    global_scope: tuple[str, ...],
    page_scope: tuple[str, ...],
    freshness: tuple[str, ...],
) -> None:
    title, subtitle = PAGE_COPY[page]
    st.markdown(f"<h1 class='page-title'>{title}</h1>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-subtitle'>{subtitle}</div>", unsafe_allow_html=True)
    _context_chips(period, prior_period, compare, global_scope, page_scope, freshness)


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


def _has_metric_evidence(values: dict | None, keys: tuple[str, ...]) -> bool:
    if values is None:
        return False
    return any(
        value is not None and not pd.isna(value) and float(value) != 0
        for key in keys
        if (value := values.get(key)) is not None
    )


def _funnel_has_evidence(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return False
    sessions = frame.iloc[0]["sessions"]
    return sessions is not None and not pd.isna(sessions) and float(sessions) != 0


def _product_has_evidence(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return False
    return any(
        float(frame[column].sum()) != 0
        for column in ("units", "units_refunded", "refunded_amount")
    )


def _optional_float(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _global_filters(
    path: str, metadata: DatabaseMetadata
) -> tuple[DatePeriod, str, FilterSpec, tuple[str, ...]]:
    _section("Global filters", "Shared across every analysis workspace")
    months = _months(metadata)
    if not months:
        if not metadata.session_min or not metadata.session_max:
            st.error("The session table has no dated records.")
        else:
            st.error(
                "No shared reporting month satisfies the core-fact month-coverage heuristic."
            )
        st.stop()
    window = _ui_select(
        "Reporting window",
        (
            "Latest 12 covered months",
            "Latest 6 covered months",
            "Latest 3 covered months",
            "All covered history",
            "Custom",
        ),
        key="global_date_window",
    )
    partial = _excluded_partial_month(metadata)
    if partial:
        st.caption(f"Incomplete source months excluded from reporting: {partial}.")
    if window == "All covered history":
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
    period = DatePeriod.from_months(chosen[0], chosen[1])
    compare_options = _available_comparison_modes(period, months[0])
    compare = _ui_select(
        "Compare with",
        compare_options,
        key="global_compare",
    )
    if compare_options == ("None",):
        st.caption(
            "Comparison is unavailable because it would precede the covered-month heuristic boundary."
        )
    option_periods = _comparison_option_periods(period, compare)
    source_options = _merge_options(
        *(
            cached_session_dimension_values(
                path, option_period, FilterSpec(), "traffic_source"
            )
            for option_period in option_periods
        )
    )
    sources = checkbox_group(
        "Traffic source",
        source_options,
        "global_source",
        all_label="All traffic sources",
    )
    effective_sources = _effective_filter_values(source_options, sources)
    source_filters = FilterSpec(traffic_sources=effective_sources)
    campaign_options = _merge_options(
        *(
            cached_session_dimension_values(
                path, option_period, source_filters, "campaign"
            )
            for option_period in option_periods
        )
    )
    campaigns = checkbox_group(
        "Campaign", campaign_options, "global_campaign", all_label="All campaigns"
    )
    effective_campaigns = _effective_filter_values(campaign_options, campaigns)
    campaign_filters = FilterSpec(
        traffic_sources=effective_sources,
        campaigns=effective_campaigns,
    )
    device_options = _merge_options(
        *(
            cached_session_dimension_values(
                path, option_period, campaign_filters, "device"
            )
            for option_period in option_periods
        )
    )
    devices = checkbox_group(
        "Device", device_options, "global_device", all_label="All devices"
    )
    effective_devices = _effective_filter_values(device_options, devices)
    device_filters = FilterSpec(
        traffic_sources=effective_sources,
        campaigns=effective_campaigns,
        devices=effective_devices,
    )
    session_type_options = _merge_options(
        *(
            cached_session_dimension_values(
                path, option_period, device_filters, "session_type"
            )
            for option_period in option_periods
        )
    )
    session_types = checkbox_group(
        "Session type",
        session_type_options,
        "global_session_type",
        all_label="All session types",
    )
    effective_session_types = _effective_filter_values(
        session_type_options, session_types
    )
    global_scope = tuple(
        value
        for value in (
            _active_selection_scope(
                "Traffic source", source_options, sources, all_label="All traffic sources"
            ),
            _active_selection_scope(
                "Campaign", campaign_options, campaigns, all_label="All campaigns"
            ),
            _active_selection_scope("Device", device_options, devices, all_label="All devices"),
            _active_selection_scope(
                "Session type",
                session_type_options,
                session_types,
                all_label="All session types",
            ),
        )
        if value is not None
    ) or ("Global filters: None",)
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
            traffic_sources=effective_sources,
            campaigns=effective_campaigns,
            devices=effective_devices,
            session_types=effective_session_types,
        ),
        global_scope,
    )


def _render_overview_filters(compare: str) -> dict:
    _section("Overview controls")
    grain = _ui_select("Time grain", ("Month", "Week", "Day", "Quarter"), key="overview_grain")
    basis = _ui_select("Revenue basis", ("Gross", "Net"), key="overview_basis")
    primary = _ui_select(
        "Primary KPI",
        ("Revenue", "Orders", "Sessions", "Order Rate", "Average Order Value", "Gross Margin", "Refund Event Ratio"),
        key="overview_primary",
    )
    dimension_role = (
        "Current-period breakdown dimension"
        if compare == "None"
        else "Contribution dimension"
    )
    dimension = _ui_select(
        dimension_role,
        ("Traffic source", "UTM source", "Campaign", "Device", "Session type"),
        key="overview_dimension",
    )
    return {
        "grain": grain,
        "basis": basis,
        "primary": primary,
        "dimension": dimension,
        "scope": (
            f"Revenue basis: {basis}",
            f"Time grain: {grain}",
            f"{dimension_role}: {dimension}",
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
        ("Sessions", "Orders", "Order Rate", "Revenue per Session", "Gross Margin per Session"),
        key="acq_metric",
        default="Sessions",
    )
    scope = tuple(
        value
        for value in (
            _active_selection_scope(
                "Ad content", options["ad"], ad_contents, all_label="All ad content"
            ),
            _active_selection_scope(
                "Referrer type", options["referrer"], referrers, all_label="All referrer types"
            ),
            _active_selection_scope(
                "Landing page", options["landing"], landings, all_label="All landing pages"
            ),
        )
        if value is not None
    )
    return {
        "ad_contents": _effective_filter_values(options["ad"], ad_contents),
        "referrers": _effective_filter_values(options["referrer"], referrers),
        "landings": _effective_filter_values(options["landing"], landings),
        "metric": metric,
        "scope": (*scope, f"Metric: {metric}"),
    }


def _render_funnel_filters(options: dict) -> dict:
    _section(
        "Funnel controls",
        "Product-detail and billing choices define those stages and downstream reach. They do not filter the Landing cohort and are not experiment treatments.",
    )
    landings = checkbox_group(
        "Landing page", options["landing"], "funnel_landing", all_label="All landing pages"
    )
    selected_products = checkbox_group(
        "Product-detail page",
        options["product_page"],
        "funnel_product",
        all_label="All product-detail pages",
    )
    products = _effective_filter_values(options["product_page"], selected_products)
    version_labels = {
        "All": "All observed billing paths",
        "/billing": "Observed /billing path",
        "/billing-2": "Observed /billing-2 path",
    }
    version = _ui_select(
        "Billing path",
        ("All", "/billing", "/billing-2"),
        key="funnel_version",
        format_func=lambda value: version_labels[value],
    )
    compare_by = _ui_select(
        "Compare by", ("Device", "Traffic source", "Campaign", "Landing page"), key="funnel_compare"
    )
    landing_scope = selection_summary(
        "Landing page", options["landing"], landings, all_label="All landing pages"
    )
    product_scope = selection_summary(
        "Product-detail page",
        options["product_page"],
        selected_products,
        all_label="All product-detail pages",
    )
    return {
        "landings": _effective_filter_values(options["landing"], landings),
        "products": products,
        "version": version,
        "compare_by": compare_by,
        "scope": (
            f"Landing page: {landing_scope}",
            f"Product-detail page: {product_scope}",
            f"Billing path: {version_labels[version]}",
            f"Breakdown: {compare_by}",
        ),
    }


def _render_product_filters(options: dict) -> dict:
    _section("Product controls")
    basis = _ui_select(
        "Refund basis",
        ("Purchase date", "Refund date"),
        key="product_basis",
    )
    products = checkbox_group(
        "Product", options["product"], "product_names", all_label="All products"
    )
    roles = checkbox_group(
        "Item role", options["item_role"], "product_role", all_label="All item roles"
    )
    size_options = options["order_size"]
    if set(roles) == {"Add-on"}:
        size_options = tuple(
            size for size in size_options if size == "Multi-item"
        )
        st.caption("Add-on items only occur in multi-item orders.")
    sizes = checkbox_group(
        "Order size",
        size_options,
        "product_size",
        all_label=(
            "Multi-item orders"
            if size_options == ("Multi-item",)
            else "All order sizes"
        ),
    )
    refund_measure_label = _refund_measure_label(basis)
    metric = _ui_select(
        "Metric",
        (
            "Revenue",
            "Units Sold",
            "Gross Margin",
            refund_measure_label,
            "Refunded Amount",
            "Add-On Unit Share",
        ),
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
            "Order size",
            size_options,
            sizes,
            all_label=(
                "Multi-item orders"
                if size_options == ("Multi-item",)
                else "All order sizes"
            ),
        ),
        "scope": (
            f"Product: {selection_summary('Product', options['product'], products, all_label='All products')}",
            f"Item role: {selection_summary('Item role', options['item_role'], roles, all_label='All item roles')}",
            f"Order size: {selection_summary('Order size', size_options, sizes, all_label='Multi-item orders' if size_options == ('Multi-item',) else 'All order sizes')}",
            "Sales basis: Item purchase date",
            f"Refund basis: {basis}",
            f"Metric: {metric}",
        ),
    }


def render_overview(
    path: str,
    metadata: DatabaseMetadata,
    period: DatePeriod,
    compare: str,
    filters: FilterSpec,
    controls: dict,
    global_scope: tuple[str, ...],
) -> None:
    prior_period = comparison_period(period, compare)
    _page_header(
        "Executive Overview",
        period,
        prior_period,
        compare,
        global_scope,
        controls["scope"],
        _freshness_scope(metadata, "sessions", "orders", "items", "refunds"),
    )
    current = cached_overview_kpis(path, filters, period, controls["basis"])
    prior = (
        cached_overview_kpis(path, filters, prior_period, controls["basis"])
        if prior_period
        else None
    )
    evidence_keys = ("sessions", "orders", "gross_revenue", "refund_amount")
    if not _has_metric_evidence(current, evidence_keys) and not _has_metric_evidence(
        prior, evidence_keys
    ):
        _empty_state("overview")
        return

    card_keys = (
        (
            "gross_revenue",
            "orders",
            "sessions",
            "conversion_rate",
            "aov",
            "gross_margin",
            "refund_rate",
            "net_revenue",
        )
        if controls["basis"] == "Gross"
        else (
            "net_revenue",
            "orders",
            "sessions",
            "conversion_rate",
            "aov",
            "margin_after_recorded_refunds",
            "refund_rate",
            "gross_revenue",
        )
    )
    render_metrics(
        current,
        prior,
        card_keys,
        compare,
        period,
        prior_period,
        "overview",
        {"revenue_basis": controls["basis"]},
        {
            "aov": "Gross AOV",
            "conversion_rate": "Order Rate",
            "margin_after_recorded_refunds": "Margin After Refunds",
            "refund_rate": "Refund Event Ratio",
        },
    )

    primary_map = {
        "Revenue": "revenue",
        "Orders": "orders",
        "Sessions": "sessions",
        "Order Rate": "conversion_rate",
        "Average Order Value": "aov",
        "Gross Margin": "gross_margin",
        "Refund Event Ratio": "refund_rate",
    }
    metric = primary_map[controls["primary"]]
    label, value_format = METRIC_META[metric]
    if metric == "revenue":
        label = f"{controls['basis']} Revenue"
    elif metric == "aov":
        label = "Average Order Value (Gross)"
    elif metric == "conversion_rate":
        label = "Order Rate"
    trend = cached_overview_trend(
        path, filters, period, controls["grain"], controls["basis"]
    )
    comparison = (
        cached_overview_trend(
            path, filters, prior_period, controls["grain"], controls["basis"]
        )
        if prior_period
        else None
    )
    trend_chips = (label, f"Current: {period.label}")
    if prior_period:
        trend_chips += (f"{compare}: {prior_period.label}",)
    _section("Performance Trend", chips=trend_chips)
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

    dimension = controls["dimension"]
    current_segments = overview_drivers(
        path,
        filters,
        period,
        dimension=dimension,
        revenue_basis=controls["basis"],
    )
    prior_segments = (
        overview_drivers(
            path,
            filters,
            prior_period,
            dimension=dimension,
            revenue_basis=controls["basis"],
        )
        if prior_period
        else None
    )
    left, right = st.columns(2)
    with left:
        driver_title = (
            "Observed Revenue-Change Contributions"
            if prior_period is not None
            else "Revenue-Change Decomposition"
        )
        driver_chips = (
            (
                f"{controls['basis']} Revenue",
                "Includes recorded refunds"
                if controls["basis"] == "Net"
                else "Recorded refunds excluded",
                "Accounting decomposition",
                "Not causal",
            )
            if prior_period is not None
            else (f"{controls['basis']} Revenue", "Comparison required")
        )
        _section(
            driver_title,
            chips=driver_chips,
        )
        driver_frame = revenue_driver_contributions(
            current,
            prior,
            revenue_basis=controls["basis"],
        )
        if not driver_frame.empty:
            driver_frame = driver_frame.copy()
            driver_frame["driver"] = driver_frame["driver"].map(_title_case)
            driver_frame["value_label"] = driver_frame["value_label"].map(
                _title_case
            )
        if prior_period is None:
            st.info("Choose a comparison period to decompose the observed revenue change.")
        else:
            if controls["basis"] == "Gross":
                st.caption(
                    "Recorded-refund impact is excluded from this Gross revenue decomposition. "
                    "Select Net under Revenue basis to include it."
                )
            st.plotly_chart(
                contribution_bar(
                    driver_frame,
                    "driver",
                    "contribution",
                    f"Contribution to {controls['basis'].lower()} revenue change",
                    value_format="currency",
                    comparison_label=compare,
                ),
                width="stretch",
                key="overview_revenue_contributions",
            )
    with right:
        segment_label = f"{controls['basis']} Revenue"
        if prior_period is None:
            _section(
                f"Current {segment_label.lower()} by {dimension.lower()}",
                chips=("Current period only", "No comparison selected"),
            )
            st.plotly_chart(
                ranked_bar(
                    current_segments,
                    "segment",
                    "revenue",
                    segment_label,
                    value_format="currency",
                    display_title=False,
                ),
                width="stretch",
                key="overview_segment_current",
            )
            segment_detail = current_segments[["segment", "revenue"]].rename(
                columns={"revenue": "current"}
            )
        else:
            _section(
                f"Revenue-Change Contribution by {_title_case(dimension)}",
                chips=(segment_label, f"vs. {prior_period.label}", "Not causal"),
            )
            segment_detail = segment_contributions(
                current_segments,
                prior_segments,
                value_column="revenue",
            )
            st.plotly_chart(
                contribution_bar(
                    segment_detail,
                    "segment",
                    "absolute_delta",
                    f"Contribution to {segment_label.lower()} change",
                    value_format="currency",
                    comparison_label=compare,
                    detail_label=segment_label,
                ),
                width="stretch",
                key="overview_segment_contributions",
            )

    if prior_period is None:
        _section(
            "Current-Period Segment Detail",
            f"Current {segment_label.lower()} by {dimension.lower()}; no change contribution is calculated without a comparison period.",
        )
    else:
        _section(
            "Contribution Detail",
            "Positive and negative values reconcile to the observed period-over-period change; they do not establish causality.",
        )
    _render_detail_table(
        segment_detail,
        {
            "current": "currency",
            "comparison": "currency",
            "absolute_delta": "currency",
        },
    )


def _acquisition_totals(frame: pd.DataFrame) -> dict[str, float]:
    sessions = float(frame["sessions"].sum()) if not frame.empty else 0
    orders = float(frame["orders"].sum()) if not frame.empty else 0
    revenue = float(frame["revenue"].sum()) if not frame.empty else 0
    margin = float(frame["gross_margin"].sum()) if not frame.empty else 0
    return {
        "sessions": sessions,
        "orders": orders,
        "conversion_rate": orders / sessions if sessions else pd.NA,
        "revenue_per_session": revenue / sessions if sessions else pd.NA,
        "margin_per_session": margin / sessions if sessions else pd.NA,
    }


def render_acquisition(
    path: str,
    metadata: DatabaseMetadata,
    period: DatePeriod,
    compare: str,
    filters: FilterSpec,
    controls: dict,
    global_scope: tuple[str, ...],
) -> None:
    scoped = replace(
        filters,
        ad_contents=controls["ad_contents"],
        referrer_types=controls["referrers"],
    )
    prior_period = comparison_period(period, compare)
    _page_header(
        "Acquisition",
        period,
        prior_period,
        compare,
        global_scope,
        controls["scope"],
        _freshness_scope(metadata, "sessions", "pageviews", "orders"),
    )
    sources = cached_acquisition(
        path, scoped, period, "UTM source", controls["landings"]
    ).copy()
    sources["segment"] = sources["segment"].map(format_filter_option)
    prior_sources = (
        cached_acquisition(
            path, scoped, prior_period, "UTM source", controls["landings"]
        ).copy()
        if prior_period
        else None
    )
    if prior_sources is not None:
        prior_sources["segment"] = prior_sources["segment"].map(
            format_filter_option
        )
    source_totals = _acquisition_totals(sources)
    prior_totals = (
        _acquisition_totals(prior_sources) if prior_sources is not None else None
    )
    evidence_keys = ("sessions", "orders", "revenue", "gross_margin")
    if not _has_metric_evidence(
        source_totals, evidence_keys
    ) and not _has_metric_evidence(prior_totals, evidence_keys):
        _empty_state("acquisition")
        return
    render_metrics(
        source_totals,
        prior_totals,
        ("sessions", "orders", "conversion_rate", "revenue_per_session"),
        compare,
        period,
        prior_period,
        "acquisition",
        label_overrides={"conversion_rate": "Order Rate"},
    )

    metric_map = {
        "Sessions": ("sessions", "integer"),
        "Orders": ("orders", "integer"),
        "Order Rate": ("conversion_rate", "percent"),
        "Revenue per Session": ("revenue_per_session", "currency"),
        "Gross Margin per Session": ("margin_per_session", "currency"),
    }
    metric, value_format = metric_map[controls["metric"]]
    chart_type = "Volume" if metric in {"sessions", "orders"} else "Efficiency"
    dimensions = (
        ("UTM source", "UTM Source"),
        ("Campaign", "Campaign"),
        ("Device", "Device"),
        ("Landing page", "Landing Page"),
    )
    frames: dict[str, tuple[pd.DataFrame, pd.DataFrame | None]] = {
        "UTM source": (sources, prior_sources)
    }
    for dimension, _ in dimensions[1:]:
        current_frame = cached_acquisition(
            path, scoped, period, dimension, controls["landings"]
        ).copy()
        prior_frame = (
            cached_acquisition(
                path, scoped, prior_period, dimension, controls["landings"]
            ).copy()
            if prior_period
            else None
        )
        if dimension in {"UTM source", "Campaign", "Device", "Landing page"}:
            current_frame["segment"] = current_frame["segment"].map(
                format_filter_option
            )
            if prior_frame is not None:
                prior_frame["segment"] = prior_frame["segment"].map(
                    format_filter_option
                )
        frames[dimension] = (current_frame, prior_frame)

    left, right = st.columns(2)
    chart_columns = (left, right)
    for index, (dimension, title_prefix) in enumerate(dimensions):
        if index == 2:
            chart_columns = st.columns(2)
        current_frame, prior_frame = frames[dimension]
        with chart_columns[index % 2]:
            chips = (controls["metric"],)
            chips += (
                (f"vs. {prior_period.label}",)
                if prior_period
                else ("Current period only",)
            )
            _section(f"{title_prefix} {chart_type}", chips=chips)
            _render_comparison_or_current_bar(
                current_frame,
                prior_frame,
                category="segment",
                metric=metric,
                label=controls["metric"],
                value_format=value_format,
                compare=compare,
                key=f"acq_{dimension.lower().replace(' ', '_')}",
                denominator=(
                    "sessions"
                    if metric
                    in {"conversion_rate", "revenue_per_session", "margin_per_session"}
                    else None
                ),
            )
    traffic_sources = cached_acquisition(
        path, scoped, period, "Traffic source", controls["landings"]
    )
    _section(
        "Traffic-Source Detail",
        "Current-period metrics by derived traffic source; this complements the single metric selected in the charts.",
    )
    _render_detail_table(
        traffic_sources,
        {
            "sessions": "integer",
            "orders": "integer",
            "revenue": "currency",
            "gross_margin": "currency",
            "conversion_rate": "percent",
            "revenue_per_session": "currency",
            "margin_per_session": "currency",
        },
    )


def render_funnel(
    path: str,
    metadata: DatabaseMetadata,
    period: DatePeriod,
    compare: str,
    filters: FilterSpec,
    controls: dict,
    global_scope: tuple[str, ...],
) -> None:
    prior_period = comparison_period(period, compare)
    _page_header(
        "Website Funnel",
        period,
        prior_period,
        compare,
        global_scope,
        controls["scope"],
        _freshness_scope(metadata, "sessions", "pageviews"),
    )
    current = cached_funnel(
        path,
        filters,
        period,
        controls["landings"],
        controls["products"],
        controls["version"],
    )
    prior = (
        cached_funnel(
            path,
            filters,
            prior_period,
            controls["landings"],
            controls["products"],
            controls["version"],
        )
        if prior_period
        else None
    )
    current_has_evidence = _funnel_has_evidence(current)
    prior_has_evidence = _funnel_has_evidence(prior)
    if not current_has_evidence and not prior_has_evidence:
        _empty_state("funnel")
        return
    current_final = (
        _optional_float(current.iloc[-1]["total_conversion"])
        if not current.empty
        else None
    )
    prior_final = (
        _optional_float(prior.iloc[-1]["total_conversion"])
        if prior is not None and not prior.empty
        else None
    )
    kpis = {
        "sessions": float(current.iloc[0]["sessions"]) if not current.empty else 0,
        "conversion_rate": current_final,
        "orders": float(current.iloc[-1]["sessions"]) if not current.empty else 0,
    }
    prior_kpis = None if prior is None else {
        "sessions": float(prior.iloc[0]["sessions"]) if not prior.empty else 0,
        "conversion_rate": prior_final,
        "orders": float(prior.iloc[-1]["sessions"]) if not prior.empty else 0,
    }
    render_metrics(
        kpis,
        prior_kpis,
        ("sessions", "orders", "conversion_rate"),
        compare,
        period,
        prior_period,
        "funnel",
        label_overrides={"orders": "Observed Thank-You Sessions", "conversion_rate": "Conversion Rate"},
    )
    left, right = st.columns([1.35, 1])
    with left:
        _section(
            "Ordered Funnel",
            chips=("Current session cohort", f"{period.label}", "Observed paths"),
        )
        funnel_frame = current if current_has_evidence else pd.DataFrame()
        st.plotly_chart(funnel_chart(funnel_frame), width="stretch", key="funnel_main")
    with right:
        _section(
            "Stage-Transition Drop-Off",
            chips=(
                "Sessions lost between adjacent stages",
                (f"vs. {prior_period.label}" if prior_period else "Current period only"),
            ),
        )
        drop = current.loc[current["transition"].notna()].copy()
        prior_drop = (
            prior.loc[prior["transition"].notna()].copy()
            if prior is not None and not prior.empty
            else None
        )
        _render_comparison_or_current_bar(
            drop,
            prior_drop,
            category="transition",
            metric="drop_off",
            label="Sessions lost",
            value_format="integer",
            compare=compare,
            key="funnel_dropoff",
            denominator=None,
        )
    _section(
        f"Final Observed Conversion by {_title_case(controls['compare_by'])}",
        "Thank-you-page reach is the final observed event; this is not an experiment result.",
    )
    breakdown = cached_funnel_breakdown(
        path, filters, period, controls["compare_by"], controls["landings"], controls["products"], controls["version"]
    )
    prior_breakdown = (
        cached_funnel_breakdown(
            path,
            filters,
            prior_period,
            controls["compare_by"],
            controls["landings"],
            controls["products"],
            controls["version"],
        )
        if prior_period
        else None
    )
    if controls["compare_by"] in {"Landing page", "Device", "Campaign"}:
        breakdown = breakdown.copy()
        breakdown["segment"] = breakdown["segment"].map(format_filter_option)
        if prior_breakdown is not None:
            prior_breakdown = prior_breakdown.copy()
            prior_breakdown["segment"] = prior_breakdown["segment"].map(
                format_filter_option
            )
    _render_comparison_or_current_bar(
        breakdown,
        prior_breakdown,
        category="segment",
        metric="conversion_rate",
        label="Final Observed Conversion",
        value_format="percent",
        compare=compare,
        key="funnel_breakdown",
        denominator="sessions",
    )
    detail = current.copy()
    detail["transition"] = detail["transition"].fillna("Starting Stage")
    if prior is not None and not prior.empty:
        detail = detail.merge(
            prior[["stage", "total_conversion"]],
            on="stage",
            how="left",
            suffixes=("", "_comparison"),
        )
    _section(
        "Funnel Detail",
        "One row per ordered stage with current reach, adjacent-step conversion, total conversion, and drop-off.",
    )
    comparison_label = (
        {"Previous period": "Previous Period Total (%)", "Previous year": "Previous Year Total (%)"}.get(
            compare,
            "Comparison Total (%)",
        )
    )
    _render_detail_table(
        detail,
        column_labels={
            "drop_off": "Drop-Off",
            "total_conversion_comparison": comparison_label,
        },
        column_widths={
            "stage": 104,
            "transition": 188,
            "sessions": 88,
            "step_conversion": 116,
            "total_conversion": 116,
            "drop_off": 88,
            "total_conversion_comparison": 148,
        },
    )


def _product_totals(frame: pd.DataFrame) -> dict[str, float]:
    units = float(frame["units"].sum()) if not frame.empty else 0
    refunded = float(frame["units_refunded"].sum()) if not frame.empty else 0
    return {
        "revenue": float(frame["revenue"].sum()) if not frame.empty else 0,
        "units": units,
        "gross_margin": float(frame["gross_margin"].sum()) if not frame.empty else 0,
        "refund_rate": refunded / units if units else pd.NA,
        "refunded_amount": float(frame["refunded_amount"].sum()) if not frame.empty else 0,
    }


def render_products(
    path: str,
    metadata: DatabaseMetadata,
    period: DatePeriod,
    compare: str,
    filters: FilterSpec,
    controls: dict,
    global_scope: tuple[str, ...],
) -> None:
    prior_period = comparison_period(period, compare)
    _page_header(
        "Products & Refunds",
        period,
        prior_period,
        compare,
        global_scope,
        controls["scope"],
        _freshness_scope(metadata, "sessions", "orders", "items", "refunds"),
    )
    current = cached_products(
        path,
        filters,
        period,
        controls["products"],
        controls["roles"],
        controls["sizes"],
        controls["basis"],
    )
    prior = (
        cached_products(
            path,
            filters,
            prior_period,
            controls["products"],
            controls["roles"],
            controls["sizes"],
            controls["basis"],
        )
        if prior_period
        else None
    )
    if not _product_has_evidence(current) and not _product_has_evidence(prior):
        _empty_state("product")
        return
    refund_rate_label = _refund_measure_label(controls["basis"])
    render_metrics(
        _product_totals(current),
        _product_totals(prior) if prior is not None else None,
        ("revenue", "units", "gross_margin", "refund_rate"),
        compare,
        period,
        prior_period,
        "products",
        {"date_basis": controls["basis"]},
        {"refund_rate": refund_rate_label},
    )
    if controls["basis"] == "Refund date":
        st.info(
            "Refund events use refund timestamps. The displayed ratio divides those events by units purchased in the same calendar period, so it is an event ratio rather than a purchase-cohort refund rate."
        )

    metric_map = {
        "Revenue": ("revenue", "currency"),
        "Units Sold": ("units", "integer"),
        "Gross Margin": ("gross_margin", "currency"),
        refund_rate_label: ("refund_rate", "percent"),
        "Refunded Amount": ("refunded_amount", "currency"),
        "Add-On Unit Share": ("addon_unit_share", "percent"),
    }
    metric, value_format = metric_map[controls["metric"]]
    if metric != "refunded_amount":
        exposure_metric = "refunded_amount"
        exposure_label = "Refunded Amount"
        exposure_format = "currency"
        exposure_denominator = None
    else:
        exposure_metric = "refund_rate"
        exposure_label = refund_rate_label
        exposure_format = "percent"
        exposure_denominator = "units"
    performance_column, refunds_column = st.columns(2)
    with performance_column:
        _section(
            "Product Performance",
            chips=(
                controls["metric"],
                (f"vs. {prior_period.label}" if prior_period else "Current period only"),
            ),
        )
        _render_comparison_or_current_bar(
            current,
            prior,
            category="product",
            metric=metric,
            label=controls["metric"],
            value_format=value_format,
            compare=compare,
            key="product_performance",
            denominator=(
                "units" if metric in {"refund_rate", "addon_unit_share"} else None
            ),
        )
    with refunds_column:
        _section(
            "Refund Exposure",
            chips=(
                exposure_label,
                (f"vs. {prior_period.label}" if prior_period else "Current period only"),
            ),
        )
        _render_comparison_or_current_bar(
            current,
            prior,
            category="product",
            metric=exposure_metric,
            label=exposure_label,
            value_format=exposure_format,
            compare=compare,
            key="product_refunds",
            denominator=exposure_denominator,
        )
    trend_scope = (
        controls["product_scope"],
        controls["role_scope"],
        controls["size_scope"],
    )
    basket_column, trend_column = st.columns([0.36, 0.64])
    with basket_column:
        _section(
            "Basket Mix",
            chips=(
                "Orders by basket size",
                (f"vs. {prior_period.label}" if prior_period else "Current period only"),
            ),
        )
        basket = cached_basket(path, filters, period, controls["products"], controls["roles"], controls["sizes"])
        prior_basket = (
            cached_basket(
                path,
                filters,
                prior_period,
                controls["products"],
                controls["roles"],
                controls["sizes"],
            )
            if prior_period
            else None
        )
        _render_comparison_or_current_bar(
            basket,
            prior_basket,
            category="order_size",
            metric="orders",
            label="Orders",
            value_format="integer",
            compare=compare,
            key="product_basket",
            denominator=None,
        )
    with trend_column:
        trend_context = "<br>".join(trend_scope)
        trend_basis = (
            f"Refund basis: {controls['basis']}"
            if metric in {"refund_rate", "refunded_amount"}
            else "Sales basis: Item purchase date"
        )
        _section(
            f"Product-Scoped Monthly {controls['metric']}",
            chips=(trend_basis, *trend_scope),
        )
        trend = cached_product_trend(
            path,
            filters,
            period,
            controls["products"],
            controls["roles"],
            controls["sizes"],
            controls["basis"],
        )
        prior_trend = (
            cached_product_trend(
                path,
                filters,
                prior_period,
                controls["products"],
                controls["roles"],
                controls["sizes"],
                controls["basis"],
            )
            if prior_period
            else None
        )
        aggregate = aggregate_product_trend(trend, metric)
        prior_aggregate = (
            aggregate_product_trend(prior_trend, metric)
            if prior_trend is not None
            else None
        )
        trend_label = (
            f"Total {controls['metric']}"
            if len(controls["products"]) > 1
            else controls["metric"]
        )
        st.plotly_chart(
            trend_chart(
                aggregate,
                "period",
                metric,
                trend_label,
                value_format=value_format,
                comparison=prior_aggregate,
                comparison_label=compare,
                hover_context=trend_context,
                display_title=False,
            ),
            width="stretch",
            key="product_trend",
        )
    _section(
        "Product Detail",
        "One row per product with current-period sales, margin, refund, and add-on metrics.",
    )
    _render_detail_table(
        current,
        {
            "units": "integer",
            "addon_units": "integer",
            "units_refunded": "integer",
            "revenue": "currency",
            "cogs": "currency",
            "refunded_amount": "currency",
            "gross_margin": "currency",
            "net_revenue": "currency",
            "refund_rate": "percent",
            "addon_unit_share": "percent",
        },
        {
            "cogs": "COGS",
            "addon_units": "Add-On Units",
            "units_refunded": "Refund Units",
            "refunded_amount": "Refund $",
            "gross_margin": "Gross Margin",
            "net_revenue": "Net Revenue",
            "refund_rate": "Refund Rate (%)",
            "addon_unit_share": "Add-On Share (%)",
        },
        {
            "product": 176,
            "units": 58,
            "revenue": 86,
            "cogs": 86,
            "addon_units": 78,
            "units_refunded": 78,
            "refunded_amount": 86,
            "gross_margin": 100,
            "net_revenue": 100,
            "refund_rate": 86,
            "addon_unit_share": 90,
        },
    )


def render_top_navigation() -> str:
    return st.segmented_control(
        "Page",
        PAGES,
        default="Executive Overview",
        format_func=lambda value: PAGE_NAV_LABELS[value],
        key="top_navigation",
        label_visibility="collapsed",
        width="stretch",
        wrap=True,
    ) or "Executive Overview"


def render_app(path: str | Path, metadata: DatabaseMetadata) -> None:
    inject_css()
    path_string = str(path)
    with st.container(border=False, key="top_nav_shell"):
        brand, nav = st.columns([0.3, 0.7], gap="large", vertical_alignment="center")
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
        filter_column, content_column = st.columns([0.22, 0.78], gap="medium")
        with filter_column:
            with st.spinner("Loading filters and controls…"):
                period, compare, filters, global_scope = _global_filters(
                    path_string, metadata
                )
                option_periods = _comparison_option_periods(period, compare)
                if page == "Executive Overview":
                    controls = _render_overview_filters(compare)
                elif page == "Acquisition":
                    options = _merge_option_dicts(
                        *(
                            cached_acquisition_filter_options(
                                path_string, option_period, filters
                            )
                            for option_period in option_periods
                        )
                    )
                    controls = _render_acquisition_filters(options)
                elif page == "Website Funnel":
                    options = _merge_option_dicts(
                        *(
                            cached_funnel_filter_options(
                                path_string, option_period, filters
                            )
                            for option_period in option_periods
                        )
                    )
                    controls = _render_funnel_filters(options)
                else:
                    options = _merge_option_dicts(
                        *(
                            cached_product_filter_options(
                                path_string, option_period, filters
                            )
                            for option_period in option_periods
                        )
                    )
                    controls = _render_product_filters(options)
            st.markdown(
                "<div class='filter-bottom-spacer' aria-hidden='true'></div>",
                unsafe_allow_html=True,
            )

        with content_column:
            with st.spinner("Calculating from the local database…"):
                if page == "Executive Overview":
                    render_overview(
                        path_string,
                        metadata,
                        period,
                        compare,
                        filters,
                        controls,
                        global_scope,
                    )
                elif page == "Acquisition":
                    render_acquisition(
                        path_string,
                        metadata,
                        period,
                        compare,
                        filters,
                        controls,
                        global_scope,
                    )
                elif page == "Website Funnel":
                    render_funnel(
                        path_string,
                        metadata,
                        period,
                        compare,
                        filters,
                        controls,
                        global_scope,
                    )
                else:
                    render_products(
                        path_string,
                        metadata,
                        period,
                        compare,
                        filters,
                        controls,
                        global_scope,
                    )


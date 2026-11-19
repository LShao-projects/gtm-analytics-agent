"""Read-only investigation agent panel: a chat column docked to the right of the dashboard.

The panel is open by default and collapses to a narrow rail. It reads the page's global filters
and revenue basis and never changes any dashboard control.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from itertools import groupby
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.filters import comparison_period
from dashboard.labels import display_label
from dashboard.models import DatePeriod, FilterSpec
from investigation import (
    Budgets,
    DashboardContext,
    EvidenceRegistry,
    GeminiClient,
    InvestigationResult,
    InvestigationTools,
    ScriptedClient,
    investigate,
    trace_to_json,
)
from investigation.facts import format_value, signed_money
from investigation.models import Claim
from investigation.providers import ClassifyDecision, FinishDecision, ToolDecision

MAX_LIVE_RUNS_PER_SESSION = 30
MAX_THREAD_ENTRIES = 6
LIVE_MODEL = "Gemini (live)"
DEMO_MODEL = "Scripted replay (no model call)"
LEVEL_LABELS = {
    "verified_fact": "Fact",
    "observed_contribution": "Observed contribution",
    "hypothesis": "Hypothesis (untested)",
    "unknown": "Unknown",
}
# Where a status has a code-rendered body, say who wrote its words; other statuses have none.
_PROVENANCE = {
    "report": "Facts are rendered by code from evidence; only hypotheses and unknowns are model text.",
    "definition": "Definitions are quoted by code from the Data Guide; the model only chose which ones.",
}

# Styles the panel's interior, open and collapsed; its grid column and sticky height are set by the
# workspace layout in dashboard/ui.py. The thread's scroll box is a column-reverse flex container,
# so a short thread sits at the bottom above the input and a long one stays scrolled to the newest
# message. The collapse and expand buttons are tabs on the panel's left edge, vertically centered;
# their containing block is the sticky grid cell, so the panel's overflow:hidden does not clip them.
PANEL_CSS = """
<style>
.st-key-agent_panel {
  height:100%; box-sizing:border-box; padding:.7rem 1rem .9rem; overflow:hidden;
  background:var(--white); border-left:1px solid var(--line);
  display:flex; flex-direction:column; gap:.45rem; flex-wrap:nowrap;
}
.st-key-agent_panel > * { flex:0 0 auto; }
.st-key-agent_panel > div:first-child div[data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; }
.st-key-agent_panel > div:first-child div[data-testid="stColumn"]:first-child {
  flex:1 1 0 !important; width:auto !important;
}
.st-key-agent_panel > div:first-child div[data-testid="stColumn"]:not(:first-child) {
  flex:0 0 auto !important; width:auto !important; min-width:0 !important;
}
.st-key-agent_panel > div:has(> .st-key-agent_thread) {
  flex:1 1 0; min-height:0; overflow-y:auto; display:flex; flex-direction:column-reverse;
}
.st-key-agent_thread { flex:0 0 auto; }
.st-key-agent_panel_collapsed {
  height:100%; box-sizing:border-box; padding:.7rem .3rem; overflow:hidden;
  background:var(--white); border-left:1px solid var(--line);
  display:flex; flex-direction:column; align-items:center; gap:.6rem;
}
.st-key-agent_panel_collapsed > * { flex:0 0 auto; }
.st-key-agent_panel_collapsed [data-testid="stMarkdownContainer"] { margin-bottom:0; }
.agent-rail-label {
  writing-mode:vertical-rl; color:var(--muted); font-size:.78rem; font-weight:650;
  letter-spacing:.04em; line-height:1.3; white-space:nowrap;
}
.st-key-agent_panel button[kind="tertiary"],
.st-key-agent_panel_collapsed button[kind="tertiary"] { padding:.1rem .35rem; min-height:0; }
.st-key-agent_collapse, .st-key-agent_expand {
  position:absolute; left:-10px; top:50%; transform:translateY(-50%); z-index:6;
}
.st-key-agent_collapse button[kind="tertiary"], .st-key-agent_expand button[kind="tertiary"] {
  width:20px; height:56px; min-height:56px; padding:0; border-radius:10px;
  background:var(--white); border:1px solid #D3D8E6; color:var(--navy);
  box-shadow:0 2px 8px rgba(24,39,75,.12);
}
.st-key-agent_collapse button[kind="tertiary"]:hover, .st-key-agent_expand button[kind="tertiary"]:hover {
  background:#F2EFFF; border-color:#B9B1E8;
}
.st-key-agent_collapse span[role="img"], .st-key-agent_expand span[role="img"] { font-size:1.3rem; }
</style>
"""


def build_context(
    page: str,
    period: DatePeriod,
    mode: str,
    filters: FilterSpec,
    revenue_basis: str,
) -> DashboardContext:
    return DashboardContext(
        page=page,
        current_period=period,
        comparison_period=comparison_period(period, mode),
        comparison_mode=mode,
        filters=filters,
        revenue_basis=revenue_basis,
    )


def context_caption(context: DashboardContext, basis_note: str = "") -> str:
    comparison = (
        context.comparison_period.label if context.comparison_period else "no comparison"
    )
    active = [
        f"{name.replace('_', ' ')}: {', '.join(values)}"
        for name, values in vars(context.filters).items()
        if values is not None
    ]
    return (
        f"{context.page}. {context.current_period.label} versus {comparison}. "
        f"Filters: {'; '.join(active) or 'none'}. "
        f"Revenue basis: {context.revenue_basis}{basis_note}."
    )


def page_revenue_basis(controls: Mapping[str, object]) -> tuple[str, str]:
    """The basis the page is showing, and a note when the page has no basis control."""
    basis = controls.get("basis")
    if basis in ("Gross", "Net"):
        return str(basis), ""
    return "Gross", " (default; this page has no basis control)"


def claim_rows(result: InvestigationResult) -> list[dict[str, str]]:
    """Pair every report claim with its rendered sentence and evidence reference."""
    if result.report is None:
        return []
    return [
        {
            "Type": LEVEL_LABELS.get(claim.level, claim.level),
            "Statement": sentence,
            "Evidence": ", ".join(claim.evidence_ids),
        }
        for claim, sentence in zip(result.report.claims, result.sentences)
    ]


# Evidence measure -> (display name, value format); anything not listed is a dollar amount.
MEASURES = {
    "revenue": "Revenue",
    "gross_revenue": "Gross Revenue",
    "net_revenue": "Net Revenue",
    "orders": ("Orders", "integer"),
    "sessions": ("Sessions", "integer"),
    "conversion_rate": ("Order Rate", "percent"),
    "aov": "Gross AOV",
    "gross_margin": "Gross Margin",
    "margin_after_recorded_refunds": "Margin After Recorded Refunds",
    "refund_amount": "Refund Amount",
    "refund_rate": ("Refund Event Ratio", "percent"),
}


def _measure(key: str) -> tuple[str, str]:
    name = MEASURES.get(key, key.replace("_", " ").title())
    return name if isinstance(name, tuple) else (name, "currency")


def _move(comparison, current, value_format: str) -> str:
    if comparison is None and current is None:
        return ""
    return f"{format_value(comparison, value_format)} to {format_value(current, value_format)}"


def evidence_frames(result: InvestigationResult) -> list[tuple[str, pd.DataFrame]]:
    """One narrow, formatted table per evidence record, readable in the drawer."""
    frames = []
    for record in result.evidence:
        payload = record.as_dict()
        title = f"{record.evidence_id} {record.tool_name.replace('_', ' ').capitalize()}"
        if record.tool_name == "revenue_summary":
            current, comparison = payload["current"], payload["comparison"] or {}
            rows = []
            for key, value in current.items():
                name, value_format = _measure(key)
                rows.append(
                    (
                        name,
                        format_value(comparison.get(key), value_format) if comparison else "",
                        format_value(value, value_format),
                    )
                )
            frame = pd.DataFrame(rows, columns=["Measure", "Comparison", "Current"])
        elif record.tool_name == "revenue_decomposition":
            frame = pd.DataFrame(
                [
                    (
                        row["driver"],
                        _move(row["comparison"], row["current"], row["value_format"]),
                        signed_money(row["contribution"]),
                    )
                    for row in payload["drivers"]
                ],
                columns=["Driver", "Comparison to Current", "Contribution"],
            )
        else:
            title += f" ({payload['dimension']})"
            frame = pd.DataFrame(
                [
                    (
                        display_label(row["segment"]),
                        _move(row["comparison"], row["current"], "currency"),
                        signed_money(row["absolute_delta"]),
                    )
                    for row in payload["segments"]
                ],
                columns=["Segment", "Comparison to Current", "Change"],
            )
        frames.append((title, frame))
    return frames


def trace_frame(result: InvestigationResult) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Step": [step.index for step in result.trace],
            "Kind": [step.kind for step in result.trace],
            "Detail": [step.detail for step in result.trace],
            "Evidence": [step.evidence_id or "" for step in result.trace],
            "Seconds": [step.elapsed_seconds for step in result.trace],
        }
    )


def _gemini_client() -> GeminiClient:
    import google.auth

    credentials, project = google.auth.default()
    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or getattr(credentials, "quota_project_id", None)
        or project
    )
    if not project:
        raise RuntimeError("No Google Cloud project is configured for the credentials.")
    return GeminiClient(
        project, model=os.environ.get("GTM_AGENT_MODEL", "gemini-3-flash-preview")
    )


def _replay_client() -> ScriptedClient:
    """A fixed trajectory that needs no model; it ignores the wording of the question."""
    return ScriptedClient(
        [
            ClassifyDecision("supported_investigation"),
            ToolDecision("revenue_summary"),
            ToolDecision("revenue_decomposition"),
            ToolDecision("segment_contributions", {"dimension": "Traffic source"}),
            FinishDecision(
                (
                    Claim("", "verified_fact", ("EV-001",), "revenue_change"),
                    Claim("", "observed_contribution", ("EV-002",), "primary_contributor"),
                    Claim("", "observed_contribution", ("EV-003",), "primary_contributor"),
                    Claim(
                        "The dataset has no ad spend, promotion or site-change records, "
                        "so it cannot show why these contributions moved.",
                        "unknown",
                    ),
                ),
                "supported_conclusion",
            ),
        ]
    )


def _plain(text: str) -> str:
    """Escape dollar signs so Streamlit markdown does not read amounts as math."""
    return text.replace("$", "\\$")


def _cited(row: dict[str, str]) -> str:
    return f" :gray-badge[{row['Evidence']}]" if row["Evidence"] else ""


def _render_claims(result: InvestigationResult) -> None:
    """Show report claims grouped by level in a fixed order, whatever order the model listed them."""
    order = {label: index for index, label in enumerate(LEVEL_LABELS.values())}
    rows = sorted(
        claim_rows(result),
        key=lambda row: (order.get(row["Type"], len(order)), row["Type"]),
    )
    for label, group in groupby(rows, key=lambda row: row["Type"]):
        st.caption(label)
        if label == LEVEL_LABELS["verified_fact"]:
            st.markdown(
                "\n\n".join(f"**{_plain(row['Statement'])}**{_cited(row)}" for row in group)
            )
        else:
            st.markdown(
                "\n".join(f"- {_plain(row['Statement'])}{_cited(row)}" for row in group)
            )


def _render_definitions(result: InvestigationResult) -> None:
    """Show each Data Guide entry as a title and labeled parts, quoted as the Guide wrote them."""
    for index, definition in enumerate(result.definitions):
        if index:
            st.divider()
        st.markdown(f"**{_plain(definition.name)}** :gray-badge[{_plain(definition.context)}]")
        for label, value in definition.fields:
            st.markdown(f":gray[{label}]  \n{_plain(value)}")
        st.caption(f"Source: {definition.source}")


def _render_answer(result: InvestigationResult) -> None:
    if result.status == "clarification":
        st.info(_plain(result.clarification.question))
    elif result.status == "refusal":
        st.warning(_plain(result.refusal_reason))
        st.caption("I can")
        st.markdown(
            "\n".join(f"- {_plain(item[:1].upper() + item[1:])}" for item in result.refusal_scope)
        )
    elif result.status == "definition":
        _render_definitions(result)
    elif result.status == "failure":
        st.error(
            f"The investigation stopped without a report ({result.stop_reason}). "
            "No unverified answer is shown."
        )
        for issue in result.issues:
            st.caption(_plain(f"{issue.code}: {issue.message}"))
    else:
        _render_claims(result)


def _render_details(result: InvestigationResult, position: int) -> None:
    """Evidence and trace stay collapsed, with run metadata inside, so the answer stays uncluttered."""
    count = len(result.evidence)
    if count:
        with st.expander(f"Evidence ({count} record{'' if count == 1 else 's'})"):
            for title, frame in evidence_frames(result):
                st.markdown(f"**{title}**")
                st.table(frame.map(_plain).set_index(frame.columns[0]))
    with st.expander("Investigation trace"):
        st.caption(f"Model: {result.model or 'none'}. Stop reason: {result.stop_reason}.")
        if result.status in _PROVENANCE:
            st.caption(_PROVENANCE[result.status])
        st.dataframe(trace_frame(result), hide_index=True, width="stretch")
        st.download_button(
            "Download trace (JSON)",
            trace_to_json(result),
            file_name="investigation_trace.json",
            mime="application/json",
            key=f"agent_trace_download_{position}",
        )


def _render_result(result: InvestigationResult, position: int) -> None:
    _render_answer(result)
    _render_details(result, position)


def _toggle_collapsed() -> None:
    st.session_state["agent_collapsed"] = not st.session_state.get("agent_collapsed", False)


def _ask(
    question: str,
    path: str | Path,
    context: DashboardContext,
    caption: str,
    model_choice: str,
) -> None:
    if (
        model_choice == LIVE_MODEL
        and st.session_state.get("agent_live_runs", 0) >= MAX_LIVE_RUNS_PER_SESSION
    ):
        st.error("This session reached its limit of live model runs. Reload to reset it.")
        return
    try:
        client = _gemini_client() if model_choice == LIVE_MODEL else _replay_client()
    except Exception as error:
        st.error(
            "The model could not be set up. Run `gcloud auth application-default login`, "
            f"or choose the scripted replay in Settings. ({type(error).__name__})"
        )
        return
    tools = InvestigationTools(path, EvidenceRegistry())
    with st.spinner("Investigating with read-only tools…"):
        result = investigate(question, tools, client, context=context, budgets=Budgets())
    if model_choice == LIVE_MODEL:
        st.session_state["agent_live_runs"] = st.session_state.get("agent_live_runs", 0) + 1
    thread = st.session_state.setdefault("agent_thread", [])
    thread.insert(0, (question, result, caption))
    del thread[MAX_THREAD_ENTRIES:]


@st.fragment
def _panel(
    path: str | Path,
    page: str,
    period: DatePeriod,
    mode: str,
    filters: FilterSpec,
    controls: Mapping[str, object],
) -> None:
    if st.session_state.get("agent_collapsed", False):
        with st.container(key="agent_panel_collapsed"):
            st.button(
                ":material/chevron_left:",
                key="agent_expand",
                help="Open the investigation agent",
                type="tertiary",
                on_click=_toggle_collapsed,
            )
            st.markdown(
                "<div class='agent-rail-label'>Investigation agent</div>",
                unsafe_allow_html=True,
            )
        return

    with st.container(key="agent_panel"):
        title, settings = st.columns([0.87, 0.13], vertical_alignment="center")
        title.markdown("#### Investigation agent")
        models = (LIVE_MODEL, DEMO_MODEL)
        saved = st.session_state.get("agent_model_saved", LIVE_MODEL)
        with settings.popover(":material/tune:", help="Settings", type="tertiary"):
            model_choice = st.radio(
                "Model",
                models,
                index=models.index(saved),
                help="The replay runs a fixed set of tool calls and ignores the question wording.",
            )
        st.session_state["agent_model_saved"] = model_choice
        st.button(
            ":material/chevron_right:",
            key="agent_collapse",
            help="Collapse",
            type="tertiary",
            on_click=_toggle_collapsed,
        )

        revenue_basis, basis_note = page_revenue_basis(controls)
        context = build_context(page, period, mode, filters, revenue_basis)
        caption = context_caption(context, basis_note)

        thread_area = st.container(key="agent_thread")
        question = st.chat_input("Ask about what you see on this page", key="agent_question")
        with thread_area:
            if question and question.strip():
                _ask(question.strip(), path, context, caption, model_choice)
            entries = st.session_state.get("agent_thread", [])
            if not entries:
                st.caption("Ask a question about the numbers you see on this page.")
            for position in reversed(range(len(entries))):
                asked, result, asked_caption = entries[position]
                with st.container():
                    with st.chat_message("user"):
                        st.markdown(_plain(asked))
                        st.caption(asked_caption)
                    with st.chat_message("assistant"):
                        _render_result(result, position)


def render_agent_panel(
    path: str | Path,
    page: str,
    period: DatePeriod,
    mode: str,
    filters: FilterSpec,
    controls: Mapping[str, object],
) -> None:
    """Render the agent chat panel for the current page; it collapses to a narrow rail."""
    _panel(path, page, period, mode, filters, controls)

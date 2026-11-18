"""Read-only investigation agent dock: a floating button that opens a right-side chat drawer.

The dock reads the page's global filters and revenue basis and never changes any dashboard control.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.filters import comparison_period
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

# The thread's scroll box is a column-reverse flex container, so a short thread sits at the
# bottom above the input and a long one stays scrolled to the newest message.
_DOCK_CSS = """
<style>
.stMain div[data-testid="stVerticalBlock"] > div:has(> .st-key-agent_launcher) {
  position:fixed; right:1.5rem; bottom:1.5rem; z-index:1100; width:auto;
}
.st-key-agent_launcher button {
  border-radius:999px; padding:.5rem 1.2rem; box-shadow:0 6px 18px rgba(24,39,75,.24);
}
.stMain div[data-testid="stVerticalBlock"] > div:has(> .st-key-agent_drawer) {
  position:fixed; top:var(--topbar-height); right:0; bottom:0; z-index:1090;
  width:min(440px,100vw);
}
.st-key-agent_drawer {
  height:100%; box-sizing:border-box; padding:.7rem 1rem .9rem; overflow:hidden;
  background:var(--white); border-left:1px solid var(--line);
  box-shadow:-8px 0 24px rgba(24,39,75,.12);
}
.st-key-agent_drawer { display:flex; flex-direction:column; gap:.45rem; flex-wrap:nowrap; }
.st-key-agent_drawer > * { flex:0 0 auto; }
.st-key-agent_drawer > div:has(> .st-key-agent_thread) {
  flex:1 1 0; min-height:0; overflow-y:auto; display:flex; flex-direction:column-reverse;
}
.st-key-agent_thread { flex:0 0 auto; }
.st-key-agent_drawer button[kind="tertiary"] { padding:.1rem .35rem; min-height:0; }
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


def evidence_frames(result: InvestigationResult) -> list[tuple[str, pd.DataFrame]]:
    frames = []
    for record in result.evidence:
        payload = record.as_dict()
        title = f"{record.evidence_id}: {record.tool_name}"
        if record.tool_name == "revenue_summary":
            current, comparison = payload["current"], payload["comparison"] or {}
            frame = pd.DataFrame(
                {
                    "Measure": list(current),
                    "Current": list(current.values()),
                    "Comparison": [comparison.get(key) for key in current],
                }
            )
        elif record.tool_name == "revenue_decomposition":
            frame = pd.DataFrame(payload["drivers"])[
                ["driver", "comparison", "current", "contribution"]
            ]
        else:
            title += f" ({payload['dimension']})"
            frame = pd.DataFrame(payload["segments"])[
                ["segment", "comparison", "current", "absolute_delta"]
            ]
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


def _render_result(result: InvestigationResult, position: int) -> None:
    if result.status == "clarification":
        st.info(_plain(result.clarification.question))
    elif result.status == "refusal":
        st.warning(_plain(result.refusal))
    elif result.status == "definition":
        for definition in result.definitions:
            st.markdown(_plain(definition.text))
            st.caption(f"Source: {definition.source}")
    elif result.status == "failure":
        st.error(
            f"The investigation stopped without a report ({result.stop_reason}). "
            "No unverified answer is shown."
        )
        for issue in result.issues:
            st.caption(_plain(f"{issue.code}: {issue.message}"))
    else:
        for row in claim_rows(result):
            st.markdown(f"**{row['Type']}.** {_plain(row['Statement'])}")
            if row["Evidence"]:
                st.caption(f"Evidence {row['Evidence']}")
        if result.stop_reason != "supported_conclusion":
            st.caption(f"Stopped early: {result.stop_reason.replace('_', ' ')}.")
    provenance = (
        "Definitions are quoted by code from the Data Guide; the model only chose which ones."
        if result.status == "definition"
        else "Facts are rendered by code from evidence; only hypotheses and unknowns are model text."
    )
    st.caption(f"Model: {result.model or 'none'}. Stop reason: {result.stop_reason}. {provenance}")
    if result.evidence:
        with st.expander(f"Evidence ({len(result.evidence)} records)"):
            for title, frame in evidence_frames(result):
                st.markdown(f"**{title}**")
                st.dataframe(frame, hide_index=True, width="stretch")
    with st.expander("Investigation trace"):
        st.dataframe(trace_frame(result), hide_index=True, width="stretch")
        st.download_button(
            "Download trace (JSON)",
            trace_to_json(result),
            file_name="investigation_trace.json",
            mime="application/json",
            key=f"agent_trace_download_{position}",
        )


def _toggle_drawer() -> None:
    st.session_state["agent_open"] = not st.session_state.get("agent_open", False)


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
def _dock(
    path: str | Path,
    page: str,
    period: DatePeriod,
    mode: str,
    filters: FilterSpec,
    controls: Mapping[str, object],
) -> None:
    st.markdown(_DOCK_CSS, unsafe_allow_html=True)
    if not st.session_state.get("agent_open", False):
        with st.container(key="agent_launcher"):
            st.button(
                "Ask the agent", key="agent_toggle", type="primary", on_click=_toggle_drawer
            )
        return

    with st.container(key="agent_drawer"):
        title, settings, close = st.columns([0.74, 0.13, 0.13], vertical_alignment="center")
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
        close.button(
            ":material/close:",
            key="agent_close",
            help="Close",
            type="tertiary",
            on_click=_toggle_drawer,
        )

        revenue_basis, basis_note = page_revenue_basis(controls)
        context = build_context(page, period, mode, filters, revenue_basis)
        caption = context_caption(context, basis_note)
        st.caption(f"Reading: {caption}")

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


def render_agent_dock(
    path: str | Path,
    page: str,
    period: DatePeriod,
    mode: str,
    filters: FilterSpec,
    controls: Mapping[str, object],
) -> None:
    """Render the floating agent button and its drawer on the current page."""
    _dock(path, page, period, mode, filters, controls)

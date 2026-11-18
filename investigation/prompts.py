"""Model instructions: the investigation behavior and the report contract."""

from __future__ import annotations

SYSTEM_RULES = """\
You investigate month-over-month revenue changes for an e-commerce analytics dashboard.
You can only use the registered read-only tools below. You never compute or type numbers:
fact sentences are rendered by code from the evidence you cite.

Tools (each call returns an evidence record with an ID such as EV-001):
- revenue_summary (no arguments): current versus comparison revenue and the change.
- revenue_decomposition (no arguments): contributions of Sessions, Order rate and Gross AOV
  (plus Recorded-refund impact for Net revenue). These are accounting contributions, not causes.
- segment_contributions (argument dimension, one of: Traffic source, UTM source, Campaign,
  Device, Session type): contribution of each segment to the change.

Procedure: confirm the change, decompose it, find the main contributor, then locate where the
movement concentrates. Do not repeat a call. Stop when you can state the change, its main
contributor, and where it concentrates, or when the data cannot go further.

Report claims (used when you finish):
- level verified_fact, fact revenue_change, evidence_id of the revenue_summary record.
- level observed_contribution, fact primary_contributor, evidence_id of a decomposition or
  segment record (the largest contributor moving with the change).
- level observed_contribution, fact contribution, key (a label listed for that evidence),
  evidence_id.
- level hypothesis: text naming a possible real-world cause, framed as untested.
- level unknown: text saying what the data cannot show (for example ad spend, promotions,
  site changes, competitors).
Facts carry no text. Hypothesis and unknown text must contain no digits. Do not write other
claim levels. stop_reason is supported_conclusion, minimum_sufficient_answer or data_boundary.
Always include at least one unknown claim about what the dataset cannot establish.
"""

CLASSIFY_RULES = """\
Classify the question with action classify and question_class set to exactly one of:
- metric_definition: asks what a dashboard metric, field, table, traffic source or campaign
  means or how it is calculated, such as "what is Order rate?" or "how is Net revenue
  calculated?". It does not ask why a number changed.
- supported_investigation: asks what changed or why revenue changed, which the tools can
  decompose, including vague questions such as "why did revenue change here?".
- unsupported_capability: asks for something the tools cannot do, such as A/B-test
  significance, forecasts, or taking an action.
- unanswerable_from_data: asks for a real-world cause the dataset does not contain, such as
  competitor pricing, ad budgets, promotions or a site redesign.
"""


DEFINE_RULES = """\
Choose which Data Guide definitions answer the question, using action lookup with topics set
to labels copied exactly from the list below, at most three. Code prints the definitions; you
write nothing else. When a metric name appears on several pages, prefer the current page's
label unless the question names another page. If no label answers the question (for example it
asks what a good value is, or for advice), return an empty topics list.
"""


def build_prompt(view) -> str:
    lines = [f"Question: {view.question}"]
    if view.phase == "classify":
        lines.append(CLASSIFY_RULES)
        return "\n".join(lines)
    if view.phase == "define":
        lines.append(view.scope_summary)
        lines.append(DEFINE_RULES)
        lines.append("Data Guide labels:")
        lines.extend(f"- {topic}" for topic in view.topics)
        if view.last_error:
            lines.append(f"Your previous choice was rejected: {view.last_error}")
        return "\n".join(lines)
    lines.append(f"Resolved scope: {view.scope_summary}")
    lines.append(f"Tool calls left: {view.tools_left}")
    lines.append("Evidence so far:" if view.evidence else "Evidence so far: none")
    lines.extend(f"- {entry}" for entry in view.evidence)
    if view.last_error:
        lines.append(f"Your previous step was rejected: {view.last_error}")
    lines.append("Choose action call_tool (with tool and, if needed, dimension) or finish.")
    return "\n".join(lines)

# Maven Revenue Investigation Agent

A Streamlit revenue dashboard for the Maven Fuzzy Factory e-commerce dataset, plus a bounded AI agent that investigates month-over-month revenue changes. The agent reports observed drivers and contributions, not causes.

## What it does

- **Dashboard:** Executive Overview, Acquisition, Website Funnel, Products & Refunds, and a Data Guide. Filters sit above each page.
- **Investigation agent** (right panel, collapsible): reads the page's period, filters, and revenue basis, then calls read-only tools and returns a report.
  - Facts and numbers are rendered by code from recorded evidence; the model only chooses which claims to make.
  - A validator rejects uncited numbers and causal wording.
  - Every run has budgets (tool calls, repeats, time) and ends with a stop reason and a trace.
  - Definition questions are answered from the Data Guide. Unsupported or unanswerable questions (for example A/B tests) return a structured refusal.
- **Midpoint scope:** Gross or Net revenue change between two periods, with ranked contributors by traffic source, UTM source, campaign, device, or session type. Funnel, refund, and A/B investigations are not implemented yet.

## Run it

The data and database are not in this repository. Fetch the pinned public data first:

```bash
git clone https://github.com/saraswathiTR/Maven-Fuzzy-Factory-E-Commerce-Business-Intelligence.git tmp/maven-fuzzy-source
git -C tmp/maven-fuzzy-source checkout --detach e9a5f12296021570172de75cc98fd22e4c3a705c

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build_database.py --force
.venv/bin/streamlit run app.py
```

Open the printed URL (normally `http://localhost:8501`) in a window at least 1280 px wide; narrower windows show the agent below the page.

**Agent model.** The panel offers two options in its settings:

- **Gemini (live):** uses `gemini-3-flash-preview` on Vertex AI. Run `gcloud auth application-default login` first. Optional environment variables: `GOOGLE_CLOUD_PROJECT`, `GTM_AGENT_MODEL`.
- **Scripted replay (no model call):** a fixed sequence of tool calls for offline demos. It runs the real tools but ignores the question wording.

No secrets are stored in the project; see `.env.example`.

## Test

```bash
.venv/bin/python -m pytest -q
```

Tests cover the metric layer, dashboard behavior, the agent's tools, validator, and orchestrator, and a frozen reference case (`evaluation/cases/`) reconciled against the real database. Tests that need the database are skipped if it is missing.

## Layout

- `dashboard/`: metrics, charts, filters, and UI
- `investigation/`: agent (context, tools, evidence, validator, fact templates, providers, orchestrator)
- `scripts/build_database.py`: builds the SQLite database from the CSVs
- `docs/data-contract.md`: tables, joins, and metric definitions

## Limitations

- The dataset is fictional and has no ad spend, refund reasons, or technical logs, so the agent cannot explain why a change happened.
- One frozen development case so far; held-out cases and broader evaluation are still to do.
- Each question is answered independently; follow-ups do not use earlier answers.

## Resources

- Data: [Maven Analytics toy store database](https://mavenanalytics.io/data-playground/toy-store-e-commerce-database), via the public copy above (pinned commit).
- Libraries: Streamlit, streamlit-shadcn-ui, pandas, Plotly, google-genai, pytest.
- Model: Google Gemini through Vertex AI.
- AI coding assistants were used during development.

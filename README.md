# Maven Revenue Intelligence

A local Streamlit dashboard for the Maven Fuzzy Factory e-commerce dataset. The first release is intentionally dashboard-only: it uses the six real local tables and includes no agent, chat panel, or mock business values.

## Reproduce from a clean checkout

The source CSVs and generated SQLite database are intentionally excluded from the project repository. Fetch the
validated public data revision first:

```bash
git clone \
  https://github.com/saraswathiTR/Maven-Fuzzy-Factory-E-Commerce-Business-Intelligence.git \
  tmp/maven-fuzzy-source
git -C tmp/maven-fuzzy-source checkout --detach e9a5f12296021570172de75cc98fd22e4c3a705c
```

Then create the local environment, build the database atomically, and start Streamlit:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build_database.py --force
.venv/bin/streamlit run app.py
```

Streamlit prints the local URL (normally `http://localhost:8501`). The app reads `tmp/maven-analysis/maven_fuzzy.db` in SQLite read-only mode.

To rebuild an existing local database from the same CSVs:

```bash
.venv/bin/python scripts/build_database.py --force
```

The builder checks for all six files, loads a temporary database, creates analytical indexes, and only then replaces
the target. Restart Streamlit after a manual rebuild so the in-process query cache is cleared before the dashboard is
used again. The source revision above is the version used for the documented table counts, metric audit, and tests.

## Repository boundary

Files intended for the clean project repository:

- `app.py`, `dashboard/`, and `scripts/` — application and deterministic database builder;
- `tests/` — offline validation;
- `docs/data-contract.md` and `README.md` — public data definitions and setup documentation;
- `project_proposal.md`, `proposal.pdf`, and `requirements.txt` — course and environment records;
- `.gitignore`, `.env.example`, and `.streamlit/config.toml` — safe local setup templates.

The following stay local and are ignored: `.venv/`, `tmp/` source data and SQLite output, Python/test caches, real
`.env` or Streamlit secrets, generated `build/` and `output/` artifacts, and coding-agent collaboration files such as
`.agents/`, `AGENTS.md`, `.superpowers/`, internal execution plans, and decision logs. These files remain available
locally but are not part of the course repository. The dashboard currently needs no environment variables or API
keys; `.env.example` is intentionally secret-free. Future reports and evaluated cases should be added explicitly
after review rather than through a broad `git add .`.

## Dashboard structure

The top application bar contains four analysis views plus a reference page:

1. **Executive Overview** — revenue, orders, sessions, conversion, AOV, margin, refunds, trends, and revenue drivers.
2. **Acquisition** — traffic quality by source, campaign, device, ad content, referrer type, and landing page.
3. **Website Funnel** — ordered reach and drop-off from landing through thank-you, with cohort comparisons.
4. **Products & Refunds** — item revenue, units, margin, add-on behavior, basket size, refunds, and trends.
5. **Data Guide** — source schema, logical ERD, example rows, derived dimensions, and metric definitions.

Global filters stay in the left rail when pages change. Each page adds its own controls below them. The reporting window uses safe presets—latest 12, 6, or 3 months, all history, or custom—rather than a month slider. The date window is the upstream filter: traffic, campaign, device, landing-page, product-page, and product options only show values that exist in the selected period and match earlier selections. If a date or upstream-filter change makes a selected value unavailable, the dashboard removes it and shows a brief explanation instead of leaving the report in an accidental empty state.

All filter inputs use one shadcn component system, with consistent labels, borders, height, spacing, and focus behavior. Multi-value controls are searchable; an empty explicit selection means **All**, so a filter group cannot accidentally zero the report. Values inside one group use OR logic, while different filter groups use AND logic. The filter workspace stays visible in the desktop left rail and stacks above the report on narrow screens.

### Visualization standard

This dashboard prioritizes comparison accuracy over decorative chart variety. Internal GTM views use aligned position, length, and time-series trends as their primary visual encodings. Bubble charts, pie charts, and donut charts are excluded because area and angle make close business values harder to compare. Percentages, currency, and decimal metrics display two decimal places; count metrics remain whole numbers.

## Data semantics

The source schema does not contain friendly channel or referrer fields, so the UI derives them transparently from real columns:

- **Paid Search:** `utm_source` is `gsearch` or `bsearch`.
- **Paid Social:** `utm_source` is `socialbook`.
- **Organic Search:** `utm_source` is NULL and `http_referer` is present.
- **Direct:** both `utm_source` and `http_referer` are NULL.
- **Referrer type:** Paid, Organic, or Direct from the same real fields.
- **Untracked campaign/ad content:** the public CSV copy uses the text sentinel `NULL`; the import and query layers normalize it to SQL NULL semantics.
- **Landing page:** the first `website_pageviews` row in each session, ordered by `website_pageview_id`.
- **Original/Optimized funnel:** `/billing` and `/billing-2`, respectively.

Campaign choices depend on source selection: Paid Search exposes Brand/Nonbrand, Paid Social exposes Desktop targeted/Pilot, and Organic/Direct expose Untracked. Incompatible values are excluded.

## Metric grain and refund basis

- Session counts come from `website_sessions`.
- Order revenue, order count, AOV, and order COGS come from `orders` before any other fact table is joined.
- Product revenue, units, role, and product COGS come from `order_items`.
- Refund events and dollars come from `order_item_refunds`.
- Funnel reach first collapses pageviews to one row per session.

This separation prevents order amounts from being multiplied by pageviews or line items.

On the Executive page, **Net** revenue subtracts refund events recorded in the selected period from orders recorded in that period; refund events inherit source/device attribution from the original order session. On Products & Refunds:

- **Purchase date** creates a sold-item cohort and counts whether those items were later refunded.
- **Refund date** counts refund events by their own timestamps. Sales and the refund-rate denominator remain purchases in the same displayed calendar period, and the UI states this explicitly.

The dataset has no ad spend, refund reasons, customer feedback, fulfillment data, or technical logs. Revenue per session is therefore not labeled ROAS, and the dashboard does not claim why an observed change occurred.

## Verification

Run the automated suite and import check:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile app.py dashboard/*.py scripts/*.py
```

The tests cover month/period boundaries, date-aware cascading options and invalid-selection recovery, dependent campaign options, AND/OR filter semantics, popover selection persistence, page-navigation state, palette contrast, chart order/density, missing schema errors, revenue join-duplication protection, acquisition grouping, ordered funnel stages, product/refund date bases, empty chart states, and CSV-to-SQLite rebuilding.

## Git and GitHub ownership

The student performs every commit and remote GitHub action. Coding agents may prepare files, checks, and commands but
must not initialize the remote, commit, push, pull, or open a pull request. After reviewing the local files, the
student can run:

```bash
git init
git add .
git status --short
git commit -m "Prepare Maven revenue investigation midpoint"
git branch -M main
git remote add origin <YOUR_REPOSITORY_URL>
git push -u origin main
```

For later updates, the student runs `git pull --ff-only` and `git push` personally. Do not add `Co-Authored-By` or
generated-by attribution.

## Real data coverage

| Table | Rows | Date range / note |
|---|---:|---|
| `website_sessions` | 472,871 | 2012-03-19 to 2015-03-19 |
| `website_pageviews` | 1,188,124 | 2012-03-19 to 2015-03-19 |
| `orders` | 32,313 | 2012-03-19 to 2015-03-19 |
| `order_items` | 40,025 | 2012-03-19 to 2015-03-19 |
| `order_item_refunds` | 1,731 | extends to 2015-04-01 |
| `products` | 4 | product catalog |

The final session month is partial; the page context shows the exact last available date.

## Current limitations

- The shared month slider follows session coverage and ends at March 2015. Two refund events on April 1, 2015 (totaling $105.98) remain in the database but are outside the selectable dashboard range.
- Source categories and referrer types are transparent business mappings over the available UTM/referrer fields; the source data has no ad spend, refund reason, or causal diagnostic fields.
- The UI is optimized for desktop and stacks on narrow screens. Essential theme text pairs are automatically checked against WCAG AA contrast; this is not a substitute for a full independent accessibility audit.

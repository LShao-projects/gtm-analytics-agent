from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.data import DatabaseMetadata, query_df
from dashboard.display import dataframe_column_config
from dashboard.filters import TRAFFIC_SOURCE_SQL
from dashboard.labels import AD_CONTENT_LABELS, PAGE_URL_LABELS


GUIDE_SECTIONS = (
    "Raw Data Dictionary",
    "Derived Dimensions",
    "Metrics & Charts",
)


RELATIONSHIP_ROWS = (
    (
        "website_sessions",
        "1 → many",
        "website_pageviews",
        "A session records many page events in viewing order.",
    ),
    (
        "website_sessions",
        "1 → 0 or 1",
        "orders",
        "A session may end without a purchase or create one order.",
    ),
    (
        "orders",
        "1 → many",
        "order_items",
        "An order contains one or more sold items; current orders contain one or two.",
    ),
    (
        "order_items",
        "many → 1",
        "products",
        "Each sold item references one catalog product.",
    ),
    (
        "order_items",
        "1 → 0 or 1",
        "order_item_refunds",
        "A sold item may have no refund or one refund event in the current data.",
    ),
)


TABLE_SPECS = {
    "website_sessions": {
        "grain": "One website visit (session)",
        "primary_key": "website_session_id",
        "description": "Visit timing, user identity, acquisition tags, device, and new/repeat status.",
        "fields": (
            ("website_session_id", "INTEGER PK", "Unique session key; joins to pageviews and orders."),
            ("created_at", "TEXT", "Session start timestamp."),
            ("user_id", "INTEGER", "Logical user identifier; one user may have multiple sessions."),
            ("is_repeat_session", "INTEGER", "0 = New session; 1 = Repeat session."),
            ("utm_source", "TEXT", "Tracked traffic origin such as gsearch, bsearch, or socialbook."),
            ("utm_campaign", "TEXT", "Tracked marketing campaign name."),
            ("utm_content", "TEXT", "Tracked ad or content variant."),
            ("device_type", "TEXT", "Desktop or mobile."),
            ("http_referer", "TEXT", "Previous-site URL reported by the browser."),
        ),
    },
    "website_pageviews": {
        "grain": "One pageview event",
        "primary_key": "website_pageview_id",
        "description": "Ordered pages viewed during a session; used for landing pages and funnel stages.",
        "fields": (
            ("website_pageview_id", "INTEGER PK", "Unique event key; increasing IDs establish page order."),
            ("created_at", "TEXT", "Pageview timestamp."),
            ("website_session_id", "INTEGER", "Parent session key."),
            ("pageview_url", "TEXT", "URL path that was viewed."),
        ),
    },
    "orders": {
        "grain": "One completed order",
        "primary_key": "order_id",
        "description": "Order-level revenue, COGS, item count, and attribution to a website session.",
        "fields": (
            ("order_id", "INTEGER PK", "Unique order key."),
            ("created_at", "TEXT", "Order timestamp."),
            ("website_session_id", "INTEGER", "Session attributed to the order."),
            ("user_id", "INTEGER", "Buyer identifier; reconciles with the joined session user."),
            ("primary_product_id", "INTEGER", "Product designated as the order's primary item."),
            ("items_purchased", "INTEGER", "Number of item rows in the order: one or two in this dataset."),
            ("price_usd", "REAL", "Total pre-refund order revenue."),
            ("cogs_usd", "REAL", "Total cost of goods sold for the order."),
        ),
    },
    "order_items": {
        "grain": "One product item within an order",
        "primary_key": "order_item_id",
        "description": "Item-level product, price, COGS, and Primary/Add-on role.",
        "fields": (
            ("order_item_id", "INTEGER PK", "Unique item key; joins to refunds."),
            ("created_at", "TEXT", "Item purchase timestamp; matches the parent order in current data."),
            ("order_id", "INTEGER", "Parent order key."),
            ("product_id", "INTEGER", "Product key."),
            ("is_primary_item", "INTEGER", "1 = Primary item; 0 = Add-on item."),
            ("price_usd", "REAL", "Pre-refund item revenue."),
            ("cogs_usd", "REAL", "Cost of goods sold for the item."),
        ),
    },
    "order_item_refunds": {
        "grain": "One item-level refund event",
        "primary_key": "order_item_refund_id",
        "description": "Refund timing and amount for a sold order item.",
        "fields": (
            ("order_item_refund_id", "INTEGER PK", "Unique refund-event key."),
            ("created_at", "TEXT", "Refund-event timestamp."),
            ("order_item_id", "INTEGER", "Refunded item key."),
            ("order_id", "INTEGER", "Denormalized parent order key."),
            ("refund_amount_usd", "REAL", "Refunded amount."),
        ),
    },
    "products": {
        "grain": "One catalog product",
        "primary_key": "product_id",
        "description": "Four-product catalog used to label sold items.",
        "fields": (
            ("product_id", "INTEGER PK", "Unique product key."),
            ("created_at", "TEXT", "Product launch timestamp."),
            ("product_name", "TEXT", "Product display name."),
        ),
    },
}


TRAFFIC_SOURCE_RULES = {
    "Paid Search": "utm_source is gsearch or bsearch.",
    "Paid Social": "utm_source is socialbook.",
    "Organic Search": "utm_source is missing and http_referer is present.",
    "Direct": "Both utm_source and http_referer are missing.",
}


CAMPAIGN_DEFINITIONS = {
    "Brand": "Paid-search ads triggered by searches for the company, brand, or product names.",
    "Nonbrand": "Paid-search ads triggered by generic product searches such as teddy bear or stuffed animal.",
    "Pilot": "A Socialbook trial campaign. The data does not state the exact hypothesis being tested.",
    "Desktop targeted": "A Socialbook campaign delivered to desktop users; every matching session is desktop in this dataset.",
    "Untracked": "The session has no UTM campaign tag, so no paid campaign name is available.",
}


MASKED_AD_CONTEXT = {
    "g_ad_1": "Gsearch · Nonbrand campaign",
    "g_ad_2": "Gsearch · Brand campaign",
    "b_ad_1": "Bsearch · Nonbrand campaign",
    "b_ad_2": "Bsearch · Brand campaign",
    "social_ad_1": "Socialbook · Pilot campaign",
    "social_ad_2": "Socialbook · Desktop targeted campaign",
}


METRIC_GUIDES = {
    "Executive Overview": (
        ("Revenue", "Gross: SUM(orders.price_usd). Net: gross revenue minus refund events in the selected period.", "Order / refund event", "The Channel contribution chart remains gross even when Net is selected."),
        ("Orders", "Count of orders placed in the selected period.", "Order", "Order time owns the period."),
        ("Sessions", "Count of website sessions started in the selected period.", "Session", "Counts visits, not unique users."),
        ("Conversion rate", "Orders ÷ Sessions.", "Order and session aggregated separately", "An event-period rate, not a controlled experiment."),
        ("Average order value", "Gross order revenue ÷ Orders.", "Order", "Always uses gross order revenue."),
        ("Gross margin", "Gross order revenue − order COGS; Net basis also subtracts refund amount.", "Order / refund event", "Does not include advertising or operating expenses."),
        ("Refund rate", "Refund events in the period ÷ items sold in the period.", "Refund event / item", "The numerator and denominator need not represent the same purchase cohort."),
        ("Net revenue", "Gross order revenue − refund events recorded in the selected period.", "Order / refund event", "Mixes order-event and refund-event timing."),
        ("Revenue drivers", "Revenue = Sessions × Conversion rate × Average order value.", "Mixed, separately aggregated", "An accounting identity, not a causal claim."),
        ("Channel contribution", "Gross order revenue grouped by derived Traffic source.", "Order attributed to session", "Shows current-period concentration, not contribution to period-over-period change."),
        ("Driver detail", "Session and order measures by the same derived Traffic-source categories.", "Session / order", "Each grain is aggregated before display to avoid duplication."),
    ),
    "Acquisition": (
        ("Sessions", "Count of sessions in the selected acquisition segment.", "Session", "Segment attributes come from website_sessions."),
        ("Orders", "Count of orders linked to selected sessions.", "Order attributed to session", "One purchasing session has at most one order in current data."),
        ("Conversion rate", "Linked orders ÷ selected sessions.", "Order / session", "Descriptive segment comparison."),
        ("Revenue per session", "Gross revenue from linked orders ÷ selected sessions.", "Order / session", "Not ROAS because advertising spend is unavailable."),
        ("Gross margin per session", "(Gross order revenue − order COGS) ÷ selected sessions.", "Order / session", "Excludes advertising and operating expenses."),
        ("Quality charts", "The selected metric ranked by Traffic source, Campaign, Device, or Landing page.", "Selected dimension", "Ranks current values, not period-over-period contribution."),
    ),
    "Website Funnel": (
        ("Sessions", "Selected-cohort sessions at the Landing stage.", "Session", "The cohort is defined by session start time."),
        ("Orders", "Sessions that reached /thank-you-for-your-order.", "Session pageview path", "This card observes the final pageview; it does not count orders rows directly."),
        ("Conversion rate", "Thank-you-stage sessions ÷ Landing-stage sessions.", "Session", "Descriptive funnel conversion."),
        ("Step conversion", "Current-stage sessions ÷ preceding-stage sessions.", "Session", "Stages must appear in the required order."),
        ("Total conversion", "Current-stage sessions ÷ Landing-stage sessions.", "Session", "Measures reach from the start of the funnel."),
        ("Drop-off", "Preceding-stage sessions − current-stage sessions.", "Session", "Counts observed losses between ordered stages."),
        ("Final conversion by", "Final funnel conversion grouped by the selected dimension.", "Session", "Not a statistical A/B test."),
    ),
    "Products & Refunds": (
        ("Revenue", "SUM(order_items.price_usd) for selected items.", "Order item", "Item grain avoids duplicating multi-item orders."),
        ("Units sold", "Count of selected order-item rows.", "Order item", "Each row represents one sold item in current data."),
        ("Gross margin", "Selected item revenue − selected item COGS.", "Order item", "Not company net profit."),
        ("Refunded amount", "SUM(order_item_refunds.refund_amount_usd).", "Refund event", "Attributed back to the original order and session."),
        ("Refund rate — Purchase date", "Purchase-cohort items later refunded ÷ units in that purchase cohort.", "Order item cohort", "May include refunds recorded after the displayed purchase period."),
        ("Refund rate — Refund date", "Refund events in the period ÷ items purchased in the same calendar period.", "Refund event / item", "The numerator and denominator are different event populations."),
        ("Attachment rate", "Selected-product units sold as Add-ons ÷ selected-product units.", "Order item", "Primary/Add-on is taken from is_primary_item."),
        ("Basket mix", "Orders grouped as Single-item or Multi-item.", "Order", "Uses orders.items_purchased."),
    ),
}


def table_profile(path: str | Path, table: str) -> dict[str, object]:
    if table not in TABLE_SPECS:
        raise ValueError(f"Unsupported guide table: {table}")
    row = query_df(
        path,
        f"SELECT COUNT(*) AS rows, MIN(created_at) AS first_at, MAX(created_at) AS last_at FROM {table}",
    ).iloc[0]
    return {"rows": int(row["rows"]), "first_at": row["first_at"], "last_at": row["last_at"]}


def table_sample(path: str | Path, table: str, limit: int = 5) -> pd.DataFrame:
    if table not in TABLE_SPECS:
        raise ValueError(f"Unsupported guide table: {table}")
    if not 1 <= limit <= 20:
        raise ValueError("Guide sample limit must be between 1 and 20.")
    primary_key = TABLE_SPECS[table]["primary_key"]
    return query_df(path, f"SELECT * FROM {table} ORDER BY {primary_key} LIMIT ?", [limit])


def traffic_source_distribution(path: str | Path) -> pd.DataFrame:
    expression = TRAFFIC_SOURCE_SQL.format(alias="s")
    frame = query_df(
        path,
        f"""
        SELECT {expression} AS traffic_source, COUNT(*) AS sessions
        FROM website_sessions s
        GROUP BY 1
        ORDER BY sessions DESC
        """,
    )
    frame["rule"] = frame["traffic_source"].map(TRAFFIC_SOURCE_RULES).fillna("Source not covered by the current named categories.")
    return frame[["traffic_source", "rule", "sessions"]]


def campaign_distribution(path: str | Path) -> pd.DataFrame:
    counts = query_df(
        path,
        """
        SELECT COALESCE(NULLIF(utm_campaign, 'NULL'), 'Untracked') AS campaign,
               COUNT(*) AS sessions
        FROM website_sessions
        GROUP BY 1
        """,
    ).set_index("campaign")["sessions"].to_dict()
    rows = []
    raw_values = {
        "Brand": "brand",
        "Nonbrand": "nonbrand",
        "Pilot": "pilot",
        "Desktop targeted": "desktop_targeted",
        "Untracked": "Untracked",
    }
    for label, description in CAMPAIGN_DEFINITIONS.items():
        rows.append(
            {
                "campaign": label,
                "raw_value": raw_values[label],
                "description": description,
                "sessions": int(counts.get(raw_values[label], 0)),
            }
        )
    return pd.DataFrame(rows)


def url_inventory(path: str | Path) -> pd.DataFrame:
    return query_df(
        path,
        """
        SELECT pageview_url,
               COUNT(*) AS pageviews,
               COUNT(DISTINCT website_session_id) AS sessions
        FROM website_pageviews
        GROUP BY pageview_url
        ORDER BY pageview_url
        """,
    )


def masked_value_inventory() -> tuple[pd.DataFrame, pd.DataFrame]:
    ad_rows = [
        {
            "raw_value": raw_value,
            "display_label": display_label,
            "known_context": MASKED_AD_CONTEXT[raw_value],
        }
        for raw_value, display_label in AD_CONTENT_LABELS.items()
    ]
    landing_rows = [
        {
            "raw_value": raw_value,
            "display_label": PAGE_URL_LABELS[raw_value],
            "known_context": "Masked landing-page variant; page content is not included in the dataset.",
        }
        for raw_value in ("/home", "/lander-1", "/lander-2", "/lander-3", "/lander-4", "/lander-5")
    ]
    return pd.DataFrame(ad_rows), pd.DataFrame(landing_rows)


def _erd_table(
    x: int,
    y: int,
    width: int,
    name: str,
    fields: tuple[tuple[str, str], ...],
) -> str:
    header_height = 36
    row_height = 25
    height = header_height + row_height * len(fields) + 8
    rows = []
    for index, (key_type, field) in enumerate(fields):
        row_y = header_height + 18 + index * row_height
        key_markup = (
            f"<text class='erd-key' x='12' y='{row_y}'>{escape(key_type)}</text>"
            if key_type
            else ""
        )
        rows.append(
            f"<line class='erd-row-line' x1='0' y1='{header_height + index * row_height}' "
            f"x2='{width}' y2='{header_height + index * row_height}'/>"
            f"{key_markup}"
            f"<text class='erd-field' x='46' y='{row_y}'>{escape(field)}</text>"
        )
    return (
        f"<g class='erd-entity' transform='translate({x} {y})'>"
        f"<rect class='erd-entity-box' width='{width}' height='{height}' rx='10'/>"
        f"<path class='erd-entity-header' d='M10 0 H{width - 10} Q{width} 0 {width} 10 "
        f"V{header_height} H0 V10 Q0 0 10 0 Z'/>"
        f"<text class='erd-title' x='12' y='23'>{escape(name)}</text>"
        f"{''.join(rows)}</g>"
    )


def _render_relationship_map() -> None:
    entities = "".join(
        (
            _erd_table(
                15,
                175,
                205,
                "website_sessions",
                (
                    ("PK", "website_session_id"),
                    ("", "created_at"),
                    ("", "user_id"),
                    ("", "utm_source"),
                    ("", "utm_campaign"),
                    ("", "device_type"),
                ),
            ),
            _erd_table(
                295,
                20,
                210,
                "website_pageviews",
                (
                    ("PK", "website_pageview_id"),
                    ("FK", "website_session_id"),
                    ("", "created_at"),
                    ("", "pageview_url"),
                ),
            ),
            _erd_table(
                295,
                190,
                210,
                "orders",
                (
                    ("PK", "order_id"),
                    ("FK", "website_session_id"),
                    ("", "user_id"),
                    ("", "primary_product_id"),
                    ("", "price_usd"),
                    ("", "cogs_usd"),
                ),
            ),
            _erd_table(
                580,
                20,
                205,
                "products",
                (
                    ("PK", "product_id"),
                    ("", "created_at"),
                    ("", "product_name"),
                ),
            ),
            _erd_table(
                580,
                190,
                205,
                "order_items",
                (
                    ("PK", "order_item_id"),
                    ("FK", "order_id"),
                    ("FK", "product_id"),
                    ("", "is_primary_item"),
                    ("", "price_usd"),
                    ("", "cogs_usd"),
                ),
            ),
            _erd_table(
                570,
                455,
                220,
                "order_item_refunds",
                (
                    ("PK", "order_item_refund_id"),
                    ("FK", "order_item_id"),
                    ("", "order_id"),
                    ("", "refund_amount_usd"),
                    ("", "created_at"),
                ),
            ),
        )
    )
    relationship_description = "; ".join(
        f"{source} {cardinality} {target}: {meaning}"
        for source, cardinality, target, meaning in RELATIONSHIP_ROWS
    )
    st.markdown(
        f"""
        <figure class="erd-wrap">
          <svg class="erd-svg" viewBox="0 0 800 640" role="img" aria-labelledby="erd-title erd-desc">
            <title id="erd-title">Logical entity relationship diagram for the six source tables</title>
            <desc id="erd-desc">{escape(relationship_description)}</desc>
            <g class="erd-links" aria-hidden="true">
              <path d="M220 230 H255 V92 H295"/><text x="228" y="220">1</text><text x="260" y="82">1..7</text>
              <path d="M220 300 H295"/><text x="230" y="290">1</text><text x="260" y="290">0..1</text>
              <path d="M505 300 H580"/><text x="515" y="290">1</text><text x="545" y="290">1..2</text>
              <path d="M682 139 V190"/><text x="692" y="158">1</text><text x="692" y="184">0..*</text>
              <path d="M682 384 V455"/><text x="692" y="407">1</text><text x="692" y="449">0..1</text>
            </g>
            {entities}
          </svg>
          <figcaption class="erd-legend">
            <span><b>PK</b> Primary key</span><span><b>FK</b> Logical join key</span>
            <span>Connector labels show records at each endpoint.</span>
          </figcaption>
        </figure>
        """,
        unsafe_allow_html=True,
    )


def _render_guide_dataframe(frame: pd.DataFrame) -> None:
    st.dataframe(
        frame,
        column_config=dataframe_column_config(frame),
        width="stretch",
        hide_index=True,
    )


def _render_raw_data(path: str | Path, metadata: DatabaseMetadata) -> None:
    st.markdown("### What is in the source database?")
    st.caption("Six read-only source tables power every dashboard calculation. Samples below come from the active local database.")

    columns = st.columns(3)
    columns[0].metric("Source tables", metadata.table_count)
    session_start = metadata.session_min[:10] if metadata.session_min else "Unavailable"
    session_end = metadata.session_max[:10] if metadata.session_max else "Unavailable"
    columns[1].metric("Session coverage", f"{session_start} to {session_end}")
    columns[2].metric("Refund data through", metadata.refund_max[:10] if metadata.refund_max else "Unavailable")

    st.markdown("#### Relationship map")
    st.caption("Logical ERD for the five core analysis joins. Cardinality labels show the observed relationship in this dataset.")
    _render_relationship_map()

    for table, spec in TABLE_SPECS.items():
        profile = table_profile(path, table)
        with st.expander(f"{table} — {spec['grain']}", expanded=False):
            st.markdown(spec["description"])
            st.markdown(
                f"**Rows:** {profile['rows']:,}  ·  **Primary key:** `{spec['primary_key']}`  ·  "
                f"**Time range:** {profile['first_at']} to {profile['last_at']}"
            )
            fields = pd.DataFrame(spec["fields"], columns=["Field", "Type", "Business meaning"])
            with st.container(key=f"guide_fields_{table}"):
                st.markdown("##### Fields")
                _render_guide_dataframe(fields)
            sample = table_sample(path, table)
            with st.container(key=f"guide_sample_{table}"):
                st.markdown("##### First five rows")
                _render_guide_dataframe(sample)

    st.markdown("#### All unique page URLs")
    st.caption("The source contains 16 URL values. Business funnel stages group alternative URLs that serve the same role.")
    _render_guide_dataframe(url_inventory(path))

    st.markdown("#### Data-quality boundaries")
    st.markdown(
        """
- The source declares primary keys but no foreign-key or NOT NULL constraints; logical integrity is checked separately.
- Text `NULL` and SQL `NULL` are normalized as missing acquisition values.
- March 2015 session data is incomplete, while refund events extend into April 2015.
- Current order totals reconcile to item counts, item revenue, and item COGS, but application code should still preserve grain.
- The dataset has no advertising spend, impressions, clicks, experiment assignments, or general operating expenses.
"""
    )


def _render_derived_dimensions(path: str | Path) -> None:
    st.markdown("### Which dashboard fields are derived?")
    st.caption("These labels do not exist as raw database columns. The dashboard calculates them with deterministic rules.")

    st.markdown("#### Traffic Source")
    traffic = traffic_source_distribution(path).rename(
        columns={"traffic_source": "Traffic source", "rule": "Rule", "sessions": "Sessions"}
    )
    _render_guide_dataframe(traffic)
    st.caption("Only the four categories present in the active dataset are shown.")

    st.markdown("#### Campaign")
    campaigns = campaign_distribution(path).rename(
        columns={"campaign": "Campaign", "raw_value": "Raw value", "description": "Meaning", "sessions": "Sessions"}
    )
    _render_guide_dataframe(campaigns)

    with st.expander("Masked ad-content and landing-page labels", expanded=False):
        st.markdown(
            "The source values are anonymized identifiers. The dashboard uses readable display labels but retains "
            "the raw value in parentheses where useful. The dataset does not contain the original ad copy, image, "
            "landing-page text, or page design."
        )
        ads, landings = masked_value_inventory()
        st.markdown("##### Ad content")
        _render_guide_dataframe(
            ads.rename(
                columns={"raw_value": "Raw value", "display_label": "Display label", "known_context": "What is known"}
            )
        )
        st.markdown("##### Landing pages")
        _render_guide_dataframe(
            landings.rename(
                columns={"raw_value": "Raw value", "display_label": "Display label", "known_context": "What is known"}
            )
        )

    with st.expander("Ad content, Session type, and Referrer type", expanded=False):
        st.markdown(
            """
- **Ad content:** the raw `utm_content` ad variant; missing values display as Untracked.
- **Session type:** New when `is_repeat_session = 0`; Repeat when `is_repeat_session = 1`.
- **Referrer type:** Paid when a UTM source exists; Organic when UTM is missing but a referrer exists; otherwise Direct.
"""
        )

    with st.expander("Landing pages and ordered funnel stages", expanded=False):
        st.markdown(
            """
**Landing page** is the first pageview in a session, ordered by `website_pageview_id`.

| Funnel stage | Source URL rule |
| --- | --- |
| Landing | The session's first pageview: `/home` or `/lander-1` through `/lander-5` in current data |
| Products | `/products` |
| Product detail | Any of the four product-detail URLs |
| Cart | `/cart` |
| Shipping | `/shipping` |
| Billing | `/billing`, `/billing-2`, or the selected Funnel version |
| Thank-you | `/thank-you-for-your-order` |

The 16 raw URLs become seven business stages because landing, product-detail, and billing URLs are alternatives at
the same point in the journey. Page-version comparisons are descriptive unless a valid experiment cohort is defined.
"""
        )

    with st.expander("Product roles, basket size, and date rules", expanded=False):
        st.markdown(
            """
- **Primary/Add-on:** taken directly from `order_items.is_primary_item`; the dashboard does not infer the role.
- **Single-item/Multi-item:** derived from `orders.items_purchased`.
- **Reporting intervals:** `start <= timestamp < first day after the selected end month`.
- **Previous period:** the immediately preceding calendar window of equal length.
- **Previous year:** the same calendar window one year earlier.
- Sessions, orders, sold items, and refunds retain their own event timestamps; the active metric determines the date owner.
"""
        )


def _render_metrics_and_charts() -> None:
    st.markdown("### How are the displayed metrics and charts calculated?")
    st.caption("Each table states the formula, aggregation grain, and the caveat needed to interpret the result.")
    for page, rows in METRIC_GUIDES.items():
        with st.expander(page, expanded=page == "Executive Overview"):
            frame = pd.DataFrame(rows, columns=["Display", "Formula or definition", "Grain", "Interpretation note"])
            _render_guide_dataframe(frame)

    st.markdown("#### Interpretation boundaries")
    st.markdown(
        """
- Current-period segment rankings are not the same as contribution to period-over-period change.
- Observed drivers and associations are descriptive unless the design supports a causal claim.
- Billing and landing-page variants do not by themselves establish a valid A/B test.
- Revenue per session is not ROAS, and gross margin is not company net profit.
"""
    )


def render_data_guide(path: str | Path, metadata: DatabaseMetadata) -> None:
    st.markdown("<h1 class='page-title'>Data Guide</h1>", unsafe_allow_html=True)
    st.markdown(
        "<div class='page-subtitle'>Trace the dashboard from raw tables to derived business rules and displayed metrics.</div>",
        unsafe_allow_html=True,
    )
    section = st.segmented_control(
        "Guide section",
        GUIDE_SECTIONS,
        default=GUIDE_SECTIONS[0],
        key="data_guide_section",
        width="stretch",
    ) or GUIDE_SECTIONS[0]
    if section == "Raw Data Dictionary":
        _render_raw_data(path, metadata)
    elif section == "Derived Dimensions":
        _render_derived_dimensions(path)
    else:
        _render_metrics_and_charts()

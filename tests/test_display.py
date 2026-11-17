import pandas as pd

from dashboard.display import dataframe_column_config, is_currency_column


def test_currency_columns_cover_dashboard_metrics_and_raw_usd_fields():
    assert is_currency_column("revenue")
    assert is_currency_column("gross_margin")
    assert is_currency_column("margin_after_recorded_refunds")
    assert is_currency_column("revenue_per_session")
    assert is_currency_column("price_usd")
    assert is_currency_column("refund_amount_usd")
    assert not is_currency_column("sessions")
    assert not is_currency_column("conversion_rate")


def test_dataframe_config_left_aligns_text_numbers_and_currency():
    frame = pd.DataFrame(
        {
            "segment": ["Paid Search"],
            "sessions": [10],
            "revenue": [125.5],
        }
    )

    config = dataframe_column_config(
        frame,
        {"segment": "Segment", "sessions": "Sessions", "revenue": "Revenue"},
    )

    assert set(config) == {"Segment", "Sessions", "Revenue"}
    assert all(column["alignment"] == "left" for column in config.values())
    assert config["Revenue"]["type_config"]["format"] == "dollar"

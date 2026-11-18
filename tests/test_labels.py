from dashboard.labels import display_label


def test_masked_ad_content_labels_name_source_without_inventing_creative_content():
    assert display_label("g_ad_1") == "G Search ad 1"
    assert display_label("b_ad_2") == "B Search ad 2"
    assert display_label("social_ad_1") == "Social Book ad 1"


def test_source_labels_use_readable_business_capitalization():
    assert display_label("gsearch") == "G Search"
    assert display_label("bsearch") == "B Search"
    assert display_label("socialbook") == "Social Book"


def test_page_url_labels_keep_raw_landing_variants_out_of_dashboard_copy():
    assert display_label("/home") == "Homepage"
    assert display_label("/lander-3") == "Landing page 3"
    assert display_label("/billing") == "Observed billing path (/billing)"
    assert display_label("/billing-2") == "Observed billing path (/billing-2)"

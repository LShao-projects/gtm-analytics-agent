from dashboard.labels import display_label


def test_masked_ad_content_labels_name_source_without_inventing_creative_content():
    assert display_label("g_ad_1") == "Gsearch ad 1 (masked content ID)"
    assert display_label("b_ad_2") == "Bsearch ad 2 (masked content ID)"
    assert display_label("social_ad_1") == "Socialbook ad 1 (masked content ID)"


def test_page_url_labels_are_readable_and_retain_raw_landing_variant():
    assert display_label("/home") == "Homepage (/home)"
    assert display_label("/lander-3") == "Landing page 3 (/lander-3)"
    assert display_label("/billing") == "Observed billing path (/billing)"
    assert display_label("/billing-2") == "Observed billing path (/billing-2)"

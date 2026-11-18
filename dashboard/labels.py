from __future__ import annotations


AD_CONTENT_LABELS = {
    "g_ad_1": "G Search ad 1",
    "g_ad_2": "G Search ad 2",
    "b_ad_1": "B Search ad 1",
    "b_ad_2": "B Search ad 2",
    "social_ad_1": "Social Book ad 1",
    "social_ad_2": "Social Book ad 2",
}


SOURCE_LABELS = {
    "gsearch": "G Search",
    "bsearch": "B Search",
    "socialbook": "Social Book",
}


PAGE_URL_LABELS = {
    "/home": "Homepage",
    "/lander-1": "Landing page 1",
    "/lander-2": "Landing page 2",
    "/lander-3": "Landing page 3",
    "/lander-4": "Landing page 4",
    "/lander-5": "Landing page 5",
    "/products": "Product catalog (/products)",
    "/the-original-mr-fuzzy": "Original Mr. Fuzzy product page",
    "/the-forever-love-bear": "Forever Love Bear product page",
    "/the-birthday-sugar-panda": "Birthday Sugar Panda product page",
    "/the-hudson-river-mini-bear": "Hudson River Mini Bear product page",
    "/cart": "Cart (/cart)",
    "/shipping": "Shipping (/shipping)",
    "/billing": "Observed billing path (/billing)",
    "/billing-2": "Observed billing path (/billing-2)",
    "/thank-you-for-your-order": "Order confirmation page",
}


def display_label(value: str) -> str:
    if value in AD_CONTENT_LABELS:
        return AD_CONTENT_LABELS[value]
    if value in SOURCE_LABELS:
        return SOURCE_LABELS[value]
    if value in PAGE_URL_LABELS:
        return PAGE_URL_LABELS[value]
    return value.replace("_", " ").strip().title()

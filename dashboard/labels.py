from __future__ import annotations


AD_CONTENT_LABELS = {
    "g_ad_1": "Gsearch ad 1 (masked content ID)",
    "g_ad_2": "Gsearch ad 2 (masked content ID)",
    "b_ad_1": "Bsearch ad 1 (masked content ID)",
    "b_ad_2": "Bsearch ad 2 (masked content ID)",
    "social_ad_1": "Socialbook ad 1 (masked content ID)",
    "social_ad_2": "Socialbook ad 2 (masked content ID)",
}


PAGE_URL_LABELS = {
    "/home": "Homepage (/home)",
    "/lander-1": "Landing page 1 (/lander-1)",
    "/lander-2": "Landing page 2 (/lander-2)",
    "/lander-3": "Landing page 3 (/lander-3)",
    "/lander-4": "Landing page 4 (/lander-4)",
    "/lander-5": "Landing page 5 (/lander-5)",
    "/products": "Product catalog (/products)",
    "/the-original-mr-fuzzy": "Original Mr. Fuzzy product page",
    "/the-forever-love-bear": "Forever Love Bear product page",
    "/the-birthday-sugar-panda": "Birthday Sugar Panda product page",
    "/the-hudson-river-mini-bear": "Hudson River Mini Bear product page",
    "/cart": "Cart (/cart)",
    "/shipping": "Shipping (/shipping)",
    "/billing": "Original billing page (/billing)",
    "/billing-2": "Optimized billing page (/billing-2)",
    "/thank-you-for-your-order": "Order confirmation page",
}


def display_label(value: str) -> str:
    if value in AD_CONTENT_LABELS:
        return AD_CONTENT_LABELS[value]
    if value in PAGE_URL_LABELS:
        return PAGE_URL_LABELS[value]
    return value.replace("_", " ").strip().title()

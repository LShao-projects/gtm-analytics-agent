from dashboard.theme import (
    BACKGROUND,
    CHART_PALETTE,
    INK,
    MUTED,
    NAVY,
    NEGATIVE,
    POSITIVE,
    WHITE,
)


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_theme_text_contrast_meets_wcag_aa():
    assert _contrast_ratio(NAVY, WHITE) >= 4.5
    assert _contrast_ratio(INK, BACKGROUND) >= 4.5
    assert _contrast_ratio(MUTED, WHITE) >= 4.5


def test_generic_chart_palette_does_not_use_status_colors():
    assert POSITIVE not in CHART_PALETTE
    assert NEGATIVE not in CHART_PALETTE

import pytest

from dashboard.guide import (
    CAMPAIGN_DEFINITIONS,
    METRIC_GUIDES,
    TABLE_SPECS,
    TRAFFIC_SOURCE_RULES,
)
from investigation.definitions import (
    CATALOG,
    MAX_DEFINITIONS,
    lookup,
    topic_labels,
)


def _metric_rows():
    return [
        (page, display, formula, grain, note)
        for page, rows in METRIC_GUIDES.items()
        for display, formula, grain, note in rows
    ]


def test_every_data_guide_metric_is_quoted_from_its_source():
    for page, display, formula, grain, note in _metric_rows():
        definition = CATALOG[f"{page} / {display}"]

        assert formula.rstrip(".") in definition.text
        assert grain in definition.text
        assert note.rstrip(".") in definition.text
        assert page in definition.source


def test_the_same_metric_name_on_different_pages_stays_distinct():
    sessions = [label for label in topic_labels() if label.endswith(" / Sessions")]

    assert len(sessions) >= 3
    assert len({CATALOG[label].text for label in sessions}) == len(sessions)


def test_derived_dimensions_and_tables_are_covered():
    for name, rule in TRAFFIC_SOURCE_RULES.items():
        assert rule in CATALOG[f"Traffic source / {name}"].text
    for name, meaning in CAMPAIGN_DEFINITIONS.items():
        assert meaning in CATALOG[f"Campaign / {name}"].text
    for name, spec in TABLE_SPECS.items():
        text = CATALOG[f"Table / {name}"].text
        assert spec["grain"] in text and spec["primary_key"] in text


def test_labels_are_unique_and_match_the_catalog():
    labels = topic_labels()

    assert len(labels) == len(set(labels)) == len(CATALOG)
    expected = (
        len(_metric_rows())
        + len(TRAFFIC_SOURCE_RULES)
        + len(CAMPAIGN_DEFINITIONS)
        + len(TABLE_SPECS)
    )
    assert len(labels) == expected


def test_lookup_separates_known_from_unknown_and_drops_duplicates():
    found, unknown = lookup(
        (
            "Executive Overview / Revenue",
            "Executive Overview / Revenue",
            "Executive Overview / Gross revenue",
        )
    )

    assert [definition.topic for definition in found] == ["Executive Overview / Revenue"]
    assert unknown == ("Executive Overview / Gross revenue",)


def test_lookup_keeps_only_the_first_few_topics():
    found, unknown = lookup(topic_labels()[: MAX_DEFINITIONS + 4])

    assert len(found) == MAX_DEFINITIONS
    assert unknown == ()


@pytest.mark.parametrize("text", ["", " ", "revenue"])
def test_lookup_requires_an_exact_label(text):
    found, unknown = lookup((text,))

    assert found == ()
    assert unknown == (text,)

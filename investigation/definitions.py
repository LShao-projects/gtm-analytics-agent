"""Data Guide definitions the agent may quote. The text comes from dashboard.guide, never from a model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from dashboard.guide import (
    CAMPAIGN_DEFINITIONS,
    METRIC_GUIDES,
    TABLE_SPECS,
    TRAFFIC_SOURCE_RULES,
)

MAX_DEFINITIONS = 3


@dataclass(frozen=True)
class Definition:
    topic: str
    text: str
    source: str


def _sentence(text: str) -> str:
    return text.rstrip(". ") + "."


def _build() -> dict[str, Definition]:
    catalog: dict[str, Definition] = {}

    def add(topic: str, text: str, source: str) -> None:
        if topic in catalog:
            raise ValueError(f"Duplicate Data Guide topic: {topic}")
        catalog[topic] = Definition(topic, text, source)

    for page, rows in METRIC_GUIDES.items():
        for display, formula, grain, note in rows:
            add(
                f"{page} / {display}",
                f"{display} on {page}: {_sentence(formula)} "
                f"Grain: {grain}. Note: {_sentence(note)}",
                f"Data Guide, Metrics & Charts, {page}",
            )
    for name, rule in TRAFFIC_SOURCE_RULES.items():
        add(
            f"Traffic source / {name}",
            f"Traffic source {name}: {_sentence(rule)}",
            "Data Guide, Derived Dimensions, Traffic Source",
        )
    for name, meaning in CAMPAIGN_DEFINITIONS.items():
        add(
            f"Campaign / {name}",
            f"Campaign {name}: {_sentence(meaning)}",
            "Data Guide, Derived Dimensions, Campaign",
        )
    for name, spec in TABLE_SPECS.items():
        add(
            f"Table / {name}",
            f"Table {name}. Grain: {spec['grain']}. Primary key: {spec['primary_key']}. "
            f"{_sentence(spec['description'])}",
            "Data Guide, Raw Data Dictionary",
        )
    return catalog


CATALOG: Mapping[str, Definition] = _build()


def topic_labels() -> tuple[str, ...]:
    return tuple(CATALOG)


def lookup(
    topics: Iterable[str],
) -> tuple[tuple[Definition, ...], tuple[str, ...]]:
    """Return the definitions for exact labels, and the labels that do not exist."""
    found: list[Definition] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        if topic in seen:
            continue
        seen.add(topic)
        definition = CATALOG.get(topic)
        if definition is None:
            unknown.append(topic)
        elif len(found) < MAX_DEFINITIONS:
            found.append(definition)
    return tuple(found), tuple(unknown)

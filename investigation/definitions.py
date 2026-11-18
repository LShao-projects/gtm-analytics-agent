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


def _sentence(text: str) -> str:
    return text.rstrip(". ") + "."


@dataclass(frozen=True)
class Definition:
    """One Data Guide entry: its name, where it lives, and labeled parts quoted from the Guide."""

    name: str
    context: str
    fields: tuple[tuple[str, str], ...]
    source: str

    @property
    def topic(self) -> str:
        return f"{self.context} / {self.name}"

    @property
    def text(self) -> str:
        """The same content as one run of plain sentences, for logs and graders."""
        parts = " ".join(f"{label}: {_sentence(value)}" for label, value in self.fields)
        return f"{self.name} ({self.context}). {parts}"


def _build() -> dict[str, Definition]:
    catalog: dict[str, Definition] = {}

    def add(
        name: str, context: str, fields: tuple[tuple[str, str], ...], source: str
    ) -> None:
        definition = Definition(name, context, fields, source)
        if definition.topic in catalog:
            raise ValueError(f"Duplicate Data Guide topic: {definition.topic}")
        catalog[definition.topic] = definition

    for page, rows in METRIC_GUIDES.items():
        for display, formula, grain, note in rows:
            add(
                display,
                page,
                (
                    ("Formula or Definition", formula),
                    ("Grain", grain),
                    ("Interpretation Note", note),
                ),
                f"Data Guide, Metrics & Charts, {page}",
            )
    for name, rule in TRAFFIC_SOURCE_RULES.items():
        add(
            name,
            "Traffic source",
            (("Rule", rule),),
            "Data Guide, Derived Dimensions, Traffic Source",
        )
    for name, meaning in CAMPAIGN_DEFINITIONS.items():
        add(
            name,
            "Campaign",
            (("Meaning", meaning),),
            "Data Guide, Derived Dimensions, Campaign",
        )
    for name, spec in TABLE_SPECS.items():
        add(
            name,
            "Table",
            (
                ("Description", spec["description"]),
                ("Grain", spec["grain"]),
                ("Primary Key", spec["primary_key"]),
            ),
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

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from dashboard.metrics import (
    overview_drivers,
    overview_kpis,
    revenue_driver_contributions,
    segment_contributions as calculate_segment_contributions,
)
from investigation.evidence import EvidenceRecord, EvidenceRegistry
from investigation.models import ResolvedScope


SUPPORTED_SEGMENT_DIMENSIONS = (
    "Traffic source",
    "UTM source",
    "Campaign",
    "Device",
    "Session type",
)


class ToolInputError(ValueError):
    pass


class UnsupportedToolError(ValueError):
    pass


def _clean_value(value: object) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, int):
        return value
    return float(value)


def _kpi_payload(values: dict[str, float | int]) -> dict[str, float | int | None]:
    return {key: _clean_value(value) for key, value in values.items()}


class InvestigationTools:
    """Registered read-only wrappers over the tested dashboard metric layer."""

    def __init__(
        self,
        database_path: str | Path,
        registry: EvidenceRegistry | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.registry = registry or EvidenceRegistry()

    def call(
        self,
        tool_name: str,
        scope: ResolvedScope,
        **arguments: object,
    ) -> EvidenceRecord:
        tools: dict[str, Callable[..., EvidenceRecord]] = {
            "revenue_summary": self.revenue_summary,
            "revenue_decomposition": self.revenue_decomposition,
            "segment_contributions": self.segment_contributions,
        }
        tool = tools.get(tool_name)
        if tool is None:
            raise UnsupportedToolError(f"Tool is not registered: {tool_name}")
        return tool(scope, **arguments)

    def _period_kpis(
        self, scope: ResolvedScope
    ) -> tuple[dict[str, float | int], dict[str, float | int] | None]:
        current = overview_kpis(
            self.database_path,
            scope.filters,
            scope.current_period,
            revenue_basis=scope.revenue_basis,
        )
        comparison = (
            overview_kpis(
                self.database_path,
                scope.filters,
                scope.comparison_period,
                revenue_basis=scope.revenue_basis,
            )
            if scope.comparison_period is not None
            else None
        )
        return current, comparison

    def revenue_summary(self, scope: ResolvedScope) -> EvidenceRecord:
        current, comparison = self._period_kpis(scope)
        current_revenue = float(current["revenue"])
        comparison_revenue = (
            float(comparison["revenue"]) if comparison is not None else None
        )
        absolute_change = (
            current_revenue - comparison_revenue
            if comparison_revenue is not None
            else None
        )
        relative_change = (
            absolute_change / comparison_revenue
            if absolute_change is not None and comparison_revenue != 0
            else None
        )
        return self.registry.register(
            "revenue_summary",
            scope,
            {
                "revenue_basis": scope.revenue_basis,
                "current": _kpi_payload(current),
                "comparison": _kpi_payload(comparison) if comparison else None,
                "current_revenue": current_revenue,
                "comparison_revenue": comparison_revenue,
                "absolute_change": absolute_change,
                "relative_change": relative_change,
            },
        )

    def revenue_decomposition(self, scope: ResolvedScope) -> EvidenceRecord:
        if scope.comparison_period is None:
            raise ToolInputError("Revenue decomposition requires a comparison period")
        current, comparison = self._period_kpis(scope)
        assert comparison is not None
        frame = revenue_driver_contributions(
            current,
            comparison,
            revenue_basis=scope.revenue_basis,
        )
        drivers = [
            {
                "driver": str(row.driver),
                "current": _clean_value(row.current),
                "comparison": _clean_value(row.comparison),
                "value_format": str(row.value_format),
                "contribution": float(row.contribution),
            }
            for row in frame.itertuples(index=False)
        ]
        observed_change = float(current["revenue"]) - float(comparison["revenue"])
        contribution_sum = float(frame["contribution"].sum())
        return self.registry.register(
            "revenue_decomposition",
            scope,
            {
                "revenue_basis": scope.revenue_basis,
                "observed_change": observed_change,
                "contribution_sum": contribution_sum,
                "reconciliation_error": contribution_sum - observed_change,
                "drivers": drivers,
            },
        )

    def segment_contributions(
        self,
        scope: ResolvedScope,
        *,
        dimension: str = "Traffic source",
    ) -> EvidenceRecord:
        if scope.comparison_period is None:
            raise ToolInputError("Segment contribution requires a comparison period")
        if dimension not in SUPPORTED_SEGMENT_DIMENSIONS:
            raise ToolInputError(f"Unsupported segment dimension: {dimension}")

        current = overview_drivers(
            self.database_path,
            scope.filters,
            scope.current_period,
            dimension=dimension,
            revenue_basis=scope.revenue_basis,
        )
        comparison = overview_drivers(
            self.database_path,
            scope.filters,
            scope.comparison_period,
            dimension=dimension,
            revenue_basis=scope.revenue_basis,
        )
        frame = calculate_segment_contributions(
            current, comparison, value_column="revenue"
        )
        segments = [
            {
                "segment": str(row.segment),
                "current": float(row.current),
                "comparison": float(row.comparison),
                "absolute_delta": float(row.absolute_delta),
                "share_of_total_delta": _clean_value(row.share_of_total_delta),
            }
            for row in frame.itertuples(index=False)
        ]
        observed_change = float(current["revenue"].sum()) - float(
            comparison["revenue"].sum()
        )
        contribution_sum = float(frame["absolute_delta"].sum())
        return self.registry.register(
            "segment_contributions",
            scope,
            {
                "revenue_basis": scope.revenue_basis,
                "dimension": dimension,
                "observed_change": observed_change,
                "contribution_sum": contribution_sum,
                "reconciliation_error": contribution_sum - observed_change,
                "segments": segments,
            },
        )


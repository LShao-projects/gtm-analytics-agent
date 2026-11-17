from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


def _add_months(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    return datetime(index // 12, index % 12 + 1, 1)


@dataclass(frozen=True)
class DatePeriod:
    """A half-open timestamp range aligned to calendar-month boundaries."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("Date period start must be before end")
        if self.start.day != 1 or self.end.day != 1:
            raise ValueError("Date periods must start on month boundaries")

    @classmethod
    def from_months(cls, start_month: str, end_month: str) -> "DatePeriod":
        start = datetime.strptime(start_month, "%Y-%m")
        inclusive_end = datetime.strptime(end_month, "%Y-%m")
        if start > inclusive_end:
            raise ValueError("Start month must not be after end month")
        return cls(start=start, end=_add_months(inclusive_end, 1))

    @property
    def month_count(self) -> int:
        return (self.end.year - self.start.year) * 12 + self.end.month - self.start.month

    @property
    def label(self) -> str:
        final_day = self.end - timedelta(days=1)
        if self.start.year == final_day.year:
            return f"{self.start.strftime('%b')} {self.start.day}–{final_day.strftime('%b')} {final_day.day}, {final_day.year}"
        return f"{self.start.strftime('%b')} {self.start.day}, {self.start.year}–{final_day.strftime('%b')} {final_day.day}, {final_day.year}"

    def sql_bounds(self) -> tuple[str, str]:
        return (
            self.start.strftime("%Y-%m-%d %H:%M:%S"),
            self.end.strftime("%Y-%m-%d %H:%M:%S"),
        )


@dataclass(frozen=True)
class FilterSpec:
    """Shared session-level filters; None means unfiltered, empty means match none."""

    traffic_sources: tuple[str, ...] | None = None
    campaigns: tuple[str, ...] | None = None
    devices: tuple[str, ...] | None = None
    session_types: tuple[str, ...] | None = None
    ad_contents: tuple[str, ...] | None = None
    referrer_types: tuple[str, ...] | None = None


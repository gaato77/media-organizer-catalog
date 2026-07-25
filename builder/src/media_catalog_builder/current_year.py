from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class RefreshMode(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class MonthWindow:
    year: int
    month: int
    start: datetime
    end: datetime
    complete: bool


@dataclass(frozen=True, slots=True)
class CurrentYearPlan:
    year: int
    through: datetime
    elapsed_months: tuple[MonthWindow, ...]
    refresh_months: tuple[MonthWindow, ...]
    refresh_mode: RefreshMode


def _as_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _next_month_start(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=UTC)
    return datetime(year, month + 1, 1, tzinfo=UTC)


def resolve_current_year_plan(
    *,
    now: datetime,
    refresh_mode: RefreshMode,
    year: int | None = None,
    through: datetime | None = None,
) -> CurrentYearPlan:
    now_utc = _as_utc(now, label="now")
    selected_year = now_utc.year if year is None else year
    if not 1 <= selected_year <= 9998:
        raise ValueError("year must be between 1 and 9998")

    if through is None:
        through_utc = (now_utc + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        through_utc = _as_utc(through, label="through")

    year_start = datetime(selected_year, 1, 1, tzinfo=UTC)
    year_boundary = datetime(selected_year + 1, 1, 1, tzinfo=UTC)
    if not year_start < through_utc <= year_boundary:
        raise ValueError("through must fall within the selected year boundary")

    elapsed: list[MonthWindow] = []
    for month in range(1, 13):
        start = datetime(selected_year, month, 1, tzinfo=UTC)
        if start >= through_utc:
            break
        natural_end = _next_month_start(selected_year, month)
        end = min(natural_end, through_utc)
        elapsed.append(
            MonthWindow(
                year=selected_year,
                month=month,
                start=start,
                end=end,
                complete=end == natural_end,
            )
        )

    if not elapsed:
        raise ValueError("current-year plan contains no elapsed month")

    if refresh_mode is RefreshMode.DAILY:
        refresh = elapsed[-2:]
    elif refresh_mode in {RefreshMode.WEEKLY, RefreshMode.FULL}:
        refresh = elapsed
    else:
        raise ValueError("unsupported refresh mode")

    return CurrentYearPlan(
        year=selected_year,
        through=through_utc,
        elapsed_months=tuple(elapsed),
        refresh_months=tuple(refresh),
        refresh_mode=refresh_mode,
    )

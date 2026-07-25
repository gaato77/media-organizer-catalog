from __future__ import annotations

from datetime import UTC, datetime

import pytest

from media_catalog_builder.current_year import RefreshMode, resolve_current_year_plan


def test_midyear_daily_plan_excludes_future_months() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2026, 7, 25, 12, tzinfo=UTC),
        refresh_mode=RefreshMode.DAILY,
    )

    assert plan.year == 2026
    assert plan.through == datetime(2026, 7, 26, tzinfo=UTC)
    assert [window.month for window in plan.elapsed_months] == list(range(1, 8))
    assert [window.month for window in plan.refresh_months] == [6, 7]
    assert all(window.complete for window in plan.elapsed_months[:-1])
    assert plan.elapsed_months[-1].complete is False
    assert plan.elapsed_months[-1].end == plan.through


def test_january_daily_plan_refreshes_only_january() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2027, 1, 3, 8, tzinfo=UTC),
        refresh_mode=RefreshMode.DAILY,
    )

    assert plan.year == 2027
    assert [window.month for window in plan.elapsed_months] == [1]
    assert [window.month for window in plan.refresh_months] == [1]


def test_weekly_plan_refreshes_every_elapsed_month() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2026, 4, 10, tzinfo=UTC),
        refresh_mode=RefreshMode.WEEKLY,
    )

    assert [window.month for window in plan.refresh_months] == [1, 2, 3, 4]


def test_manual_recovery_plan_accepts_explicit_year_and_through() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2026, 7, 25, tzinfo=UTC),
        year=2025,
        through=datetime(2025, 11, 16, tzinfo=UTC),
        refresh_mode=RefreshMode.FULL,
    )

    assert plan.year == 2025
    assert plan.through == datetime(2025, 11, 16, tzinfo=UTC)
    assert [window.month for window in plan.elapsed_months] == list(range(1, 12))
    assert [window.month for window in plan.refresh_months] == list(range(1, 12))
    assert plan.elapsed_months[-1].complete is False


def test_plan_rejects_through_outside_selected_year() -> None:
    with pytest.raises(ValueError, match="through must fall within the selected year"):
        resolve_current_year_plan(
            now=datetime(2026, 7, 25, tzinfo=UTC),
            year=2026,
            through=datetime(2027, 1, 1, tzinfo=UTC),
            refresh_mode=RefreshMode.DAILY,
        )


def test_plan_requires_timezone_aware_now() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        resolve_current_year_plan(
            now=datetime(2026, 7, 25),
            refresh_mode=RefreshMode.DAILY,
        )

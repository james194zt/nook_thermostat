"""Leaf week chart data (needs HA test venv)."""

from datetime import datetime

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    LEAF_DAY_MEANINGFUL_MINUTES,
    LeafState,
    leaf_week_stats,
)


def test_week_days_oldest_first_with_earned_flag():
    leaf = LeafState(
        minutes_by_day={
            "2026-10-04": 99.0,  # 8 days ago: outside the week
            "2026-10-05": 5.0,
            "2026-10-06": LEAF_DAY_MEANINGFUL_MINUTES,
            "2026-10-11": 1.0,
        }
    )
    stats = leaf_week_stats(leaf, now=datetime(2026, 10, 11, 12, 0))
    days = stats["week_days"]
    assert [d["date"] for d in days] == [f"2026-10-{n:02d}" for n in range(5, 12)]
    assert days[0]["minutes"] == 5.0 and days[1]["earned"] is True
    assert days[-1] == {"date": "2026-10-11", "minutes": 1.0, "earned": 1.0 >= LEAF_DAY_MEANINGFUL_MINUTES}
    assert stats["minutes_week"] == round(5.0 + LEAF_DAY_MEANINGFUL_MINUTES + 1.0, 1)

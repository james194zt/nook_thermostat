"""Tests for the pure heat-demand logic (no Home Assistant needed)."""

import importlib.util
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "nook"


def _load(name):
    pkg = "nook"
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PKG_DIR)]
        sys.modules[pkg] = mod
    full = f"{pkg}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, PKG_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


control = _load("control")

HOUSE = dict(cold_tolerance=0.3, hot_tolerance=0.3, true_radiant=True, coast_c=0.3)


class HouseHysteresis(unittest.TestCase):
    def test_cuts_in_below_target(self):
        self.assertTrue(control.house_calls_for_heat(19.0, 20.0, was_calling=False, **HOUSE))
        self.assertFalse(control.house_calls_for_heat(19.8, 20.0, was_calling=False, **HOUSE))

    def test_keeps_running_through_deadband(self):
        # Old code cut in and out at the same point (target - 0.3).
        self.assertTrue(control.house_calls_for_heat(19.8, 20.0, was_calling=True, **HOUSE))

    def test_true_radiant_stops_before_overshoot(self):
        # 0.3C learned coast -> stop at target + 0.3 - 0.3 = 20.0
        self.assertTrue(control.house_calls_for_heat(19.95, 20.0, was_calling=True, **HOUSE))
        self.assertFalse(control.house_calls_for_heat(20.0, 20.0, was_calling=True, **HOUSE))

    def test_big_coast_keeps_minimum_gap(self):
        fast = {**HOUSE, "coast_c": 0.8}
        off_at = control.house_off_threshold(20.0, **{k: v for k, v in fast.items()})
        self.assertAlmostEqual(off_at, 19.9)

    def test_without_true_radiant_runs_to_hot_tolerance(self):
        plain = {**HOUSE, "true_radiant": False}
        self.assertTrue(control.house_calls_for_heat(20.2, 20.0, was_calling=True, **plain))
        self.assertFalse(control.house_calls_for_heat(20.3, 20.0, was_calling=True, **plain))

    def test_no_sensor_no_heat(self):
        self.assertFalse(control.house_calls_for_heat(None, 20.0, was_calling=True, **HOUSE))


class RoomHysteresis(unittest.TestCase):
    def test_room_runs_to_target_plus_hot(self):
        kw = dict(cold_tolerance=0.3, hot_tolerance=0.3)
        self.assertTrue(control.room_calls_for_heat(19.5, 20.0, was_calling=False, **kw))
        self.assertTrue(control.room_calls_for_heat(20.1, 20.0, was_calling=True, **kw))
        self.assertFalse(control.room_calls_for_heat(20.3, 20.0, was_calling=True, **kw))
        self.assertFalse(control.room_calls_for_heat(19.8, 20.0, was_calling=False, **kw))


GUARD = dict(min_on_seconds=300, min_off_seconds=300)


class BoilerCycleGuard(unittest.TestCase):
    def test_no_change_passes_through(self):
        self.assertEqual(control.boiler_cycle_guard(True, True, 10, **GUARD), (True, 0.0))
        self.assertEqual(control.boiler_cycle_guard(False, False, 10, **GUARD), (False, 0.0))

    def test_holds_on_for_min_run(self):
        self.assertEqual(control.boiler_cycle_guard(False, True, 60, **GUARD), (True, 240))

    def test_holds_off_for_min_rest(self):
        self.assertEqual(control.boiler_cycle_guard(True, False, 200, **GUARD), (False, 100))

    def test_allows_change_after_minimum(self):
        self.assertEqual(control.boiler_cycle_guard(False, True, 300, **GUARD), (False, 0.0))
        self.assertEqual(control.boiler_cycle_guard(True, False, 301, **GUARD), (True, 0.0))

    def test_zero_minimum_disables_guard(self):
        self.assertEqual(
            control.boiler_cycle_guard(True, False, 0, min_on_seconds=0, min_off_seconds=0),
            (True, 0.0),
        )

    def test_zero_minimum_ignores_clock_jump(self):
        # Relay "changed" in the future (clock moved back): no guard means no hold.
        self.assertEqual(
            control.boiler_cycle_guard(True, False, -3600, min_on_seconds=0, min_off_seconds=0),
            (True, 0.0),
        )

    def test_clock_jump_holds_at_most_the_minimum(self):
        self.assertEqual(control.boiler_cycle_guard(True, False, -3600, **GUARD), (False, 300))

    def test_unknown_age_does_not_block(self):
        self.assertEqual(control.boiler_cycle_guard(True, False, None, **GUARD), (True, 0.0))


def _sched(blocks):
    return {d: blocks for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


class NextScheduleChange(unittest.TestCase):
    blocks = [
        {"start": "06:30", "end": "08:30", "temperature": 20},
        {"start": "16:00", "end": "22:00", "temperature": 20},
    ]

    def test_between_blocks_expires_at_next_start(self):
        now = datetime(2026, 9, 28, 12, 0)
        self.assertEqual(control.next_schedule_change(_sched(self.blocks), now), datetime(2026, 9, 28, 16, 0))

    def test_inside_block_expires_at_block_end(self):
        now = datetime(2026, 9, 28, 17, 0)
        self.assertEqual(control.next_schedule_change(_sched(self.blocks), now), datetime(2026, 9, 28, 22, 0))

    def test_late_evening_rolls_to_tomorrow(self):
        now = datetime(2026, 9, 28, 23, 0)
        self.assertEqual(control.next_schedule_change(_sched(self.blocks), now), datetime(2026, 9, 29, 6, 30))

    def test_overnight_block_from_yesterday(self):
        now = datetime(2026, 9, 28, 2, 0)
        blocks = [{"start": "22:00", "end": "06:00", "temperature": 18}]
        self.assertEqual(control.next_schedule_change(_sched(blocks), now), datetime(2026, 9, 28, 6, 0))

    def test_empty_schedule_holds_indefinitely(self):
        self.assertIsNone(control.next_schedule_change({}, datetime(2026, 9, 28, 12, 0)))

    def test_disabled_blocks_ignored(self):
        blocks = [{"start": "16:00", "end": "22:00", "temperature": 20, "enabled": False}]
        self.assertIsNone(control.next_schedule_change(_sched(blocks), datetime(2026, 9, 28, 12, 0)))


if __name__ == "__main__":
    unittest.main()

"""Dead time is learned apart from the warm-up rate.

29 Oct 2026 live: the living room took ~18 min after the boiler started to move,
then rose 3.2 °C/h. One blended rate (2.0 °C/h) plus a fixed 5 min started the
preheat 20–40 min early.
"""

import pytest

from custom_components.nook.intelligence import (
    WarmupModel,
    estimate_preheat_minutes,
    update_warmup_from_cycle,
)

LR = WarmupModel(c_per_hour=2.231, samples=4)


def test_rate_is_measured_after_the_dead_time():
    # 06:02 17.2 → 07:14 20.3, first 0.2 °C by 06:20.
    learned = update_warmup_from_cycle(LR, start_temp=17.2, end_temp=20.3, duration_minutes=72, lag_minutes=18)
    observed = (3.1 - 0.2) / (54 / 60)
    assert learned.c_per_hour == pytest.approx(2.231 * 0.65 + observed * 0.35, abs=0.002)
    assert learned.lag_samples == 1
    assert learned.lag_minutes == pytest.approx(5 * 0.65 + 18 * 0.35, abs=0.06)


def test_without_a_dead_time_it_learns_as_before():
    learned = update_warmup_from_cycle(LR, start_temp=17.2, end_temp=20.3, duration_minutes=72)
    assert learned.c_per_hour == pytest.approx(2.231 * 0.65 + (3.1 / 1.2) * 0.35, abs=0.002)
    assert learned.lag_samples == 0 and learned.lag_minutes == 5.0


def test_a_dead_time_at_the_very_end_is_not_used():
    learned = update_warmup_from_cycle(LR, start_temp=17.2, end_temp=17.6, duration_minutes=30, lag_minutes=28)
    assert learned.lag_samples == 0


def test_estimate_uses_the_learned_dead_time():
    model = WarmupModel(c_per_hour=3.2, samples=6, lag_minutes=18, lag_samples=3)
    # 17.2 → 20: 18 min + 2.6 °C at 3.2 °C/h (48.75 min) — the 66 min it really took.
    assert estimate_preheat_minutes(current_temp=17.2, target_temp=20.0, warmup=model) == 66


def test_estimate_before_any_dead_time_is_unchanged():
    model = WarmupModel(c_per_hour=1.558, samples=14)
    assert estimate_preheat_minutes(current_temp=18.6, target_temp=20.0, warmup=model) == 58


def test_old_saved_models_load_without_a_dead_time():
    model = WarmupModel.from_dict({"c_per_hour": 1.58, "samples": 16, "coast_c": 0.145, "coast_samples": 6})
    assert model.lag_samples == 0 and model.lag_minutes == 5.0
    assert WarmupModel.from_dict(model.to_dict()) == model

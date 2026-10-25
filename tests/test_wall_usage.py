"""Wall panel usage page: last 24 h of boiler runs, targets and kWh (needs HA test venv)."""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    EnergyHistoryState,
    wall_usage_payload,
)

NOW = datetime(2026, 10, 15, 14, 0)  # window = 14 Oct 14:00 → 15 Oct 14:00


def _iv(start: str, end: str | None) -> dict:
    return {"start_ts": start, "end_ts": end}


def test_runs_clipped_joined_at_midnight_and_open_run_counted():
    energy = EnergyHistoryState(
        heat_intervals_by_day={
            # Starts before the window: only the part inside counts (13:30–14:30 → 30 min).
            "2026-10-14": [
                _iv("2026-10-14T13:30:00", "2026-10-14T14:30:00"),
                # Split at midnight by track_heat_interval: one run, 23:40–00:20.
                _iv("2026-10-14T23:40:00", "2026-10-14T23:59:59"),
            ],
            "2026-10-15": [_iv("2026-10-15T00:00:00", "2026-10-15T00:20:00")],
        },
        open_heat_start="2026-10-15T13:45:00",  # boiler on right now
    )
    out = wall_usage_payload(energy, now=NOW)
    assert out["window_minutes"] == 1440
    assert out["run_count"] == 3
    first, night, now_run = out["runs"]
    assert first == {"s": 0.0, "e": 30.0}
    assert night["s"] == pytest.approx(9 * 60 + 40) and night["e"] == pytest.approx(10 * 60 + 20)
    assert now_run == {"s": 1425.0, "e": 1440.0}
    assert out["on_minutes"] == pytest.approx(30 + 40 + 15, abs=0.1)
    assert out["heating_now"] is True
    # 13 Oct 14:00 → 14 Oct 14:00: only the 13:30–14:00 part of the first run.
    assert out["prev_on_minutes"] == pytest.approx(30)


def test_setpoints_start_from_the_value_before_the_window():
    energy = EnergyHistoryState(
        setpoint_events_by_day={
            "2026-10-14": [
                {"ts": "2026-10-14T06:30:00", "temperature": 20.0},
                {"ts": "2026-10-14T22:00:00", "temperature": 17.0},
            ],
            "2026-10-15": [{"ts": "2026-10-15T06:30:00", "temperature": 20.0}],
        }
    )
    out = wall_usage_payload(energy, now=NOW)
    assert out["setpoints"] == [
        {"m": 0.0, "t": 20.0},
        {"m": 480.0, "t": 17.0},
        {"m": 990.0, "t": 20.0},
    ]
    assert out["runs"] == [] and out["on_minutes"] == 0 and out["heating_now"] is False


def test_empty_history():
    out = wall_usage_payload(EnergyHistoryState(), now=NOW)
    assert out["runs"] == [] and out["setpoints"] == [] and out["prev_on_minutes"] == 0


async def _import_meter(hass, entity_id, unit_class, unit, per_hour):
    """+per_hour every hour for the last 40 hours, as a lifetime counter."""
    from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
    from homeassistant.components.recorder.statistics import async_import_statistics
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    await hass.config.async_set_time_zone("Europe/London")
    now = dt_util.utcnow()
    hour = now.replace(minute=0, second=0, microsecond=0)
    rows = []
    total = 500_000.0
    for i in range(40, 0, -1):
        total += per_hour
        rows.append(StatisticData(start=hour - timedelta(hours=i), state=total, sum=total))
    meta = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name="Gas",
        source="recorder",
        statistic_id=entity_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )
    hass.states.async_set(entity_id, str(total), {"friendly_name": "Gas meter", "unit_of_measurement": unit})
    async_import_statistics(hass, meta, rows)
    await async_wait_recording_done(hass)
    day_start = dt_util.start_of_local_day(dt_util.as_local(now))
    return int((hour - day_start).total_seconds() // 3600)


def _check_hourly(out, per_hour):
    full = [h for h in out["hourly"] if h["m"] < 1440 - 60]
    assert full and all(h["v"] == pytest.approx(per_hour) for h in full)
    assert all(-60 < h["m"] <= 1440 for h in out["hourly"])
    assert out["last_24h"] == pytest.approx(sum(h["v"] for h in out["hourly"] if h["m"] >= 0))


async def test_energy_meter_in_wh_shown_in_kwh(recorder_mock, hass):
    from custom_components.nook.energy_meter import async_energy_usage

    hours_today = await _import_meter(hass, "sensor.gas_import", "energy", "Wh", 1000.0)
    out = await async_energy_usage(hass, "sensor.gas_import")
    assert out is not None
    assert out["entity_id"] == "sensor.gas_import" and out["name"] == "Gas meter"
    assert out["unit"] == "kWh" and out["kind"] == "energy"
    _check_hourly(out, 1.0)
    assert out["today"] == pytest.approx(hours_today)


async def test_gas_meter_in_litres_shown_in_m3(recorder_mock, hass):
    from custom_components.nook.energy_meter import async_energy_usage

    # 250 L an hour = 0.25 m³.
    hours_today = await _import_meter(hass, "sensor.gas_volume", "volume", "L", 250.0)
    out = await async_energy_usage(hass, "sensor.gas_volume")
    assert out["unit"] == "m³" and out["kind"] == "volume"
    _check_hourly(out, 0.25)
    assert out["today"] == pytest.approx(hours_today * 0.25)


def test_display_units():
    from custom_components.nook.energy_meter import display_unit

    assert display_unit("energy", "MJ") == ("kWh", {"energy": "kWh"})
    assert display_unit("volume", "m³") == ("m³", {"volume": "m³"})
    assert display_unit("volume", "ft³") == ("ft³", {"volume": "ft³"})
    assert display_unit("volume", "CCF") == ("CCF", {"volume": "CCF"})
    assert display_unit("volume", "gal") == ("m³", {"volume": "m³"})
    assert display_unit("temperature", "°C") is None
    assert display_unit(None, None) is None


async def test_energy_none_without_sensor_or_recorder(hass):
    from custom_components.nook.energy_meter import async_energy_usage

    assert await async_energy_usage(hass, "") is None
    assert await async_energy_usage(hass, "sensor.gas_import") is None  # recorder not loaded


async def test_meter_per_day_and_hour_for_energy_page(recorder_mock, hass):
    from homeassistant.util import dt as dt_util

    from custom_components.nook.energy_meter import async_energy_days

    hours_today = await _import_meter(hass, "sensor.gas_volume", "volume", "L", 250.0)
    out = await async_energy_days(hass, "sensor.gas_volume", days=3)
    assert out["unit"] == "m³" and out["entity_id"] == "sensor.gas_volume"
    days = out["days"]
    today = dt_util.as_local(dt_util.utcnow()).date().isoformat()
    if hours_today:
        assert days[today]["total"] == pytest.approx(hours_today * 0.25)
        assert days[today]["hours"][:hours_today] == [pytest.approx(0.25)] * hours_today
    assert all(len(d["hours"]) == 24 for d in days.values())
    assert all(d["total"] == pytest.approx(sum(d["hours"])) for d in days.values())
    assert len(days) <= 3

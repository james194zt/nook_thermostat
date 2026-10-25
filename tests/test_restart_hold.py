"""A house temperature changed by hand survives an HA restart (needs HA test venv).

The change holds until the next schedule change, restart or not; after that the
schedule is back in charge.
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE  # noqa: E402

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)
from tests.test_schedule_ha import MONDAY, setup  # noqa: E402,F401

# Monday 17:00, inside the default 16:00–22:00 comfort block.
AT = datetime.fromisoformat(f"{MONDAY}T17:00:00+01:00")


async def _restart(hass, coord):
    """HA stops (pending writes flushed, as HA's Store does), then a new coordinator loads."""
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    fresh = NookCoordinator(hass, coord.entry)
    await fresh.async_initialize_intelligence()
    return fresh


async def test_dial_change_survives_a_restart_until_the_next_schedule_change(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(AT)
    scheduled, _ = coord.effective_main_target()
    coord.set_main_temperature(scheduled + 1.5)  # saved with HA's 30 s delayed write
    assert coord.effective_main_target()[0] == scheduled + 1.5

    freezer.move_to(AT + timedelta(minutes=1))  # restart a minute later
    fresh = await _restart(hass, coord)
    try:
        assert fresh.effective_main_target()[0] == scheduled + 1.5
        # The block ends at 22:00: the hold ends with it, the schedule takes over.
        freezer.move_to(AT + timedelta(hours=5))
        assert fresh.effective_main_target()[0] != scheduled + 1.5
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()


async def test_hold_that_ran_out_while_ha_was_down_is_not_brought_back(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(AT)
    scheduled, _ = coord.effective_main_target()
    coord.set_main_temperature(scheduled + 1.5)
    # HA down over the 22:00 change; back at 23:00.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    freezer.move_to(AT + timedelta(hours=6))
    fresh = NookCoordinator(hass, coord.entry)
    await fresh.async_initialize_intelligence()
    try:
        assert fresh.effective_main_target()[0] != scheduled + 1.5
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()

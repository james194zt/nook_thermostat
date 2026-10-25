"""Room order (drag-and-drop on the panel) is saved on the config entry (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.websocket_api import reorder_rooms  # noqa: E402
from tests.test_schedule_ha import setup  # noqa: E402,F401

ROOMS = [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def _ids(rooms):
    return [r["id"] for r in rooms]


def test_reorder_puts_rooms_in_given_order():
    assert _ids(reorder_rooms(ROOMS, ["c", "a", "b"])) == ["c", "a", "b"]


def test_reorder_ignores_unknown_and_duplicate_ids_and_keeps_unlisted():
    assert _ids(reorder_rooms(ROOMS, ["b", "zz", "b"])) == ["b", "a", "c"]


async def test_reordered_rooms_persist_on_the_entry(hass, setup):
    coord, _calls = setup
    lounge = coord.config.rooms[0].to_dict()
    kitchen = {**lounge, "id": "kitchen", "name": "Kitchen", "trv_entity": "climate.kitchen_trv"}
    await coord.async_save_config({"rooms": [lounge, kitchen]})

    rooms = reorder_rooms([r.to_dict() for r in coord.config.rooms], ["kitchen", "lounge"])
    await coord.async_save_config({"rooms": rooms})
    await hass.async_block_till_done()

    assert [r.id for r in coord.config.rooms] == ["kitchen", "lounge"]
    assert _ids(coord.entry.options["rooms"]) == ["kitchen", "lounge"]
    # Reordering must not lose a room's settings.
    assert coord.config.rooms[1].trv_entity == lounge["trv_entity"]

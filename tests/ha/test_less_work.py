"""1.7.0: a speaker's update that changes nothing Media Mgmt shows tells nobody,
entities are written only when what they show changed, and device changes
that can't change the Music Assistant link don't look it up again."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.media_mgmt import manager as manager_module
from custom_components.media_mgmt.const import SIGNAL_ANY_UPDATED
from homeassistant.const import EVENT_STATE_CHANGED, EVENT_STATE_REPORTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .test_integration import advance, set_speaker, setup


async def test_play_position_alone_tells_nobody(
    hass: HomeAssistant, calls, freezer
) -> None:
    set_speaker(hass, media_position=10)
    await setup(hass)
    told: list[str] = []
    unsub = async_dispatcher_connect(
        hass, SIGNAL_ANY_UPDATED, callback(lambda entry_id: told.append(entry_id))
    )
    for position in (12, 14, 16):  # some speakers report this every few seconds
        set_speaker(hass, media_position=position)
        await hass.async_block_till_done()
    assert told == []
    set_speaker(hass, title="Gymnopédie No. 1", artist="Satie", media_position=0)
    await hass.async_block_till_done()
    assert told  # a new song is shown, so it's told at once
    told.clear()
    set_speaker(hass, title="Gymnopédie No. 1", artist="Satie", volume=0.5)
    await hass.async_block_till_done()
    assert told  # the volume is shown too
    unsub()


async def test_entities_written_only_when_changed(
    hass: HomeAssistant, calls, freezer
) -> None:
    set_speaker(hass)
    entry = await setup(hass)
    registry = er.async_get(hass)
    ours = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert ours
    changed: list[str] = []
    reported: list[str] = []

    @callback
    def _ours(event_data) -> bool:
        return event_data["entity_id"] in ours

    hass.bus.async_listen(
        EVENT_STATE_CHANGED,
        callback(lambda event: changed.append(event.data["entity_id"])),
        event_filter=_ours,
    )
    hass.bus.async_listen(
        EVENT_STATE_REPORTED,
        callback(lambda event: reported.append(event.data["entity_id"])),
        event_filter=_ours,
    )
    await advance(hass, freezer, 16)  # each entity's first update writes once
    changed.clear()
    reported.clear()
    for _ in range(4):  # a minute of music: today's minutes move
        await advance(hass, freezer, 16)
    assert changed  # the listening time went up
    assert reported == []  # nothing was written again unchanged
    assert len(set(changed)) < len(ours)  # the mode and the switches weren't


async def test_device_changes_that_cannot_relink_are_skipped(
    hass: HomeAssistant, calls, freezer
) -> None:
    set_speaker(hass)
    await setup(hass)
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("test", "speaker")}
    )
    looked: list[int] = []
    real = manager_module.resolve_ma_link

    def counted(*args, **kwargs):
        looked.append(1)
        return real(*args, **kwargs)

    manager_module.resolve_ma_link = counted
    try:
        devices.async_update_device(device.id, sw_version="2.0")
        devices.async_update_device(device.id, configuration_url="http://192.0.2.1")
        await hass.async_block_till_done()
        assert looked == []  # firmware and links don't change the player
        devices.async_update_device(device.id, name_by_user="Kids Room")
        await hass.async_block_till_done()
        assert looked  # a new name can
    finally:
        manager_module.resolve_ma_link = real

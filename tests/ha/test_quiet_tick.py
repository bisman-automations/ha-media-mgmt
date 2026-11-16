"""1.5.4: a tick that changes nothing (the speaker is off) tells nobody, and a
speaker without a Music Assistant player isn't looked up every tick."""

from custom_components.media_mgmt import manager as manager_module
from custom_components.media_mgmt.const import SIGNAL_ANY_UPDATED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .test_integration import advance, set_speaker, setup


async def test_quiet_tick_tells_nobody(hass: HomeAssistant, calls, freezer) -> None:
    set_speaker(hass, state="off", title=None)
    await setup(hass)
    told: list[str] = []
    unsub = async_dispatcher_connect(
        hass, SIGNAL_ANY_UPDATED, callback(lambda entry_id: told.append(entry_id))
    )
    for _ in range(4):
        await advance(hass, freezer, 16)
    assert told == []  # a minute with the speaker off: nothing to tell
    set_speaker(hass)
    await hass.async_block_till_done()
    told.clear()
    await advance(hass, freezer, 16)
    assert told  # playing: time is counted, so the dashboards hear
    unsub()


async def test_music_assistant_retried_now_and_then(
    hass: HomeAssistant, calls, freezer
) -> None:
    set_speaker(hass, state="off", title=None)
    await setup(hass)
    looked: list[int] = []
    real = manager_module.resolve_ma_link

    def counted(*args, **kwargs):
        looked.append(1)
        return real(*args, **kwargs)

    manager_module.resolve_ma_link = counted
    try:
        for _ in range(8):  # two minutes
            await advance(hass, freezer, 16)
        assert len(looked) <= 1
        await advance(hass, freezer, 5 * 60)
        assert len(looked) >= 1
    finally:
        manager_module.resolve_ma_link = real

"""1.7.1: play position updates don't run the rules again, and the Live
Activity's 15-minute timer only runs while an activity is on the phones."""

from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.core import HomeAssistant

from .test_integration import advance, set_speaker, setup


async def test_play_position_update_runs_nothing(
    hass: HomeAssistant, calls, freezer
) -> None:
    set_speaker(hass, media_position=10)
    entry = await setup(hass)
    manager = entry.runtime_data
    ran: list[int] = []
    real = manager._recompute

    def counted(*args, **kwargs):
        ran.append(1)
        return real(*args, **kwargs)

    manager._recompute = counted
    for position in (12, 14, 16):
        set_speaker(
            hass,
            media_position=position,
            media_position_updated_at=f"2026-11-21T10:00:{position}+00:00",
            entity_picture=f"/api/media_player_proxy/x?token={position}",
        )
        await hass.async_block_till_done()
    assert ran == []
    set_speaker(hass, media_position=18, volume=0.6)  # the volume is read
    await hass.async_block_till_done()
    assert ran
    ran.clear()
    set_speaker(hass, state="paused", media_position=18, volume=0.6)
    await hass.async_block_till_done()
    assert ran  # so is the state


async def test_live_activity_timer_only_while_showing(
    hass: HomeAssistant, calls, freezer
) -> None:
    async_mock_service(hass, "notify", "mobile_app_parent_phone")
    set_speaker(hass, state="idle", title=None)
    entry = await setup(
        hass, announcements={"live_activity": ["mobile_app_parent_phone"]}
    )
    live = entry.runtime_data.live_activity
    assert live._interval_unsub is None  # nothing showing, nothing running
    set_speaker(hass)
    await hass.async_block_till_done()
    assert live._interval_unsub is not None
    set_speaker(hass, state="paused")
    await hass.async_block_till_done()
    await advance(hass, freezer, 61)  # "Music off", then cleared
    assert live._interval_unsub is None

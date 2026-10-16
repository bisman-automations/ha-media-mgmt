"""Fixtures for tests that run inside Home Assistant."""

import pathlib

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.setup import async_setup_component

REPO_COMPONENTS = str(pathlib.Path(__file__).parents[2] / "custom_components")
SERVICES = (
    "media_pause", "media_stop", "media_play", "media_next_track", "turn_off", "turn_on",
    "volume_set", "play_media", "select_source", "shuffle_set", "repeat_set",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    # The test harness ships its own custom_components package; add ours.
    import custom_components

    if REPO_COMPONENTS not in custom_components.__path__:
        custom_components.__path__.append(REPO_COMPONENTS)
    yield


@pytest.fixture
async def calls(hass):
    """Record speaker service calls.

    Load media_player first so its real services don't replace the mocks.
    """
    assert await async_setup_component(hass, "media_player", {})
    return {name: async_mock_service(hass, "media_player", name) for name in SERVICES}

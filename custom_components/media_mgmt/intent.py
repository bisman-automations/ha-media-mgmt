"""Voice and AI assistants: "play Brahms in the kids room".

Registers the MediaMgmtPlayArtist intent. AI conversation agents (OpenAI,
Google, Anthropic, Ollama, ...) with "Assist" control get it as a tool (see
llm.py); custom sentences and the conversation blueprint can use it too.
It plays through the same path as the play_artist action, so blocked
music, limits, quiet windows and the volume cap all apply.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent

from .const import INTENT_PLAY_ARTIST
from .targets import device_area

# Newer Home Assistant validates intent slots with probatio, older with
# voluptuous; the two can't be mixed in one schema.
_schema = getattr(intent, "probatio", None) or vol


class PlayArtistIntentHandler(intent.IntentHandler):
    """Play music by an artist on a speaker Media Mgmt manages."""

    intent_type = INTENT_PLAY_ARTIST
    platforms = frozenset({"media_player"})
    description = (
        "Plays music by an artist on a speaker managed by Media Mgmt, using Music Assistant "
        "when the speaker has it. Use this when someone asks to play an artist or band "
        "(for example 'play Taylor Swift' or 'play Brahms in the kids room'). Leave out the "
        "speaker to use the one in the same room as the person asking. Media Mgmt's rules "
        "(blocked music, listening limits, quiet times, volume caps) still apply, and the "
        "reply says why if the music can't play."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            _schema.Required(
                "artist", description="The artist or band to play"
            ): cv.string,
            _schema.Optional(
                "speaker",
                description="The speaker or room to play on, if the person named one",
            ): cv.string,
            _schema.Optional(
                "radio",
                description="Keep playing similar music after the artist's songs (radio)",
            ): cv.boolean,
            _schema.Optional("preferred_area_id"): cv.string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        from .saved import async_play_request

        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        artist = slots["artist"]["value"]
        speaker = slots.get("speaker", {}).get("value")
        radio = slots.get("radio", {}).get("value")
        area_id = slots.get("preferred_area_id", {}).get("value") or device_area(
            hass, intent_obj.device_id
        )
        user = None
        if intent_obj.context.user_id:
            user = await hass.auth.async_get_user(intent_obj.context.user_id)
        result = await async_play_request(
            hass,
            artist,
            speaker=speaker,
            area_id=area_id,
            radio=radio,
            by=user.name if user else intent_obj.assistant or "voice",
        )
        response = intent_obj.create_response()
        if result.ok:
            response.async_set_speech(result.message)
        else:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, result.message
            )
        response.async_set_speech_slots(
            {"artist": result.name, "speaker": result.speaker}
        )
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register the intent. Home Assistant's intent integration calls this too, so only once."""
    if INTENT_PLAY_ARTIST not in hass.data.get(intent.DATA_KEY, {}):
        intent.async_register(hass, PlayArtistIntentHandler())

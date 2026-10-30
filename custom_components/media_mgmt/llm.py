"""AI assistants: offer "play an artist" as a tool to conversation agents.

Home Assistant asks each integration for its tools here. 2026.10 added a
title, the integration and annotations to a tool; on 2026.8 and 2026.9 the
tool is offered without them.
"""

from __future__ import annotations

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext

try:
    from homeassistant.helpers.llm import ToolAnnotations
except ImportError:  # Home Assistant 2026.9 and older
    ToolAnnotations = None  # type: ignore[assignment,misc]

from .const import DOMAIN, INTENT_PLAY_ARTIST
from .targets import managers


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """The play artist tool, when a managed speaker is exposed to the assistant."""
    if api_id != LLM_API_ASSIST:
        return None
    handler = next(
        (h for h in intent.async_get(hass) if h.intent_type == INTENT_PLAY_ARTIST), None
    )
    if handler is None:
        return None
    speakers = [
        m.name
        for m in managers(hass)
        if any(
            eid and async_should_expose(hass, llm_context.assistant, eid)
            for eid in (m.entity_id, m.ma_link.entity_id)
        )
    ]
    if not speakers:
        return None
    name = f"{DOMAIN}__{INTENT_PLAY_ARTIST}"
    if ToolAnnotations is None:
        tool = IntentTool(name, handler)
    else:
        tool = IntentTool(
            name,
            handler,
            title="Play artist",
            integration=DOMAIN,
            annotations=ToolAnnotations(
                read_only=False, destructive=False, idempotent=False, open_world=True
            ),
        )
    prompt = (
        f"To play an artist or band, use {DOMAIN}__{INTENT_PLAY_ARTIST}. "
        f"Speakers it can play on: {', '.join(sorted(speakers))}."
    )
    return LLMTools(tools=[tool], prompt=prompt)

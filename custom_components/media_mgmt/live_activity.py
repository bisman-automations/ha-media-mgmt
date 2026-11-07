"""A speaker's Live Activity on the parents' phones.

Starts when music starts and shows how much listening time is left today.
The phone counts the time down itself, so a push is only sent when something
visible changes (``live_view``). When the music stops the activity shows
"Music off" for a minute and then goes away: iOS doesn't reliably remove one
on a silent clear, so it gets a final update first (as in TV Mgmt and
Appliance Live Activity). Music that starts again within that minute picks
the activity back up. iOS ends a Live Activity after 8 hours, so one left on
that long is started again.

Payloads follow https://companion.home-assistant.io/docs/notifications/live-activities/
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util, slugify

from .const import CONF_LIVE_ACTIVITY, DOMAIN
from .live_view import (
    TONE_BAD,
    TONE_OFF,
    TONE_WARN,
    LiveView,
    clock_text,
    live_view,
    same_view,
)

if TYPE_CHECKING:
    from .manager import MediaManager

_LOGGER = logging.getLogger(__name__)

OFF_DISPLAY_SECONDS = 60  # "Music off" stays this long before it's cleared
RESTART_AFTER = timedelta(hours=7, minutes=45)  # iOS ends activities at 8 hours
COLORS = {
    TONE_OFF: "#9E9E9E",
    TONE_WARN: "#FF9800",
    TONE_BAD: "#E5484D",
}
DEFAULT_COLOR = "#03A9F4"
PANEL_URL = "/media-mgmt"


def phone_targets(hass: HomeAssistant) -> dict[str, str]:
    """Phones with the Home Assistant app: notify service -> device name."""
    names = {
        f"mobile_app_{slugify(entry.data.get('device_name') or '')}": entry.data.get(
            "device_name"
        )
        for entry in hass.config_entries.async_entries("mobile_app")
        if entry.data.get("device_name")
    }
    services = hass.services.async_services_for_domain("notify")
    return {
        service: names.get(service)
        or service.removeprefix("mobile_app_").replace("_", " ")
        for service in sorted(services)
        if service.startswith("mobile_app_")
    }


class SpeakerLiveActivity:
    """Owns one speaker's Live Activity."""

    def __init__(self, manager: MediaManager) -> None:
        self.m = manager
        self.hass = manager.hass
        self._showing = False  # an activity is on the phones
        self._was_on: bool | None = None
        self._last: LiveView | None = None
        self._phones: list[str] = []  # where the showing activity was sent
        self._started: datetime | None = None
        self._clear_unsub: CALLBACK_TYPE | None = None
        self._interval_unsub: CALLBACK_TYPE | None = None

    @property
    def tag(self) -> str:
        return f"media-mgmt-{self.m.entry.entry_id}"

    @property
    def phones(self) -> list[str]:
        return list(self.m.options.get(CONF_LIVE_ACTIVITY) or [])

    # ---- life ---------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._interval_unsub = async_track_time_interval(
            self.hass, self._on_interval, timedelta(minutes=15)
        )
        # Home Assistant restarted with music playing: pick the activity up
        # again. With nothing playing, make sure one left from before goes.
        self._was_on = None
        if self._playing() is False and self.phones:
            self._send(self._clear_payload(), self.phones)
        self.refresh()

    @callback
    def async_stop(self) -> None:
        """Stop the timers. A showing activity stays until the music next changes."""
        for unsub in (self._clear_unsub, self._interval_unsub):
            if unsub:
                unsub()
        self._clear_unsub = self._interval_unsub = None

    @callback
    def phones_changed(self) -> None:
        """The phones were changed in the settings: move the activity."""
        if self._showing:
            self._send(self._clear_payload(), list(self._phones))
            self._showing = False
            self._last = None
        self.refresh(force=True)

    # ---- updates ------------------------------------------------------------------

    def _playing(self) -> bool | None:
        """Whether music is playing; None when the speaker can't be reached."""
        if not self.m.player.available:
            return None
        return self.m.player.is_playing

    def view(self) -> LiveView:
        m = self.m
        decision = m.decision

        def clock(epoch: int) -> str:
            local = dt_util.as_local(dt_util.utc_from_timestamp(epoch))
            return clock_text(local.hour, local.minute)

        return live_view(
            playing=self._playing() is True,
            state=decision.state,
            reason=decision.reason,
            remaining_seconds=decision.remaining_seconds,
            used_seconds=m.state.used_seconds,
            quiet_window=decision.quiet_window,
            schedule=decision.schedule,
            now=dt_util.utcnow().timestamp(),
            clock=clock,
        )

    @callback
    def refresh(self, force: bool = False) -> None:
        """Called after every decision: push when something visible changed."""
        on = self._playing()
        if on is None:
            return  # can't reach the speaker: leave the activity as it is
        turned_on = on and self._was_on is not True
        turned_off = not on and self._was_on is True
        self._was_on = on
        phones = self.phones
        if not phones:
            return
        if on:
            if self._clear_unsub:
                self._clear_unsub()
                self._clear_unsub = None
            if not self._showing and not (turned_on or force):
                return
            view = self.view()
            if not (turned_on or force) and same_view(self._last, view):
                return
            if not self._showing:
                self._started = dt_util.utcnow()
            self._push(view, phones)
        elif turned_off and self._showing:
            self._push(self.view(), self._phones)
            self._clear_unsub = async_call_later(
                self.hass, OFF_DISPLAY_SECONDS, self._clear
            )

    async def _on_interval(self, _now: datetime) -> None:
        if (
            self._showing
            and self._started
            and self._playing()
            and dt_util.utcnow() - self._started >= RESTART_AFTER
        ):
            # iOS ends an activity after 8 hours: start a fresh one.
            self._send(self._clear_payload(), list(self._phones))
            self._showing = False
            self._last = None
            self.refresh(force=True)

    @callback
    def _clear(self, _now: datetime | None = None) -> None:
        self._clear_unsub = None
        if self._showing:
            self._send(self._clear_payload(), list(self._phones))
        self._showing = False
        self._last = None
        self._started = None

    # ---- sending ------------------------------------------------------------------

    @callback
    def _push(self, view: LiveView, phones: list[str]) -> None:
        self._last = view
        self._showing = True
        self._phones = list(phones)
        self._send(self.payload(view), phones)

    def payload(self, view: LiveView) -> dict[str, Any]:
        color = COLORS.get(view.tone, DEFAULT_COLOR)
        data: dict[str, Any] = {
            "tag": self.tag,
            "live_update": True,
            "critical_text": view.headline,
            "notification_icon": "mdi:music-off"
            if view.tone == TONE_OFF
            else "mdi:music",
            "notification_icon_color": color,
            "color": color,
            "alert_once": True,
            "sticky": True,
            "url": PANEL_URL,
            "clickAction": PANEL_URL,
        }
        if view.ends_at is not None:
            # The phone counts down to when the time runs out.
            data["chronometer"] = True
            data["when"] = view.ends_at
            data["when_relative"] = False
        return {"title": self.m.name, "message": view.message, "data": data}

    def _clear_payload(self) -> dict[str, Any]:
        return {"message": "clear_notification", "data": {"tag": self.tag}}

    @callback
    def _send(self, payload: dict[str, Any], phones: list[str]) -> None:
        for phone in phones:
            self.m.entry.async_create_background_task(
                self.hass,
                self._async_send(phone, payload),
                f"{DOMAIN} live activity {phone}",
            )

    async def _async_send(self, phone: str, payload: dict[str, Any]) -> None:
        if not self.hass.services.has_service("notify", phone):
            _LOGGER.warning("Media Mgmt: notify.%s isn't set up, skipping", phone)
            return
        try:
            await self.hass.services.async_call("notify", phone, payload, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Media Mgmt: couldn't update notify.%s: %s", phone, err)

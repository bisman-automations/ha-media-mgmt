"""No blocking file I/O on the event loop from this integration.

Home Assistant reviewers (frenck on hacs/default) flag file access made from
the event loop, such as ``Path.resolve`` or ``open`` while registering the
sidebar panel. This wraps the low-level file functions and records every call
made on the event loop thread with a frame from ``custom_components/media_mgmt``
on the stack, then goes through setup with the sidebar panel, the sidebar
app's websocket API, diagnostics, the options and reconfigure flows, and
unload. The same detector as bisman-automations/ha-shared-album-mgmt.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Generator
import io
import os
from pathlib import Path
import shutil
import sys
import sysconfig
import threading
from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from tests.ha.test_integration import set_speaker, setup

DOMAIN = "media_mgmt"
PACKAGE = os.sep.join(("custom_components", "media_mgmt"))
STDLIB = sysconfig.get_paths()["stdlib"]


@pytest.fixture
def loop_io(hass: HomeAssistant) -> Generator[list[str]]:
    """Record file I/O done on the loop thread by the integration."""
    loop_thread = threading.get_ident()
    seen: list[str] = []

    def wrap(name: str, func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if threading.get_ident() == loop_thread:
                # The first frame outside the standard library is the caller.
                # asyncio debug mode reads source lines for task tracebacks
                # (linecache), which is the test harness, not the integration.
                frame = sys._getframe(1)
                debug_only = False
                while frame is not None and frame.f_code.co_filename.startswith(STDLIB):
                    debug_only |= frame.f_code.co_filename.endswith(
                        ("linecache.py", "traceback.py")
                    )
                    frame = frame.f_back
                if (
                    frame is not None
                    and not debug_only
                    and PACKAGE in frame.f_code.co_filename
                ):
                    seen.append(
                        f"{name} from {frame.f_code.co_filename}:{frame.f_lineno}"
                    )
            return func(*args, **kwargs)

        return wrapper

    # Path.resolve goes through os.lstat / os.path.realpath rather than
    # os.stat, so it gets its own hook.
    targets = [
        (builtins, "open"),
        (io, "open"),
        (os, "open"),
        (os, "stat"),
        (os, "lstat"),
        (os, "replace"),
        (os, "unlink"),
        (os, "scandir"),
        (os, "listdir"),
        (os, "mkdir"),
        (shutil, "copyfile"),
        (Path, "resolve"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (Path, "exists"),
        (Path, "is_file"),
        (Path, "is_dir"),
    ]
    patches = [
        patch.object(mod, attr, wrap(f"{mod.__name__}.{attr}", getattr(mod, attr)))
        for mod, attr in targets
    ]
    for p in patches:
        p.start()
    try:
        yield seen
    finally:
        for p in patches:
            p.stop()


def test_the_detector_sees_the_integration(loop_io: list[str]) -> None:
    """A read from this package on the loop thread is recorded."""
    from custom_components.media_mgmt import panel

    panel._version()  # runs here on the test (loop) thread on purpose
    assert any("manifest" in s or "panel.py" in s for s in loop_io), loop_io


async def test_no_file_io_on_the_event_loop(
    hass: HomeAssistant, hass_ws_client, calls, loop_io: list[str]
) -> None:
    """Everything that touches disk runs in the executor."""
    # The sidebar panel needs the frontend (CI installs its requirements).
    pytest.importorskip("hass_frontend")
    assert await async_setup_component(hass, "frontend", {})
    set_speaker(hass)
    entry = await setup(hass)
    assert hass.data["frontend_panels"].get("media-mgmt") is not None

    client = await hass_ws_client(hass)

    async def call(**msg: Any) -> dict[str, Any]:
        await client.send_json_auto_id(msg)
        res = await client.receive_json()
        assert res["success"], res
        return res

    await call(type=f"{DOMAIN}/profiles")
    await call(type=f"{DOMAIN}/settings/get", entry_id=entry.entry_id)
    await call(type=f"{DOMAIN}/settings/set", entry_id=entry.entry_id, max_volume=60)
    await call(type=f"{DOMAIN}/activity", entry_id=entry.entry_id)
    await call(type=f"{DOMAIN}/analytics")
    await call(type=f"{DOMAIN}/history", entry_id=entry.entry_id)
    await call(type=f"{DOMAIN}/home/get")
    await call(type=f"{DOMAIN}/access/me")
    await call(type=f"{DOMAIN}/artists/list")

    from custom_components.media_mgmt.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    await async_get_config_entry_diagnostics(hass, entry)

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    hass.config_entries.options.async_abort(flow["flow_id"])
    result = await entry.start_reconfigure_flow(hass)
    hass.config_entries.flow.async_abort(result["flow_id"])

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert loop_io == []

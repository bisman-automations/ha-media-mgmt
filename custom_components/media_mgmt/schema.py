"""Schema validation library: the one place that imports it.

Home Assistant 2026.10 and newer validate with probatio (and alias
``voluptuous`` to it); older versions use voluptuous. Import ``vol`` from here
(``from .schema import vol``), never voluptuous or probatio directly, so the
code runs on both and mypy checks it against the library Home Assistant uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    try:
        import probatio as vol
    except ImportError:  # Home Assistant before 2026.10
        import voluptuous as vol

__all__ = ["vol"]

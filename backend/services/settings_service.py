"""
services/settings_service.py
============================
Runtime settings stored in the ``app_settings`` table.

Only a handful of values need to be changeable while the server runs - at
present the ESP32-CAM's IP address, which the Camera Management page lets the
operator type in. Everything else stays in ``.env``.

Resolution order for such a value is deliberate:

    1. a value saved here from the dashboard  (most specific, user just set it)
    2. the ``.env`` / environment value        (deployment default)
    3. the address the device last reported in its heartbeat (auto-discovery)

The dashboard wins because an operator correcting an address expects that to
take effect immediately, without editing a file and restarting the backend.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Dict, Optional

from database.db import execute, query_all, query_one, to_iso8601

logger = logging.getLogger(__name__)

# Known setting keys. Kept as constants so a typo is a NameError, not a
# silently-missing setting.
KEY_ESP32_CAM_IP = "esp32_cam_ip"
KEY_ESP32_CAM_NAME = "esp32_cam_name"

HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,61}[A-Za-z0-9])?$")


class InvalidSettingError(ValueError):
    """Raised when a supplied setting value fails validation."""


# --------------------------------------------------------------------------- #
# Generic access
# --------------------------------------------------------------------------- #

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    row = query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
    if row is None:
        return default
    value = row.get("value")
    return default if value in (None, "") else str(value)


def set_setting(key: str, value: Optional[str]) -> None:
    """Store a setting, or delete it when ``value`` is None/empty."""
    if value is None or str(value).strip() == "":
        execute("DELETE FROM app_settings WHERE key = ?", (key,))
        logger.info("Setting '%s' cleared; falling back to the .env / discovered value.", key)
        return

    execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
             VALUES (?, ?, strftime('%Y-%m-%d %H:%M:%S', 'now'))
        ON CONFLICT(key) DO UPDATE
               SET value = excluded.value,
                   updated_at = excluded.updated_at
        """,
        (key, str(value).strip()),
    )
    logger.info("Setting '%s' updated to %r.", key, str(value).strip())


def all_settings() -> Dict[str, Any]:
    return {
        row["key"]: {"value": row["value"], "updated_at": to_iso8601(row["updated_at"])}
        for row in query_all("SELECT key, value, updated_at FROM app_settings ORDER BY key")
    }


# --------------------------------------------------------------------------- #
# ESP32-CAM address
# --------------------------------------------------------------------------- #

def normalise_host(raw: str) -> str:
    """
    Validate and normalise an address typed into the dashboard.

    Accepts a bare IPv4/IPv6 address, a hostname, or either with an
    ``http://`` prefix and a ``/path`` suffix, because people paste what the
    serial monitor printed or what their browser shows. Rejects anything that
    is not a plausible host so a typo surfaces immediately instead of as a
    confusing connection timeout later.
    """
    value = str(raw or "").strip()
    if not value:
        raise InvalidSettingError("The address is empty.")

    # Strip a scheme and anything after the host.
    value = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", value)
    value = value.split("/", 1)[0].strip()

    if not value:
        raise InvalidSettingError("No host remained after removing the URL scheme and path.")

    # Separate an optional :port so both parts can be checked.
    port: Optional[str] = None
    if value.count(":") == 1:
        host_part, port_part = value.split(":", 1)
        if port_part:
            if not port_part.isdigit() or not 1 <= int(port_part) <= 65535:
                raise InvalidSettingError(f"'{port_part}' is not a valid TCP port.")
            port = port_part
        value = host_part

    if len(value) > 253:
        raise InvalidSettingError("The address is too long to be a valid host.")

    try:
        ipaddress.ip_address(value)
        return f"{value}:{port}" if port else value
    except ValueError:
        pass  # not a bare IP - fall through to hostname validation

    if not HOSTNAME_PATTERN.match(value):
        raise InvalidSettingError(
            f"'{value}' is not a valid IP address or hostname. Enter the address printed "
            "in the ESP32-CAM serial monitor, for example 192.168.1.50"
        )
    return f"{value}:{port}" if port else value


def get_configured_esp32_ip() -> Optional[str]:
    """The dashboard-configured address, if one has been saved."""
    return get_setting(KEY_ESP32_CAM_IP)


def set_configured_esp32_ip(raw: Optional[str]) -> Optional[str]:
    """
    Save (or clear) the ESP32-CAM address.

    Returns the normalised value that was stored, or None if it was cleared.
    """
    if raw is None or str(raw).strip() == "":
        set_setting(KEY_ESP32_CAM_IP, None)
        return None

    normalised = normalise_host(raw)
    set_setting(KEY_ESP32_CAM_IP, normalised)
    return normalised


__all__ = [
    "KEY_ESP32_CAM_IP",
    "KEY_ESP32_CAM_NAME",
    "InvalidSettingError",
    "get_setting",
    "set_setting",
    "all_settings",
    "normalise_host",
    "get_configured_esp32_ip",
    "set_configured_esp32_ip",
]

"""
models/device.py
================
Data access for the ``device_status`` table - one row per ESP32-CAM.

Online/offline is derived, not stored as the truth: a device counts as online
only if its last heartbeat arrived within ``offline_after_seconds``. A board
that loses power cannot tell us it died, so a stored "online" flag would lie
forever. The stored ``connection_status`` is still updated so that a plain
SELECT in a DB browser matches what the dashboard shows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database.db import (
    DB_TIME_FORMAT,
    execute,
    insert_returning_id,
    query_all,
    query_one,
    to_iso8601,
    utc_now_string,
)

logger = logging.getLogger(__name__)

VALID_CONNECTION_STATUSES = ("online", "offline", "error")
VALID_LED_STATES = ("on", "off")

# Telemetry columns the firmware may report on a heartbeat.
TELEMETRY_COLUMNS = (
    "ip_address",
    "mac_address",
    "wifi_ssid",
    "wifi_rssi",
    "firmware_version",
    "camera_model",
    "led_state",
    "free_heap",
    "uptime_seconds",
    "frame_size",
    "psram_found",
    "last_error",
)


def _seconds_since(db_timestamp: Optional[str]) -> Optional[float]:
    """Age in seconds of a UTC database timestamp."""
    if not db_timestamp:
        return None
    try:
        moment = datetime.strptime(str(db_timestamp).strip(), DB_TIME_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - moment).total_seconds())


def to_api_dict(row: Dict[str, Any], offline_after_seconds: int = 45) -> Dict[str, Any]:
    """Database row -> JSON for ``/api/device/status``, with liveness computed now."""
    age = _seconds_since(row.get("last_seen"))
    is_online = age is not None and age <= offline_after_seconds

    stored_status = row.get("connection_status") or "offline"
    if stored_status == "error":
        connection_status = "error"
    else:
        connection_status = "online" if is_online else "offline"

    return {
        "id": row.get("id"),
        "device_name": row.get("device_name"),
        "ip_address": row.get("ip_address"),
        "connection_status": connection_status,
        "is_online": is_online,
        "last_seen": to_iso8601(row.get("last_seen")),
        "seconds_since_last_seen": round(age, 1) if age is not None else None,
        "offline_after_seconds": offline_after_seconds,
        "mac_address": row.get("mac_address"),
        "wifi_ssid": row.get("wifi_ssid"),
        "wifi_rssi": row.get("wifi_rssi"),
        "wifi_signal_quality": _signal_quality(row.get("wifi_rssi")),
        "firmware_version": row.get("firmware_version"),
        "camera_model": row.get("camera_model"),
        "led_state": row.get("led_state") or "off",
        "free_heap": row.get("free_heap"),
        "uptime_seconds": row.get("uptime_seconds"),
        "frame_size": row.get("frame_size"),
        "psram_found": None if row.get("psram_found") is None else bool(row.get("psram_found")),
        "last_capture_at": to_iso8601(row.get("last_capture_at")),
        "seconds_since_last_capture": _seconds_since(row.get("last_capture_at")),
        "total_captures": row.get("total_captures") or 0,
        "last_error": row.get("last_error"),
        "created_at": to_iso8601(row.get("created_at")),
        "updated_at": to_iso8601(row.get("updated_at")),
    }


def _signal_quality(rssi: Optional[int]) -> Optional[str]:
    """Map a dBm reading to a label the dashboard can colour-code."""
    if rssi is None:
        return None
    try:
        value = int(rssi)
    except (TypeError, ValueError):
        return None
    if value >= -55:
        return "excellent"
    if value >= -67:
        return "good"
    if value >= -75:
        return "fair"
    return "weak"


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def upsert_device(
    device_name: str,
    *,
    connection_status: str = "online",
    touch_last_seen: bool = True,
    **telemetry: Any,
) -> Dict[str, Any]:
    """
    Create or update a device row from a firmware heartbeat.

    Only the telemetry keys actually supplied are written, so a heartbeat that
    omits ``wifi_rssi`` does not wipe the previously reported value.
    """
    if not device_name:
        raise ValueError("device_name is required.")

    status = str(connection_status).lower()
    if status not in VALID_CONNECTION_STATUSES:
        status = "offline"

    fields: Dict[str, Any] = {
        key: value
        for key, value in telemetry.items()
        if key in TELEMETRY_COLUMNS and value is not None
    }
    if "led_state" in fields:
        led = str(fields["led_state"]).lower()
        fields["led_state"] = led if led in VALID_LED_STATES else "off"

    now = utc_now_string()
    existing = query_one("SELECT id FROM device_status WHERE device_name = ?", (device_name,))

    if existing is None:
        columns = ["device_name", "connection_status", "created_at", "updated_at", *fields.keys()]
        values: List[Any] = [device_name, status, now, now, *fields.values()]
        if touch_last_seen:
            columns.append("last_seen")
            values.append(now)
        placeholders = ", ".join("?" for _ in columns)
        insert_returning_id(
            f"INSERT INTO device_status ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        logger.info("Registered new device '%s' at %s", device_name, fields.get("ip_address"))
    else:
        assignments = ["connection_status = ?"]
        values = [status]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        if touch_last_seen:
            assignments.append("last_seen = ?")
            values.append(now)
        values.append(device_name)
        execute(
            f"UPDATE device_status SET {', '.join(assignments)} WHERE device_name = ?",
            values,
        )

    return get_device(device_name) or {}


def record_capture(device_name: str, increment: bool = True) -> None:
    """Note that a device just delivered an image."""
    now = utc_now_string()
    execute(
        """
        UPDATE device_status
           SET last_capture_at = ?,
               last_seen = ?,
               connection_status = 'online',
               total_captures = total_captures + ?
         WHERE device_name = ?
        """,
        (now, now, 1 if increment else 0, device_name),
    )


def set_led_state(device_name: str, state: str) -> None:
    led = str(state).lower()
    if led not in VALID_LED_STATES:
        raise ValueError(f"led_state must be one of {VALID_LED_STATES}, got {state!r}")
    execute("UPDATE device_status SET led_state = ? WHERE device_name = ?", (led, device_name))


def set_error(device_name: str, message: Optional[str]) -> None:
    execute(
        "UPDATE device_status SET last_error = ?, connection_status = ? WHERE device_name = ?",
        (message, "error" if message else "offline", device_name),
    )


def clear_error(device_name: str) -> None:
    execute("UPDATE device_status SET last_error = NULL WHERE device_name = ?", (device_name,))


def mark_stale_devices_offline(offline_after_seconds: int = 45) -> int:
    """
    Flip the stored status of silent devices to 'offline'.

    Uses SQLite's own clock arithmetic so it stays correct regardless of the
    Python process timezone.
    """
    cursor = execute(
        """
        UPDATE device_status
           SET connection_status = 'offline'
         WHERE connection_status != 'offline'
           AND (
                last_seen IS NULL
                OR strftime('%s', 'now') - strftime('%s', last_seen) > ?
           )
        """,
        (int(offline_after_seconds),),
    )
    return cursor.rowcount or 0


def ensure_device(device_name: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
    """
    Make sure a row exists for a configured device without faking a heartbeat.

    ``touch_last_seen=False`` matters: a device listed in ``.env`` but never
    heard from must stay 'offline' rather than appear briefly online.
    """
    existing = get_device(device_name)
    if existing:
        return existing
    return upsert_device(
        device_name,
        connection_status="offline",
        touch_last_seen=False,
        ip_address=ip_address,
    )


def delete_device(device_name: str) -> bool:
    cursor = execute("DELETE FROM device_status WHERE device_name = ?", (device_name,))
    return (cursor.rowcount or 0) > 0


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def get_device(device_name: str) -> Optional[Dict[str, Any]]:
    return query_one("SELECT * FROM device_status WHERE device_name = ?", (device_name,))


def list_devices(offline_after_seconds: int = 45) -> List[Dict[str, Any]]:
    rows = query_all("SELECT * FROM device_status ORDER BY last_seen DESC, device_name ASC")
    return [to_api_dict(row, offline_after_seconds) for row in rows]


def get_primary_device(
    offline_after_seconds: int = 45,
    preferred_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    The device the dashboard talks to.

    Preference order: the configured device name, then any currently online
    device, then the most recently seen device.
    """
    devices = list_devices(offline_after_seconds)
    if not devices:
        return None
    if preferred_name:
        for device in devices:
            if device["device_name"] == preferred_name:
                return device
    for device in devices:
        if device["is_online"]:
            return device
    return devices[0]


def resolve_device_ip(preferred_name: Optional[str] = None) -> Optional[str]:
    """Last known IP of a device, used when no static IP is configured."""
    rows = query_all(
        "SELECT device_name, ip_address FROM device_status "
        "WHERE ip_address IS NOT NULL AND ip_address != '' "
        "ORDER BY last_seen DESC"
    )
    if not rows:
        return None
    if preferred_name:
        for row in rows:
            if row["device_name"] == preferred_name:
                return row["ip_address"]
    return rows[0]["ip_address"]


__all__ = [
    "VALID_CONNECTION_STATUSES",
    "VALID_LED_STATES",
    "to_api_dict",
    "upsert_device",
    "ensure_device",
    "record_capture",
    "set_led_state",
    "set_error",
    "clear_error",
    "mark_stale_devices_offline",
    "delete_device",
    "get_device",
    "list_devices",
    "get_primary_device",
    "resolve_device_ip",
]

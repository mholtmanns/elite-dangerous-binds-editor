"""Known Elite Dangerous input device IDs mapped to human-readable names.

The device IDs used in .binds files are the device's USB VID+PID written as
one hex string (e.g. "33448194" = VID_3344 PID_8194). Identify unknown IDs
with the AHK/Identify-Joysticks.ahk script in the project's AHK folder, then
add them here.
"""

from __future__ import annotations

KNOWN_DEVICES: dict[str, str] = {
    "{NoDevice}": "(unbound)",
    "Keyboard": "Keyboard",
    "Mouse": "Mouse",
    "33448194": "VIRPIL MongoosT-50CM3",
    "231D0125": "VKB Gunfighter",
    "16D00A38": "MFG Crosswind V2",
}

# Sort order for grouping the table by device. Devices not listed here are
# sorted alphabetically after the ones below.
DEVICE_SORT_ORDER: list[str] = [
    "VIRPIL MongoosT-50CM3",
    "VKB Gunfighter",
    "MFG Crosswind V2",
    "Keyboard",
    "Mouse",
]


def friendly_device_name(device_id: str) -> str:
    """Return a human-readable name for a raw device ID from a .binds file."""
    return KNOWN_DEVICES.get(device_id, device_id)


def device_sort_key(device_name: str) -> tuple[int, str]:
    try:
        return (DEVICE_SORT_ORDER.index(device_name), device_name)
    except ValueError:
        return (len(DEVICE_SORT_ORDER), device_name)

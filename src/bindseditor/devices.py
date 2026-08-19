"""Device name resolution for Elite Dangerous .binds files.

.binds files identify most peripherals by their raw USB VID+PID as an
8-character hex string (e.g. "33448194"). This module turns that into a
human-readable name using, in order:

  1. Elite Dangerous's own fixed device categories (Keyboard, Mouse, unbound)
  2. Windows' own joystick OEM name cache in the registry (the same names
     shown in joy.cpl / the Game Controllers panel), keyed by VID/PID
  3. A user-supplied override, typed in via the Device Names dialog and
     stored next to the loaded .binds file

Nothing here is hard-coded to any particular controller - an ID that can't
be resolved just falls back to showing the raw ID until the registry
resolves it or the user names it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GENERIC_DEVICE_NAMES: dict[str, str] = {
    "{NoDevice}": "(unbound)",
    "Keyboard": "Keyboard",
    "Mouse": "Mouse",
}

# These sort to the end of the device list; everything else (real hardware)
# sorts alphabetically before them.
_GENERIC_SORT_TAIL = ["Keyboard", "Mouse", "(unbound)"]


def registry_lookup(device_id: str) -> str | None:
    """Look up a raw VID+PID device ID in Windows' joystick OEM name cache.

    This is the same cache backing joy.cpl / the Game Controllers panel, so
    it will resolve any controller Windows has already seen on this PC.
    Returns None if not on Windows, not found, or the cached name is blank.
    """
    if sys.platform != "win32" or len(device_id) != 8:
        return None
    try:
        import winreg
    except ImportError:
        return None

    vid, pid = device_id[:4], device_id[4:]
    key_path = (
        r"System\CurrentControlSet\Control\MediaProperties\PrivateProperties"
        rf"\Joystick\OEM\VID_{vid}&PID_{pid}"
    )
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            name, _ = winreg.QueryValueEx(key, "OEMName")
    except OSError:
        return None
    name = (name or "").strip()
    return name or None


def name_store_path_for(binds_path: Path) -> Path:
    """Where device name overrides for a given .binds file are stored."""
    return binds_path.parent / f"{binds_path.name}.device_names.json"


def device_sort_key(device_name: str) -> tuple[int, int, str]:
    if device_name in _GENERIC_SORT_TAIL:
        return (1, _GENERIC_SORT_TAIL.index(device_name), device_name)
    return (0, 0, device_name)


class DeviceNameStore:
    """Resolves device IDs to names and persists user-supplied overrides."""

    def __init__(self, path: Path):
        self.path = path
        self._overrides: dict[str, str] = {}
        self._auto_cache: dict[str, str] = {}
        if path.exists():
            try:
                self._overrides = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._overrides = {}

    def is_generic(self, device_id: str) -> bool:
        return device_id in GENERIC_DEVICE_NAMES

    def has_override(self, device_id: str) -> bool:
        return device_id in self._overrides

    def name_for(self, device_id: str) -> str:
        if device_id in GENERIC_DEVICE_NAMES:
            return GENERIC_DEVICE_NAMES[device_id]
        if device_id in self._overrides:
            return self._overrides[device_id]
        if device_id in self._auto_cache:
            return self._auto_cache[device_id]
        detected = registry_lookup(device_id)
        if detected:
            self._auto_cache[device_id] = detected
            return detected
        return device_id

    def set_override(self, device_id: str, name: str) -> None:
        name = name.strip()
        if name:
            self._overrides[device_id] = name
        else:
            self._overrides.pop(device_id, None)

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self._overrides, indent=2, sort_keys=True), encoding="utf-8"
        )

    def known_names_for(self, device_ids: list[str]) -> list[str]:
        """Friendly names for the given raw device IDs, for a dropdown."""
        real = sorted({self.name_for(d) for d in device_ids if not self.is_generic(d)})
        generic_present = sorted(
            {GENERIC_DEVICE_NAMES[d] for d in device_ids if self.is_generic(d)},
            key=lambda n: _GENERIC_SORT_TAIL.index(n) if n in _GENERIC_SORT_TAIL else 99,
        )
        return real + generic_present

    def id_for_name(self, device_ids: list[str], name: str) -> str | None:
        for device_id in device_ids:
            if self.name_for(device_id) == name:
                return device_id
        for device_id, generic_name in GENERIC_DEVICE_NAMES.items():
            if generic_name == name:
                return device_id
        return None

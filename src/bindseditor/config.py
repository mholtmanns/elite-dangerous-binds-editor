"""Persistent app configuration - the bindings folder, and optionally a
specific .binds file to open automatically on startup.

Config is stored under %APPDATA%\\BindsEditor\\config.json (this app's own
settings) by default - a different thing from %LOCALAPPDATA%, where Elite
Dangerous itself stores its bindings presets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def default_bindings_dir() -> Path:
    """Elite Dangerous's own bindings folder, under %LOCALAPPDATA%."""
    local_appdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local_appdata) / "Frontier Developments" / "Elite Dangerous" / "Options" / "Bindings"


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "BindsEditor" / "config.json"


class AppConfig:
    """Reads/writes the app's own settings file."""

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else default_config_path()

    def _load_raw(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _set_raw(self, key: str, value: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = self._load_raw()
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
        self.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def get_bindings_dir(self) -> Path:
        stored = self._load_raw().get("bindings_dir")
        return Path(stored) if stored else default_bindings_dir()

    def set_bindings_dir(self, path: Path) -> None:
        self._set_raw("bindings_dir", str(path))

    def get_default_binds_file(self) -> Path | None:
        """The file to open automatically at startup, skipping the picker
        dialog - only set once the user ticks "use by default" in it."""
        stored = self._load_raw().get("default_binds_file")
        return Path(stored) if stored else None

    def set_default_binds_file(self, path: Path | None) -> None:
        self._set_raw("default_binds_file", str(path) if path is not None else None)

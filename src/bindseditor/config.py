"""Persistent app configuration - currently just which folder to look for
.binds files in.

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
    """Reads/writes the app's own settings file (currently: bindings_dir)."""

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else default_config_path()

    def _load_raw(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def get_bindings_dir(self) -> Path:
        stored = self._load_raw().get("bindings_dir")
        return Path(stored) if stored else default_bindings_dir()

    def set_bindings_dir(self, path: Path) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = self._load_raw()
        raw["bindings_dir"] = str(path)
        self.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

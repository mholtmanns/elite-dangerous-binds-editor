import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bindseditor.gui import find_binds_presets  # noqa: E402


def test_find_binds_presets_matches_major_version_4(tmp_path):
    (tmp_path / "MyPreset.4.2.binds").write_text("", encoding="utf-8")
    (tmp_path / "OldPreset.3.1.binds").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")

    found = find_binds_presets(tmp_path)
    names = [f.name for f in found]
    assert "MyPreset.4.2.binds" in names
    assert "OldPreset.3.1.binds" not in names
    assert "notes.txt" not in names


def test_find_binds_presets_missing_directory_returns_empty(tmp_path):
    assert find_binds_presets(tmp_path / "does_not_exist") == []

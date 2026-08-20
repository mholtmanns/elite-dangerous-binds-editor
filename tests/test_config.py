import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bindseditor.config import AppConfig, default_bindings_dir  # noqa: E402


def test_default_bindings_dir_points_at_frontier_folder():
    d = default_bindings_dir()
    parts = [p.lower() for p in d.parts]
    assert "frontier developments" in parts
    assert "elite dangerous" in parts
    assert "options" in parts
    assert "bindings" in parts


def test_get_bindings_dir_falls_back_to_default_when_unset(tmp_path):
    config = AppConfig(tmp_path / "config.json")
    assert config.get_bindings_dir() == default_bindings_dir()


def test_set_and_get_bindings_dir_persists(tmp_path):
    config_path = tmp_path / "config.json"
    custom_dir = tmp_path / "MyBindsFolder"

    config = AppConfig(config_path)
    config.set_bindings_dir(custom_dir)
    assert config.get_bindings_dir() == custom_dir

    # A fresh instance reading the same file should see the same value.
    reloaded = AppConfig(config_path)
    assert reloaded.get_bindings_dir() == custom_dir


def test_config_file_is_valid_json(tmp_path):
    config_path = tmp_path / "config.json"
    AppConfig(config_path).set_bindings_dir(tmp_path / "x")
    assert config_path.exists()
    import json
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["bindings_dir"] == str(tmp_path / "x")


def test_default_binds_file_unset_by_default(tmp_path):
    config = AppConfig(tmp_path / "config.json")
    assert config.get_default_binds_file() is None


def test_set_and_get_default_binds_file_persists(tmp_path):
    config_path = tmp_path / "config.json"
    binds_file = tmp_path / "Preset.4.2.binds"

    config = AppConfig(config_path)
    config.set_default_binds_file(binds_file)
    assert config.get_default_binds_file() == binds_file

    reloaded = AppConfig(config_path)
    assert reloaded.get_default_binds_file() == binds_file


def test_clearing_default_binds_file(tmp_path):
    config_path = tmp_path / "config.json"
    binds_file = tmp_path / "Preset.4.2.binds"

    config = AppConfig(config_path)
    config.set_default_binds_file(binds_file)
    config.set_default_binds_file(None)
    assert config.get_default_binds_file() is None


def test_default_binds_file_does_not_disturb_bindings_dir(tmp_path):
    config_path = tmp_path / "config.json"
    custom_dir = tmp_path / "MyBindsFolder"
    binds_file = tmp_path / "Preset.4.2.binds"

    config = AppConfig(config_path)
    config.set_bindings_dir(custom_dir)
    config.set_default_binds_file(binds_file)

    assert config.get_bindings_dir() == custom_dir
    assert config.get_default_binds_file() == binds_file

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bindseditor.devices import DeviceNameStore, name_store_path_for  # noqa: E402

FAKE_ID = "AAAA1111"  # won't resolve via the Windows registry - good for tests


def test_unresolved_device_falls_back_to_raw_id(tmp_path):
    store = DeviceNameStore(name_store_path_for(tmp_path / "profile.binds"))
    assert store.name_for(FAKE_ID) == FAKE_ID


def test_override_persists_across_instances(tmp_path):
    binds_path = tmp_path / "profile.binds"
    store = DeviceNameStore(name_store_path_for(binds_path))
    store.set_override(FAKE_ID, "My Custom Throttle")
    store.save()

    reloaded = DeviceNameStore(name_store_path_for(binds_path))
    assert reloaded.name_for(FAKE_ID) == "My Custom Throttle"
    assert reloaded.has_override(FAKE_ID)


def test_generic_devices_never_need_override(tmp_path):
    store = DeviceNameStore(name_store_path_for(tmp_path / "profile.binds"))
    assert store.name_for("Keyboard") == "Keyboard"
    assert store.name_for("Mouse") == "Mouse"
    assert store.name_for("{NoDevice}") == "(unbound)"
    assert store.is_generic("Keyboard")
    assert not store.is_generic(FAKE_ID)


def test_known_names_and_id_lookup_round_trip(tmp_path):
    store = DeviceNameStore(name_store_path_for(tmp_path / "profile.binds"))
    store.set_override(FAKE_ID, "My Custom Throttle")

    device_ids = [FAKE_ID, "Keyboard"]
    names = store.known_names_for(device_ids)
    assert "My Custom Throttle" in names
    assert "Keyboard" in names

    assert store.id_for_name(device_ids, "My Custom Throttle") == FAKE_ID
    assert store.id_for_name(device_ids, "Keyboard") == "Keyboard"

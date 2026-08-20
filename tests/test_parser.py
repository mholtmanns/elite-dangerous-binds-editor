import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bindseditor.parser import (  # noqa: E402
    apply_edit,
    extract_rows,
    format_key_and_modifiers,
    humanize,
    load_binds,
    parse_key_and_modifiers,
    save_binds,
)

SAMPLE = """<?xml version="1.0" encoding="UTF-8" ?>
<Root PresetName="Test" MajorVersion="4" MinorVersion="2">
\t<MouseSensitivity Value="3.0" />
\t<YawAxisRaw>
\t\t<Binding Device="16D00A38" Key="Joy_RZAxis" />
\t\t<Inverted Value="1" />
\t\t<Deadzone Value="0.00000000" />
\t</YawAxisRaw>
\t<UpThrustButton>
\t\t<Primary Device="33448194" Key="Joy_11" />
\t\t<Secondary Device="Keyboard" Key="Key_A">
\t\t\t<Modifier Device="Keyboard" Key="Key_LeftAlt" />
\t\t\t<Modifier Device="Keyboard" Key="Key_RightControl" />
\t\t</Secondary>
\t</UpThrustButton>
\t<PrimaryOnlyButton>
\t\t<Primary Device="33448194" Key="Joy_5" />
\t\t<Secondary Device="{NoDevice}" Key="" />
\t</PrimaryOnlyButton>
\t<SecondaryOnlyButton>
\t\t<Primary Device="{NoDevice}" Key="" />
\t\t<Secondary Device="Keyboard" Key="Key_C" />
\t</SecondaryOnlyButton>
\t<UnboundButton>
\t\t<Primary Device="{NoDevice}" Key="" />
\t\t<Secondary Device="{NoDevice}" Key="" />
\t</UnboundButton>
</Root>
"""


def make_tree(tmp_path: Path) -> Path:
    p = tmp_path / "test.binds"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_humanize():
    assert humanize("YawAxisRaw") == "Yaw Axis Raw"
    assert humanize("UpThrustButton") == "Up Thrust Button"


def test_humanize_keeps_abbreviations_intact():
    assert humanize("FSSDiscoveryScan") == "FSS Discovery Scan"
    assert humanize("DSSJumpAssist") == "DSS Jump Assist"
    assert humanize("ExplorationFSSEnter") == "Exploration FSS Enter"
    assert humanize("UIFocus") == "UI Focus"


def test_format_and_parse_key_and_modifiers_roundtrip():
    text = format_key_and_modifiers("Key_A", "Key_LeftAlt,Key_RightControl")
    assert text == "Key_A + Key_LeftAlt + Key_RightControl"
    key, mods = parse_key_and_modifiers(text)
    assert key == "Key_A"
    assert mods == ["Key_LeftAlt", "Key_RightControl"]
    assert format_key_and_modifiers("", "") == ""
    assert parse_key_and_modifiers("") == ("", [])


def test_extract_rows_skips_unbound_and_non_bindable(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    actions = {r.action for r in rows}
    assert "UnboundButton" not in actions
    assert "MouseSensitivity" not in actions
    assert "YawAxisRaw" in actions
    assert "UpThrustButton" in actions


def test_one_row_per_action_with_both_bound(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    matches = [r for r in rows if r.action == "UpThrustButton"]
    assert len(matches) == 1
    row = matches[0]
    assert row.key == "Joy_11"
    assert row.secondary_key == "Key_A"
    assert row.secondary_modifiers == "Key_LeftAlt,Key_RightControl"


def test_primary_only_has_empty_secondary(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    row = next(r for r in rows if r.action == "PrimaryOnlyButton")
    assert row.key == "Joy_5"
    assert row.secondary_key == ""


def test_secondary_only_becomes_the_main_binding(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    row = next(r for r in rows if r.action == "SecondaryOnlyButton")
    assert row.key == "Key_C"
    assert row.device_id == "Keyboard"
    assert row.secondary_key == ""  # nothing else left to show


def test_extract_rows_reads_inverted(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    axis = next(r for r in rows if r.action == "YawAxisRaw")
    assert axis.inverted == "Yes"


def test_apply_edit_and_save_roundtrip(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)

    up_thrust = next(r for r in rows if r.action == "UpThrustButton")
    apply_edit(up_thrust, "key", "Joy_5")
    apply_edit(up_thrust, "secondary_key", "Key_B + Key_LeftShift")

    axis = next(r for r in rows if r.action == "YawAxisRaw")
    apply_edit(axis, "inverted", "No")

    backup = save_binds(tree, path)
    assert backup is not None
    assert backup.exists()

    reloaded = ET.parse(path).getroot()
    up_thrust_el = reloaded.find("UpThrustButton")
    assert up_thrust_el.find("Primary").get("Key") == "Joy_5"
    assert up_thrust_el.find("Secondary").get("Key") == "Key_B"
    assert reloaded.find("YawAxisRaw").find("Inverted").get("Value") == "0"

    mods = up_thrust_el.find("Secondary").findall("Modifier")
    assert len(mods) == 1
    assert mods[0].get("Key") == "Key_LeftShift"

    # Untouched action must survive the round trip unchanged.
    assert reloaded.find("MouseSensitivity").get("Value") == "3.0"


def test_clearing_secondary_key_unbinds_it(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    up_thrust = next(r for r in rows if r.action == "UpThrustButton")

    apply_edit(up_thrust, "secondary_key", "")
    assert up_thrust.secondary_key == ""

    save_binds(tree, path)
    reloaded = ET.parse(path).getroot()
    secondary = reloaded.find("UpThrustButton").find("Secondary")
    assert secondary.get("Device") == "{NoDevice}"
    assert secondary.get("Key") == ""
    assert secondary.findall("Modifier") == []


def test_editing_secondary_key_when_none_exists_raises(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    primary_only = next(r for r in rows if r.action == "PrimaryOnlyButton")

    try:
        apply_edit(primary_only, "secondary_key", "Key_Z")
        assert False, "expected ValueError"
    except ValueError:
        pass

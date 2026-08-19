import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bindseditor.parser import apply_edit, extract_rows, humanize, load_binds, save_binds  # noqa: E402

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


def test_extract_rows_skips_unbound_and_non_bindable(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    actions = {r.action for r in rows}
    assert "UnboundButton" not in actions
    assert "MouseSensitivity" not in actions
    assert "YawAxisRaw" in actions
    assert "UpThrustButton" in actions


def test_extract_rows_reads_modifiers(tmp_path):
    path = make_tree(tmp_path)
    tree = load_binds(path)
    rows = extract_rows(tree)
    secondary = next(r for r in rows if r.action == "UpThrustButton" and r.slot == "Secondary")
    assert secondary.modifiers == "Key_LeftAlt,Key_RightControl"


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

    primary = next(r for r in rows if r.action == "UpThrustButton" and r.slot == "Primary")
    apply_edit(primary, "key", "Joy_5")

    axis = next(r for r in rows if r.action == "YawAxisRaw")
    apply_edit(axis, "inverted", "No")

    secondary = next(r for r in rows if r.action == "UpThrustButton" and r.slot == "Secondary")
    apply_edit(secondary, "modifiers", "Key_LeftShift")

    backup = save_binds(tree, path)
    assert backup is not None
    assert backup.exists()

    reloaded = ET.parse(path).getroot()
    up_thrust = reloaded.find("UpThrustButton")
    assert up_thrust.find("Primary").get("Key") == "Joy_5"
    assert reloaded.find("YawAxisRaw").find("Inverted").get("Value") == "0"

    mods = up_thrust.find("Secondary").findall("Modifier")
    assert len(mods) == 1
    assert mods[0].get("Key") == "Key_LeftShift"

    # Untouched action must survive the round trip unchanged.
    assert reloaded.find("MouseSensitivity").get("Value") == "3.0"

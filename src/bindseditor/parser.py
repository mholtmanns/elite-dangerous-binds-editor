"""Read/write support for Elite Dangerous .binds files.

A .binds file is a flat XML tree. Each bindable action is a top-level
element. Axis actions have a single <Binding> child; button/digital actions
have <Primary> and/or <Secondary> children. Any of those may carry one or
more <Modifier> children (keyboard modifier keys held together with the
main key). Unbound slots use Device="{NoDevice}" and an empty Key.

One BindingRow is produced per *action*, not per XML slot: if both Primary
and Secondary are bound, Primary drives the main Device/Key/Modifiers
columns and Secondary is exposed separately as secondary_key/modifiers. If
only Secondary is bound, it becomes the main columns instead (there is
nothing left to show as "secondary" in that case).

This module only touches elements that represent an actual binding slot
(Binding/Primary/Secondary) or Inverted - it leaves axis tuning values
(Deadzone), toggle-group settings, and every other config value in the
file completely untouched.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize(tag: str) -> str:
    """Turn an XML tag like 'YawAxisRaw' into 'Yaw Axis Raw'.

    Splits at lower->upper boundaries, but keeps runs of capitals together
    as a single word (e.g. 'FSSDiscoveryScan' -> 'FSS Discovery Scan',
    not 'F S S Discovery Scan') so abbreviations like FSS/DSS stay intact.
    """
    spaced = _CAMEL_SPLIT_RE.sub(" ", tag)
    return spaced.replace("_", " ").strip()


def format_key_and_modifiers(key: str, modifiers_csv: str) -> str:
    """'Key_A', 'Key_LeftAlt,Key_RightControl' -> 'Key_A + Key_LeftAlt + Key_RightControl'."""
    if not key:
        return ""
    mods = [m for m in modifiers_csv.split(",") if m]
    return " + ".join([key] + mods)


def parse_key_and_modifiers(text: str) -> tuple[str, list[str]]:
    """Inverse of format_key_and_modifiers, for parsing an edited cell."""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


@dataclass
class BindingRow:
    action: str
    label: str
    kind: str  # "Axis" or "Button"
    device_id: str
    device_name: str  # resolved by the caller (see devices.DeviceNameStore)
    key: str
    modifiers: str  # comma-separated raw modifier key names, e.g. "Key_LeftAlt,Key_RightControl"
    inverted: str  # "Yes" / "No" for axis rows, "" otherwise
    secondary_key: str  # "" if the action has no separate secondary binding to show
    secondary_modifiers: str
    secondary_device_id: str
    secondary_device_name: str

    # Not shown in the UI - used to write edits back to the right XML node.
    _slot_element: ET.Element = field(repr=False, compare=False)
    _inverted_element: ET.Element | None = field(default=None, repr=False, compare=False)
    _secondary_element: ET.Element | None = field(default=None, repr=False, compare=False)


def load_binds(path: Path) -> ET.ElementTree:
    return ET.parse(path)


def _is_bound(el: ET.Element | None) -> bool:
    if el is None:
        return False
    device_id = el.get("Device", "")
    key = el.get("Key", "")
    return not (device_id in ("", "{NoDevice}") and not key)


def _modifiers_text(slot_element: ET.Element) -> str:
    keys = [m.get("Key", "") for m in slot_element.findall("Modifier")]
    return ",".join(k for k in keys if k)


def resolve_device_names(rows: list[BindingRow], name_for) -> None:
    """Fill in device_name/secondary_device_name using a `device_id -> name` callable."""
    for row in rows:
        row.device_name = name_for(row.device_id)
        if row.secondary_device_id:
            row.secondary_device_name = name_for(row.secondary_device_id)


def _build_axis_row(action: str, label: str, binding_el: ET.Element,
                     inverted_el: ET.Element | None) -> BindingRow | None:
    if not _is_bound(binding_el):
        return None
    inverted = ""
    if inverted_el is not None:
        inverted = "Yes" if inverted_el.get("Value") == "1" else "No"
    device_id = binding_el.get("Device", "")
    return BindingRow(
        action=action, label=label, kind="Axis",
        device_id=device_id, device_name=device_id,
        key=binding_el.get("Key", ""), modifiers=_modifiers_text(binding_el),
        inverted=inverted,
        secondary_key="", secondary_modifiers="",
        secondary_device_id="", secondary_device_name="",
        _slot_element=binding_el, _inverted_element=inverted_el, _secondary_element=None,
    )


def _build_button_row(action: str, label: str, main_el: ET.Element,
                       other_el: ET.Element | None) -> BindingRow:
    device_id = main_el.get("Device", "")
    row = BindingRow(
        action=action, label=label, kind="Button",
        device_id=device_id, device_name=device_id,
        key=main_el.get("Key", ""), modifiers=_modifiers_text(main_el),
        inverted="",
        secondary_key="", secondary_modifiers="",
        secondary_device_id="", secondary_device_name="",
        _slot_element=main_el, _inverted_element=None, _secondary_element=other_el,
    )
    if other_el is not None:
        row.secondary_key = other_el.get("Key", "")
        row.secondary_modifiers = _modifiers_text(other_el)
        row.secondary_device_id = other_el.get("Device", "")
        row.secondary_device_name = row.secondary_device_id
    return row


def extract_rows(tree: ET.ElementTree) -> list[BindingRow]:
    root = tree.getroot()
    rows: list[BindingRow] = []

    for action_el in root:
        binding_el = action_el.find("Binding")
        primary_el = action_el.find("Primary")
        secondary_el = action_el.find("Secondary")

        if binding_el is None and primary_el is None and secondary_el is None:
            continue  # not a bindable action (e.g. MouseSensitivity)

        label = humanize(action_el.tag)

        if binding_el is not None:
            inverted_el = action_el.find("Inverted")
            row = _build_axis_row(action_el.tag, label, binding_el, inverted_el)
            if row is not None:
                rows.append(row)
            continue

        primary_bound = _is_bound(primary_el)
        secondary_bound = _is_bound(secondary_el)
        if not primary_bound and not secondary_bound:
            continue  # nothing assigned to this action at all

        if primary_bound:
            main_el = primary_el
            other_el = secondary_el if secondary_bound else None
        else:
            main_el = secondary_el
            other_el = None

        rows.append(_build_button_row(action_el.tag, label, main_el, other_el))

    return rows


def apply_edit(row: BindingRow, field_name: str, new_value: str) -> None:
    """Write an edited cell value back into the in-memory XML tree.

    field_name is one of: device_id, key, modifiers, secondary_key, inverted.
    Call save_binds() afterwards to persist changes to disk.
    """
    new_value = new_value.strip()

    if field_name == "device_id":
        row._slot_element.set("Device", new_value)
        row.device_id = new_value
        row.device_name = new_value  # caller re-resolves the friendly name

    elif field_name == "key":
        row._slot_element.set("Key", new_value)
        row.key = new_value

    elif field_name == "modifiers":
        for old in row._slot_element.findall("Modifier"):
            row._slot_element.remove(old)
        raw_keys = [k.strip() for k in new_value.split(",") if k.strip()]
        for k in raw_keys:
            mod = ET.SubElement(row._slot_element, "Modifier")
            mod.set("Device", "Keyboard")
            mod.set("Key", k)
        row.modifiers = ",".join(raw_keys)

    elif field_name == "secondary_key":
        if row._secondary_element is None:
            raise ValueError(f"{row.action} has no secondary binding slot to edit")
        key, mods = parse_key_and_modifiers(new_value)

        if not key:
            row._secondary_element.set("Device", "{NoDevice}")
            row._secondary_element.set("Key", "")
        else:
            if row._secondary_element.get("Device", "") in ("", "{NoDevice}"):
                row._secondary_element.set("Device", "Keyboard")
            row._secondary_element.set("Key", key)

        for old in row._secondary_element.findall("Modifier"):
            row._secondary_element.remove(old)
        for m in mods:
            mod = ET.SubElement(row._secondary_element, "Modifier")
            mod.set("Device", "Keyboard")
            mod.set("Key", m)

        row.secondary_key = key
        row.secondary_modifiers = ",".join(mods)
        row.secondary_device_id = row._secondary_element.get("Device", "")
        row.secondary_device_name = row.secondary_device_id

    elif field_name == "inverted":
        if row._inverted_element is None:
            raise ValueError(f"{row.action} has no Inverted setting")
        want_yes = new_value.strip().lower() in ("yes", "y", "1", "true")
        row._inverted_element.set("Value", "1" if want_yes else "0")
        row.inverted = "Yes" if want_yes else "No"

    else:
        raise ValueError(f"Unknown field: {field_name}")


def save_binds(tree: ET.ElementTree, path: Path, make_backup: bool = True) -> Path | None:
    """Write the tree back to path. Returns the backup file path, if made."""
    backup_path = None
    if make_backup and path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.stem}.{stamp}.bak")
        shutil.copy2(path, backup_path)

    ET.indent(tree, space="\t")
    tree.write(path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
    return backup_path

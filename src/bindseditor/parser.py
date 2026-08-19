"""Read/write support for Elite Dangerous .binds files.

A .binds file is a flat XML tree. Each bindable action is a top-level
element. Axis actions have a single <Binding> child; button/digital actions
have <Primary> and/or <Secondary> children. Any of those may carry one or
more <Modifier> children (keyboard modifier keys held together with the
main key). Unbound slots use Device="{NoDevice}" and an empty Key.

This module only touches elements that represent an actual binding slot
(Binding/Primary/Secondary) - it leaves axis tuning values (Deadzone,
Inverted is the exception, see below), toggle-group settings, and every
other config value in the file completely untouched.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from .devices import friendly_device_name

_CAMEL_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])")


def humanize(tag: str) -> str:
    """Turn an XML tag like 'YawAxisRaw' into 'Yaw Axis Raw'."""
    spaced = _CAMEL_SPLIT_RE.sub(" ", tag)
    return spaced.replace("_", " ").strip()


@dataclass
class BindingRow:
    action: str
    label: str
    kind: str  # "Axis" or "Button"
    slot: str  # "Axis", "Primary", "Secondary"
    device_id: str
    device_name: str
    key: str
    modifiers: str  # comma-separated raw modifier key names, e.g. "Key_LeftAlt,Key_RightControl"
    inverted: str  # "Yes" / "No" for axis rows, "" otherwise

    # Not shown in the UI - used to write edits back to the right XML node.
    _slot_element: ET.Element = field(repr=False, compare=False)
    _inverted_element: ET.Element | None = field(default=None, repr=False, compare=False)

    def row_id(self) -> str:
        return f"{self.action}:{self.slot}"


def load_binds(path: Path) -> ET.ElementTree:
    return ET.parse(path)


def _modifiers_text(slot_element: ET.Element) -> str:
    keys = [m.get("Key", "") for m in slot_element.findall("Modifier")]
    return ",".join(k for k in keys if k)


def _extract_slot_row(action: str, label: str, kind: str, slot_name: str,
                       slot_element: ET.Element,
                       inverted_element: ET.Element | None) -> BindingRow | None:
    device_id = slot_element.get("Device", "")
    key = slot_element.get("Key", "")
    if device_id in ("", "{NoDevice}") and not key:
        return None  # unbound slot - not interesting

    inverted = ""
    if inverted_element is not None:
        inverted = "Yes" if inverted_element.get("Value") == "1" else "No"

    return BindingRow(
        action=action,
        label=label,
        kind=kind,
        slot=slot_name,
        device_id=device_id,
        device_name=friendly_device_name(device_id),
        key=key,
        modifiers=_modifiers_text(slot_element),
        inverted=inverted,
        _slot_element=slot_element,
        _inverted_element=inverted_element,
    )


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
            row = _extract_slot_row(action_el.tag, label, "Axis", "Axis",
                                     binding_el, inverted_el)
            if row is not None:
                rows.append(row)
        else:
            if primary_el is not None:
                row = _extract_slot_row(action_el.tag, label, "Button", "Primary",
                                         primary_el, None)
                if row is not None:
                    rows.append(row)
            if secondary_el is not None:
                row = _extract_slot_row(action_el.tag, label, "Button", "Secondary",
                                         secondary_el, None)
                if row is not None:
                    rows.append(row)

    return rows


def apply_edit(row: BindingRow, field_name: str, new_value: str) -> None:
    """Write an edited cell value back into the in-memory XML tree.

    field_name is one of: device_id, key, modifiers, inverted.
    Call save_binds() afterwards to persist changes to disk.
    """
    new_value = new_value.strip()

    if field_name == "device_id":
        row._slot_element.set("Device", new_value)
        row.device_id = new_value
        row.device_name = friendly_device_name(new_value)

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

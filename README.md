# Elite Dangerous Binds Editor

A small local tool for viewing and editing an Elite Dangerous `.binds` keybind
file as a human-readable table, grouped by input device.

Built for a HOTAS/pedal setup identified via `AHK/Identify-Joysticks.ahk` in
the parent project folder:

| Device ID  | Device |
|---|---|
| `33448194` | VIRPIL MongoosT-50CM3 |
| `231D0125` | VKB Gunfighter |
| `16D00A38` | MFG Crosswind V2 |

Only bindings that are actually assigned to a device/key are shown - unbound
slots (`Device="{NoDevice}"`) are filtered out.

## Features

- Table of every bound action, grouped by device
- Edit Key, Modifiers, and Inverted by **typing text into the cell**
  (double-click to edit); edit Device via a **dropdown of known devices**
  (double-click, no free text) - there is no "press a button to bind"
  capture anywhere in this tool
- Full Undo/Redo (Ctrl+Z / Ctrl+Y) for every edit
- File > Reload from Disk discards all in-memory changes and reloads the
  last saved version of the file
- Save writes the edits back into the original `.binds` XML file (a
  timestamped `.bak` backup is made first)
- Export the current table to a PDF, one page per device

## Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run

```bash
.venv\Scripts\python main.py
```

With no argument, the app searches the parent project folder for a `.binds`
file and opens it automatically if exactly one is found. Otherwise use
File > Open, or pass a path directly:

```bash
.venv\Scripts\python main.py "..\AHK\HCS MongoosVKBMFG.4.2.binds"
```

## Editing keys and modifiers

Elite Dangerous's internal names are used directly, e.g.:

- Keyboard: `Key_A`, `Key_LeftAlt`, `Key_RightControl`
- Joystick button: `Joy_1`, `Joy_12`
- Joystick axis: `Joy_XAxis`, `Joy_RZAxis`

Modifiers are a comma-separated list, e.g. `Key_LeftAlt,Key_RightControl`.
`Inverted` (axis rows only) accepts `Yes` / `No`.

Nothing is written to disk until **File > Save**.

## Tests

```bash
.venv\Scripts\python -m pytest tests/
```

## Project layout

```
main.py                    entry point
src/bindseditor/
  parser.py                .binds XML <-> BindingRow, load/save
  devices.py                known device ID -> friendly name map
  pdf_export.py             table -> PDF (fpdf2)
  gui.py                    Tkinter table UI
tests/test_parser.py       parser + round-trip save tests
```

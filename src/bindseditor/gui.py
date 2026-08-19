"""Tkinter GUI for viewing and editing an Elite Dangerous .binds file.

Editing is done by double-clicking a cell and typing a new value (or, for
Device, picking from a dropdown of known devices) - there is no "press a
button to bind" capture anywhere in this tool, by design.

Device names are never hard-coded: they come from Windows' own joystick
name cache (matched by the .binds file's VID/PID device ID) or from a
user-typed override, stored next to the .binds file. See devices.py.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .devices import DeviceNameStore, device_sort_key, name_store_path_for
from .parser import BindingRow, apply_edit, extract_rows, load_binds, resolve_device_names, save_binds
from .pdf_export import export_pdf

EDITABLE_COLUMNS = {"device", "key", "modifiers", "inverted"}
COLUMNS = ("device", "action", "slot", "key", "modifiers", "inverted")
COLUMN_HEADINGS = {
    "device": "Device",
    "action": "Action",
    "slot": "Slot",
    "key": "Key",
    "modifiers": "Modifiers",
    "inverted": "Inverted",
}
COLUMN_TO_FIELD = {
    "device": "device_id",
    "key": "key",
    "modifiers": "modifiers",
    "inverted": "inverted",
}


@dataclass
class EditCommand:
    item: str
    row: BindingRow
    field_name: str
    old_value: str
    new_value: str


class BindsEditorApp:
    def __init__(self, root: tk.Tk, initial_path: Path | None = None):
        self.root = root
        self.tree_xml = None
        self.rows: list[BindingRow] = []
        self.path: Path | None = None
        self.device_store: DeviceNameStore | None = None
        self.dirty = False

        self.undo_stack: list[EditCommand] = []
        self.redo_stack: list[EditCommand] = []
        self._save_mark = 0  # len(undo_stack) at last save

        self._build_menu()
        self._build_table()
        self._build_statusbar()

        if initial_path is not None:
            self.open_file(initial_path)

    # ------------------------------------------------------------------ UI

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .binds file...", command=self.prompt_open_file)
        file_menu.add_command(label="Reload from Disk", command=self.reload_from_disk)
        file_menu.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export PDF...", command=self.prompt_export_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Device Names...", command=self.open_device_names_dialog)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Editing help", command=self._show_help)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda _e: self.save())
        self.root.bind("<Control-z>", lambda _e: self.undo())
        self.root.bind("<Control-y>", lambda _e: self.redo())
        self.root.bind("<Control-Shift-Z>", lambda _e: self.redo())

    def _build_table(self) -> None:
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(container, columns=COLUMNS, show="tree headings")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=0, stretch=False)
        for col in COLUMNS:
            self.tree.heading(col, text=COLUMN_HEADINGS[col])
        self.tree.column("device", width=170, anchor="w")
        self.tree.column("action", width=230, anchor="w")
        self.tree.column("slot", width=70, anchor="w")
        self.tree.column("key", width=170, anchor="w")
        self.tree.column("modifiers", width=220, anchor="w")
        self.tree.column("inverted", width=70, anchor="center")

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("group", background="#e8e8e8", font=("TkDefaultFont", 9, "bold"))

        self.tree.bind("<Double-1>", self._on_double_click)

        self._row_by_item: dict[str, BindingRow] = {}
        self._edit_widget: tk.Entry | ttk.Combobox | None = None

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="No file loaded.")
        bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(6, 2))
        bar.pack(side="bottom", fill="x")

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Editing help",
            "Double-click a Device, Key, Modifiers, or Inverted cell to edit it.\n\n"
            "Device is a dropdown of known devices - no free text entry. Device\n"
            "names are auto-detected from Windows where possible; use Edit >\n"
            "Device Names... to name any device that couldn't be auto-detected.\n\n"
            "Key / Modifiers use Elite Dangerous's internal names, e.g.:\n"
            "  Key_A, Key_LeftAlt, Key_RightControl, Joy_1, Joy_XAxis\n\n"
            "Modifiers: comma-separated list, e.g. Key_LeftAlt,Key_RightControl\n\n"
            "Inverted: type Yes or No (axis bindings only).\n\n"
            "Ctrl+Z / Ctrl+Y undo and redo edits. File > Reload from Disk discards\n"
            "all changes and reloads the last saved version of the file.\n\n"
            "Nothing is written to disk until you choose File > Save.",
        )

    # -------------------------------------------------------------- loading

    def prompt_open_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Open Elite Dangerous .binds file",
            filetypes=[(".binds files", "*.binds"), ("All files", "*.*")],
        )
        if chosen:
            self.open_file(Path(chosen))

    def open_file(self, path: Path) -> None:
        try:
            tree_xml = load_binds(path)
        except Exception as exc:  # noqa: BLE001 - surface any parse error to the user
            messagebox.showerror("Could not open file", str(exc))
            return

        self.tree_xml = tree_xml
        self.path = path
        self.device_store = DeviceNameStore(name_store_path_for(path))
        self.rows = extract_rows(tree_xml)
        resolve_device_names(self.rows, self.device_store.name_for)
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._save_mark = 0
        self._populate_table()
        self._update_title()
        self.status_var.set(f"Loaded {len(self.rows)} bound entries from {path.name}")

    def reload_from_disk(self) -> None:
        if self.path is None:
            return
        if self.dirty:
            if not messagebox.askyesno(
                "Reload from Disk",
                "This discards all unsaved changes and reloads the file from disk. Continue?",
            ):
                return
        self.open_file(self.path)

    def _distinct_device_ids(self) -> list[str]:
        return sorted({row.device_id for row in self.rows})

    # --------------------------------------------------------------- table

    def _populate_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_by_item.clear()

        groups: dict[str, list[BindingRow]] = {}
        for row in self.rows:
            groups.setdefault(row.device_name, []).append(row)

        for device_name in sorted(groups.keys(), key=device_sort_key):
            device_rows = sorted(groups[device_name], key=lambda r: (r.label, r.slot))
            group_item = self.tree.insert(
                "", "end", text="",
                values=(device_name, f"{len(device_rows)} binding(s)", "", "", "", ""),
                tags=("group",), open=True,
            )
            for row in device_rows:
                item = self.tree.insert(
                    group_item, "end", text="",
                    values=(
                        row.device_name, row.label, row.slot,
                        row.key, row.modifiers, row.inverted,
                    ),
                )
                self._row_by_item[item] = row

    def _refresh_row_display(self, item: str, row: BindingRow) -> None:
        self.tree.set(item, "device", row.device_name)
        self.tree.set(item, "key", row.key)
        self.tree.set(item, "modifiers", row.modifiers)
        self.tree.set(item, "inverted", row.inverted)

    def _update_title(self) -> None:
        name = self.path.name if self.path else "(no file)"
        star = "*" if self.dirty else ""
        self.root.title(f"Elite Dangerous Binds Editor - {name}{star}")

    # ---------------------------------------------------------------- edit

    def _on_double_click(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)  # e.g. "#1"
        if not item or item not in self._row_by_item or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        col_name = COLUMNS[col_index]
        if col_name not in EDITABLE_COLUMNS:
            return

        bbox = self.tree.bbox(item, col_id)
        if not bbox:
            return

        row = self._row_by_item[item]
        if col_name == "device":
            self._begin_device_edit(item, row, bbox)
        else:
            self._begin_text_edit(item, row, col_name, bbox)

    def _begin_text_edit(self, item: str, row: BindingRow, col_name: str,
                          bbox: tuple[int, int, int, int]) -> None:
        x, y, width, height = bbox
        current_value = self.tree.set(item, col_name)

        self._destroy_edit_widget()
        entry = tk.Entry(self.tree)
        entry.insert(0, current_value)
        entry.select_range(0, "end")
        entry.focus_set()
        entry.place(x=x, y=y, width=width, height=height)

        def commit(_event=None) -> None:
            new_value = entry.get()
            self._destroy_edit_widget()
            if new_value == current_value:
                return
            self._commit_edit(item, row, col_name, current_value, new_value)

        def cancel(_event=None) -> None:
            self._destroy_edit_widget()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)
        self._edit_widget = entry

    def _begin_device_edit(self, item: str, row: BindingRow,
                            bbox: tuple[int, int, int, int]) -> None:
        if self.device_store is None:
            return
        x, y, width, height = bbox
        current_value = self.tree.set(item, "device")

        self._destroy_edit_widget()
        combo = ttk.Combobox(
            self.tree, state="readonly",
            values=self.device_store.known_names_for(self._distinct_device_ids()),
        )
        combo.set(current_value)
        combo.place(x=x, y=y, width=width, height=height)
        combo.focus_set()

        def commit(_event=None) -> None:
            new_friendly = combo.get()
            self._destroy_edit_widget()
            if new_friendly == current_value:
                return
            self._commit_edit(item, row, "device", current_value, new_friendly)

        def cancel(_event=None) -> None:
            self._destroy_edit_widget()

        combo.bind("<<ComboboxSelected>>", commit)
        combo.bind("<Escape>", cancel)
        combo.bind("<FocusOut>", commit)
        self._edit_widget = combo

    def _destroy_edit_widget(self) -> None:
        if self._edit_widget is not None:
            widget = self._edit_widget
            self._edit_widget = None
            widget.destroy()

    def _commit_edit(self, item: str, row: BindingRow, col_name: str,
                      old_display_value: str, new_display_value: str) -> None:
        """Apply an edit coming from the UI, recording it for undo."""
        field_name = COLUMN_TO_FIELD[col_name]

        if col_name == "device":
            old_raw = row.device_id
            new_raw = self.device_store.id_for_name(self._distinct_device_ids(), new_display_value)
            if new_raw is None:
                new_raw = new_display_value  # shouldn't happen - dropdown is restricted
        elif col_name == "key":
            old_raw, new_raw = row.key, new_display_value
        elif col_name == "modifiers":
            old_raw, new_raw = row.modifiers, new_display_value
        else:  # inverted
            old_raw, new_raw = row.inverted, new_display_value

        if not self._apply_and_refresh(item, row, field_name, new_raw):
            return

        self.undo_stack.append(EditCommand(item, row, field_name, old_raw, new_raw))
        self.redo_stack.clear()
        self._mark_dirty_from_stack()
        self.status_var.set(f"Edited {row.label} ({row.slot}) - not saved yet")

    def _apply_and_refresh(self, item: str, row: BindingRow, field_name: str, value: str) -> bool:
        try:
            apply_edit(row, field_name, value)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid edit", str(exc))
            return False
        if field_name == "device_id" and self.device_store is not None:
            row.device_name = self.device_store.name_for(row.device_id)
        self._refresh_row_display(item, row)
        return True

    def _mark_dirty_from_stack(self) -> None:
        self.dirty = len(self.undo_stack) != self._save_mark
        self._update_title()

    # ------------------------------------------------------------- undo/redo

    def undo(self) -> None:
        if not self.undo_stack:
            return
        cmd = self.undo_stack.pop()
        if self._apply_and_refresh(cmd.item, cmd.row, cmd.field_name, cmd.old_value):
            self.redo_stack.append(cmd)
            self._mark_dirty_from_stack()
            self.status_var.set(f"Undid edit to {cmd.row.label} ({cmd.row.slot})")

    def redo(self) -> None:
        if not self.redo_stack:
            return
        cmd = self.redo_stack.pop()
        if self._apply_and_refresh(cmd.item, cmd.row, cmd.field_name, cmd.new_value):
            self.undo_stack.append(cmd)
            self._mark_dirty_from_stack()
            self.status_var.set(f"Redid edit to {cmd.row.label} ({cmd.row.slot})")

    # ---------------------------------------------------------------- save

    def save(self) -> None:
        if self.tree_xml is None or self.path is None:
            return
        try:
            backup = save_binds(self.tree_xml, self.path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return

        self._save_mark = len(self.undo_stack)
        self.dirty = False
        self._update_title()
        msg = f"Saved to {self.path.name}"
        if backup is not None:
            msg += f" (backup: {backup.name})"
        self.status_var.set(msg)

    # ---------------------------------------------------------------- pdf

    def prompt_export_pdf(self) -> None:
        if not self.rows:
            messagebox.showwarning("Nothing to export", "Open a .binds file first.")
            return
        default_name = f"{self.path.stem}_bindings.pdf" if self.path else "bindings.pdf"
        chosen = filedialog.asksaveasfilename(
            title="Export bindings as PDF",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF files", "*.pdf")],
        )
        if not chosen:
            return

        preset_name = self.tree_xml.getroot().get("PresetName", "Elite Dangerous Bindings") if self.tree_xml else "Bindings"
        try:
            export_pdf(self.rows, preset_name, Path(chosen))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_var.set(f"Exported PDF to {chosen}")

    # ---------------------------------------------------------- device names

    def open_device_names_dialog(self) -> None:
        if self.device_store is None:
            messagebox.showwarning("No file loaded", "Open a .binds file first.")
            return
        DeviceNamesDialog(self.root, self)


class DeviceNamesDialog(tk.Toplevel):
    """Lets the user type a name for any device ID, real or unresolved."""

    def __init__(self, parent: tk.Tk, app: BindsEditorApp):
        super().__init__(parent)
        self.app = app
        self.title("Device Names")
        self.geometry("520x360")
        self.transient(parent)

        intro = ttk.Label(
            self,
            text=(
                "One row per device ID found in the loaded file. Names are "
                "auto-detected from Windows where possible; type an override "
                "for any device you'd like named differently (or unresolved IDs)."
            ),
            wraplength=490, justify="left", padding=10,
        )
        intro.pack(fill="x")

        table_frame = ttk.Frame(self, padding=(10, 0))
        table_frame.pack(fill="both", expand=True)

        columns = ("device_id", "current", "override")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree.heading("device_id", text="Device ID")
        self.tree.heading("current", text="Current name")
        self.tree.heading("override", text="Override")
        self.tree.column("device_id", width=110, anchor="w")
        self.tree.column("current", width=190, anchor="w")
        self.tree.column("override", width=180, anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_double_click)
        self._edit_entry: tk.Entry | None = None

        store = app.device_store
        for device_id in app._distinct_device_ids():
            if store.is_generic(device_id):
                continue
            current = store.name_for(device_id)
            override = current if store.has_override(device_id) else ""
            self.tree.insert("", "end", iid=device_id, values=(device_id, current, override))

        button_bar = ttk.Frame(self, padding=10)
        button_bar.pack(fill="x")
        ttk.Button(button_bar, text="Save", command=self._save).pack(side="right")
        ttk.Button(button_bar, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 6))

    def _on_double_click(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not item or col_id != "#3":  # only "override" is editable
            return
        bbox = self.tree.bbox(item, col_id)
        if not bbox:
            return
        x, y, width, height = bbox

        if self._edit_entry is not None:
            self._edit_entry.destroy()

        entry = tk.Entry(self.tree)
        entry.insert(0, self.tree.set(item, "override"))
        entry.select_range(0, "end")
        entry.focus_set()
        entry.place(x=x, y=y, width=width, height=height)

        def commit(_event=None) -> None:
            self.tree.set(item, "override", entry.get())
            entry.destroy()
            self._edit_entry = None

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", lambda _e: (entry.destroy(), setattr(self, "_edit_entry", None)))
        entry.bind("<FocusOut>", commit)
        self._edit_entry = entry

    def _save(self) -> None:
        store = self.app.device_store
        for device_id in self.tree.get_children():
            override = self.tree.set(device_id, "override").strip()
            store.set_override(device_id, override)
        store.save()

        resolve_device_names(self.app.rows, store.name_for)
        self.app._populate_table()
        self.app.status_var.set("Device names updated.")
        self.destroy()


def find_binds_files(search_root: Path) -> list[Path]:
    return sorted(search_root.glob("**/*.binds"))


def run(initial_path: Path | None = None) -> None:
    root = tk.Tk()
    root.geometry("1100x650")
    app = BindsEditorApp(root, initial_path=initial_path)

    if initial_path is None:
        project_root = Path(__file__).resolve().parents[3]
        candidates = find_binds_files(project_root)
        if len(candidates) == 1:
            app.open_file(candidates[0])
        elif len(candidates) > 1:
            app.status_var.set(
                f"Found {len(candidates)} .binds files - use File > Open to pick one."
            )

    root.mainloop()

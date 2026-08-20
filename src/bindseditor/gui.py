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

from .config import AppConfig
from .devices import DeviceNameStore, device_sort_key, name_store_path_for
from .parser import (
    BindingRow,
    apply_edit,
    extract_rows,
    format_key_and_modifiers,
    load_binds,
    resolve_device_names,
    save_binds,
)
from .pdf_export import export_pdf

EDITABLE_COLUMNS = {"device", "key", "modifiers", "secondary_key", "inverted"}
COLUMNS = ("device", "action", "key", "modifiers", "secondary_key", "inverted")
COLUMN_HEADINGS = {
    "device": "Device",
    "action": "Action",
    "key": "Key",
    "modifiers": "Modifiers",
    "secondary_key": "Secondary key",
    "inverted": "Inverted",
}
COLUMN_TO_FIELD = {
    "device": "device_id",
    "key": "key",
    "modifiers": "modifiers",
    "secondary_key": "secondary_key",
    "inverted": "inverted",
}
SORTABLE_COLUMNS = {"device", "action"}


@dataclass
class EditCommand:
    item: str
    row: BindingRow
    field_name: str
    old_value: str
    new_value: str


class BindsEditorApp:
    def __init__(self, root: tk.Tk, initial_path: Path | None = None,
                 config: AppConfig | None = None):
        self.root = root
        self.config = config if config is not None else AppConfig()
        self.tree_xml = None
        self.rows: list[BindingRow] = []
        self.path: Path | None = None
        self.device_store: DeviceNameStore | None = None
        self.dirty = False

        self.undo_stack: list[EditCommand] = []
        self.redo_stack: list[EditCommand] = []
        self._save_mark = 0  # len(undo_stack) at last save

        self._device_sort_reverse = False
        self._action_sort_reverse = False

        self._build_menu()
        self._build_table()
        self._build_statusbar()
        self._update_sort_indicators()

        if initial_path is not None:
            self.open_file(initial_path)

    # ------------------------------------------------------------------ UI

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .binds file...", command=self.prompt_open_file)
        file_menu.add_command(label="Bindings Folder...", command=self.prompt_change_bindings_folder)
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
        self.tree.column("#0", width=24, minwidth=24, stretch=False)  # collapse/expand arrow
        for col in COLUMNS:
            if col in SORTABLE_COLUMNS:
                self.tree.heading(col, text=COLUMN_HEADINGS[col],
                                   command=lambda c=col: self._toggle_sort(c))
            else:
                self.tree.heading(col, text=COLUMN_HEADINGS[col])
        self.tree.column("device", width=150, anchor="w")
        self.tree.column("action", width=210, anchor="w")
        self.tree.column("key", width=140, anchor="w")
        self.tree.column("modifiers", width=170, anchor="w")
        self.tree.column("secondary_key", width=190, anchor="w")
        self.tree.column("inverted", width=65, anchor="center")

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("group", background="#e8e8e8", font=("TkDefaultFont", 9, "bold"))

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda _e: self._hide_tooltip())

        self._row_by_item: dict[str, BindingRow] = {}
        self._edit_widget: tk.Entry | ttk.Combobox | None = None

        self._tooltip_win: tk.Toplevel | None = None
        self._tooltip_after_id: str | None = None
        self._tooltip_cell: tuple[str, str] | None = None

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="No file loaded.")
        bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(6, 2))
        bar.pack(side="bottom", fill="x")

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Editing help",
            "Double-click a Device, Key, Modifiers, Secondary key, or Inverted\n"
            "cell to edit it. Device is a dropdown of known devices - no free\n"
            "text entry. Secondary key shows the action's second binding (if\n"
            "any); type 'Key' or 'Key + Modifier + Modifier' to set it, or\n"
            "clear the cell to remove it.\n\n"
            "Hover any cell to see its full content in a tooltip.\n\n"
            "Click the Device or Action column headers to sort. Click the\n"
            "arrow next to a device group to collapse/expand it.\n\n"
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
            initialdir=str(self.config.get_bindings_dir()),
            filetypes=[(".binds files", "*.binds"), ("All files", "*.*")],
        )
        if chosen:
            self.open_file(Path(chosen))

    def prompt_change_bindings_folder(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose Elite Dangerous bindings folder",
            initialdir=str(self.config.get_bindings_dir()),
        )
        if not chosen:
            return
        self.config.set_bindings_dir(Path(chosen))
        self.status_var.set(f"Bindings folder set to {chosen}")
        if messagebox.askyesno("Open a file?", "Open a .binds file from the new folder now?"):
            dialog = BindsChooserDialog(self.root, self.config)
            self.root.wait_window(dialog)
            if dialog.result is not None:
                self.open_file(dialog.result)

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
        ids: set[str] = set()
        for row in self.rows:
            ids.add(row.device_id)
            if row.secondary_device_id:
                ids.add(row.secondary_device_id)
        return sorted(ids)

    # --------------------------------------------------------------- table

    def _toggle_sort(self, col: str) -> None:
        if col == "device":
            self._device_sort_reverse = not self._device_sort_reverse
        elif col == "action":
            self._action_sort_reverse = not self._action_sort_reverse
        self._populate_table()
        self._update_sort_indicators()

    def _update_sort_indicators(self) -> None:
        device_arrow = "▼" if self._device_sort_reverse else "▲"
        action_arrow = "▼" if self._action_sort_reverse else "▲"
        self.tree.heading("device", text=f"{COLUMN_HEADINGS['device']} {device_arrow}")
        self.tree.heading("action", text=f"{COLUMN_HEADINGS['action']} {action_arrow}")

    def _populate_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_by_item.clear()

        groups: dict[str, list[BindingRow]] = {}
        for row in self.rows:
            groups.setdefault(row.device_name, []).append(row)

        for device_name in sorted(groups.keys(), key=device_sort_key,
                                   reverse=self._device_sort_reverse):
            device_rows = sorted(groups[device_name], key=lambda r: r.label,
                                  reverse=self._action_sort_reverse)
            group_item = self.tree.insert(
                "", "end", text="",
                values=(device_name, f"{len(device_rows)} binding(s)", "", "", "", ""),
                tags=("group",), open=True,
            )
            for row in device_rows:
                item = self.tree.insert(
                    group_item, "end", text="",
                    values=(
                        row.device_name, row.label, row.key, row.modifiers,
                        format_key_and_modifiers(row.secondary_key, row.secondary_modifiers),
                        row.inverted,
                    ),
                )
                self._row_by_item[item] = row

    def _refresh_row_display(self, item: str, row: BindingRow) -> None:
        self.tree.set(item, "device", row.device_name)
        self.tree.set(item, "key", row.key)
        self.tree.set(item, "modifiers", row.modifiers)
        self.tree.set(item, "secondary_key",
                       format_key_and_modifiers(row.secondary_key, row.secondary_modifiers))
        self.tree.set(item, "inverted", row.inverted)

    def _update_title(self) -> None:
        name = self.path.name if self.path else "(no file)"
        star = "*" if self.dirty else ""
        self.root.title(f"Elite Dangerous Binds Editor - {name}{star}")

    # ------------------------------------------------------------- tooltip

    def _on_tree_motion(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        cell = (item, col_id)
        if cell == self._tooltip_cell:
            return
        self._cancel_tooltip()
        self._tooltip_cell = cell
        if not item or not col_id or col_id == "#0":
            return
        x_root, y_root = event.x_root, event.y_root
        self._tooltip_after_id = self.root.after(
            500, lambda: self._show_tooltip(item, col_id, x_root, y_root)
        )

    def _show_tooltip(self, item: str, col_id: str, x_root: int, y_root: int) -> None:
        self._tooltip_after_id = None
        try:
            col_index = int(col_id.replace("#", "")) - 1
            col_name = COLUMNS[col_index]
        except (ValueError, IndexError):
            return
        text = self.tree.set(item, col_name)
        if not text:
            return

        self._destroy_tooltip()
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        label = tk.Label(
            win, text=text, background="#ffffe0", relief="solid", borderwidth=1,
            font=("TkDefaultFont", 9), padx=4, pady=2, justify="left", wraplength=420,
        )
        label.pack()
        win.geometry(f"+{x_root + 12}+{y_root + 16}")
        self._tooltip_win = win

    def _cancel_tooltip(self) -> None:
        if self._tooltip_after_id is not None:
            self.root.after_cancel(self._tooltip_after_id)
            self._tooltip_after_id = None
        self._destroy_tooltip()

    def _destroy_tooltip(self) -> None:
        if self._tooltip_win is not None:
            self._tooltip_win.destroy()
            self._tooltip_win = None

    def _hide_tooltip(self) -> None:
        self._tooltip_cell = None
        self._cancel_tooltip()

    # ---------------------------------------------------------------- edit

    def _on_double_click(self, event: tk.Event) -> None:
        self._hide_tooltip()

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
        elif col_name == "secondary_key":
            old_raw = format_key_and_modifiers(row.secondary_key, row.secondary_modifiers)
            new_raw = new_display_value
        else:  # inverted
            old_raw, new_raw = row.inverted, new_display_value

        if not self._apply_and_refresh(item, row, field_name, new_raw):
            return

        self.undo_stack.append(EditCommand(item, row, field_name, old_raw, new_raw))
        self.redo_stack.clear()
        self._mark_dirty_from_stack()
        self.status_var.set(f"Edited {row.label} - not saved yet")

    def _apply_and_refresh(self, item: str, row: BindingRow, field_name: str, value: str) -> bool:
        try:
            apply_edit(row, field_name, value)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid edit", str(exc))
            return False
        if self.device_store is not None:
            if field_name == "device_id":
                row.device_name = self.device_store.name_for(row.device_id)
            elif field_name == "secondary_key" and row.secondary_device_id:
                row.secondary_device_name = self.device_store.name_for(row.secondary_device_id)
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
            self.status_var.set(f"Undid edit to {cmd.row.label}")

    def redo(self) -> None:
        if not self.redo_stack:
            return
        cmd = self.redo_stack.pop()
        if self._apply_and_refresh(cmd.item, cmd.row, cmd.field_name, cmd.new_value):
            self.undo_stack.append(cmd)
            self._mark_dirty_from_stack()
            self.status_var.set(f"Redid edit to {cmd.row.label}")

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


BINDS_GLOB_PATTERN = "*.4.*.binds"  # Elite Dangerous preset filenames: <Name>.<MajorVersion>.<MinorVersion>.binds


def find_binds_presets(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(BINDS_GLOB_PATTERN))


class BindsChooserDialog(tk.Toplevel):
    """Startup dialog: pick which .binds preset to open from the bindings folder."""

    def __init__(self, parent: tk.Tk, config: AppConfig):
        super().__init__(parent)
        self.config = config
        self.result: Path | None = None
        self._files: list[Path] = []

        self.title("Open Elite Dangerous Bindings")
        self.geometry("560x400")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.dir_var = tk.StringVar(value=str(self.config.get_bindings_dir()))

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Bindings folder:").pack(anchor="w")
        dir_row = ttk.Frame(top)
        dir_row.pack(fill="x", pady=(2, 0))
        ttk.Entry(dir_row, textvariable=self.dir_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(dir_row, text="Change...", command=self._change_folder).pack(
            side="left", padx=(6, 0)
        )

        list_frame = ttk.Frame(self, padding=(10, 6))
        list_frame.pack(fill="both", expand=True)
        ttk.Label(list_frame, text=f"Matching preset files ({BINDS_GLOB_PATTERN}):").pack(anchor="w")
        self.listbox = tk.Listbox(list_frame)
        self.listbox.pack(fill="both", expand=True, pady=(2, 0))
        self.listbox.bind("<Double-1>", lambda _e: self._choose())

        button_bar = ttk.Frame(self, padding=10)
        button_bar.pack(fill="x")
        ttk.Button(button_bar, text="Browse for a file...", command=self._browse_file).pack(side="left")
        ttk.Button(button_bar, text="Open", command=self._choose).pack(side="right")
        ttk.Button(button_bar, text="Cancel", command=self._cancel).pack(side="right", padx=(0, 6))

        self._refresh_list()

    def _refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        self._files = find_binds_presets(Path(self.dir_var.get()))
        for f in self._files:
            self.listbox.insert("end", f.name)
        if not self._files:
            self.listbox.insert("end", "(no matching files found in this folder)")

    def _change_folder(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose Elite Dangerous bindings folder", initialdir=self.dir_var.get()
        )
        if chosen:
            self.dir_var.set(chosen)
            self.config.set_bindings_dir(Path(chosen))
            self._refresh_list()

    def _browse_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Open Elite Dangerous .binds file",
            initialdir=self.dir_var.get(),
            filetypes=[(".binds files", "*.binds"), ("All files", "*.*")],
        )
        if chosen:
            self.result = Path(chosen)
            self.destroy()

    def _choose(self) -> None:
        selection = self.listbox.curselection()
        if not selection or not self._files:
            return
        self.result = self._files[selection[0]]
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def run(initial_path: Path | None = None) -> None:
    root = tk.Tk()
    root.geometry("1150x650")

    config = AppConfig()
    app = BindsEditorApp(root, config=config)

    chosen = initial_path
    if chosen is None:
        # Withdrawing root first would make the picker (transient to it) a
        # child of an unmapped window - on Windows that can leave it
        # invisible and stuck with no way to close it. Keep root visible.
        dialog = BindsChooserDialog(root, config)
        root.wait_window(dialog)
        chosen = dialog.result

    if chosen is not None:
        app.open_file(chosen)
    else:
        app.status_var.set("No file opened - use File > Open to pick one.")

    root.mainloop()

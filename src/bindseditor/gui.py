"""Tkinter GUI for viewing and editing an Elite Dangerous .binds file.

Editing is done by double-clicking a cell and typing a new value - there is
no "press a button to bind" capture anywhere in this tool, by design.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .devices import device_sort_key
from .parser import BindingRow, apply_edit, extract_rows, load_binds, save_binds
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


class BindsEditorApp:
    def __init__(self, root: tk.Tk, initial_path: Path | None = None):
        self.root = root
        self.tree_xml = None
        self.rows: list[BindingRow] = []
        self.path: Path | None = None
        self.dirty = False

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
        file_menu.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export PDF...", command=self.prompt_export_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Editing help", command=self._show_help)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda _e: self.save())

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
        self._edit_entry: tk.Entry | None = None

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="No file loaded.")
        bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(6, 2))
        bar.pack(side="bottom", fill="x")

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Editing help",
            "Double-click a Device, Key, Modifiers, or Inverted cell to edit it as text.\n\n"
            "Key / Modifiers use Elite Dangerous's internal names, e.g.:\n"
            "  Key_A, Key_LeftAlt, Key_RightControl, Joy_1, Joy_XAxis\n\n"
            "Modifiers: comma-separated list, e.g. Key_LeftAlt,Key_RightControl\n\n"
            "Inverted: type Yes or No (axis bindings only).\n\n"
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
        self.rows = extract_rows(tree_xml)
        self.dirty = False
        self._populate_table()
        self._update_title()
        self.status_var.set(f"Loaded {len(self.rows)} bound entries from {path.name}")

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
        x, y, width, height = bbox

        row = self._row_by_item[item]
        current_value = self.tree.set(item, col_name)

        self._destroy_edit_entry()
        entry = tk.Entry(self.tree)
        entry.insert(0, current_value)
        entry.select_range(0, "end")
        entry.focus_set()
        entry.place(x=x, y=y, width=width, height=height)

        def commit(_event=None) -> None:
            new_value = entry.get()
            self._destroy_edit_entry()
            if new_value == current_value:
                return
            self._apply_cell_edit(item, row, col_name, new_value)

        def cancel(_event=None) -> None:
            self._destroy_edit_entry()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)
        self._edit_entry = entry

    def _destroy_edit_entry(self) -> None:
        if self._edit_entry is not None:
            entry = self._edit_entry
            self._edit_entry = None
            entry.destroy()

    def _apply_cell_edit(self, item: str, row: BindingRow, col_name: str, new_value: str) -> None:
        field_name = COLUMN_TO_FIELD[col_name]
        try:
            apply_edit(row, field_name, new_value)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid edit", str(exc))
            return

        self.tree.set(item, "device", row.device_name)
        self.tree.set(item, "key", row.key)
        self.tree.set(item, "modifiers", row.modifiers)
        self.tree.set(item, "inverted", row.inverted)

        self.dirty = True
        self._update_title()
        self.status_var.set(f"Edited {row.label} ({row.slot}) - not saved yet")

    # ---------------------------------------------------------------- save

    def save(self) -> None:
        if self.tree_xml is None or self.path is None:
            return
        try:
            backup = save_binds(self.tree_xml, self.path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return

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

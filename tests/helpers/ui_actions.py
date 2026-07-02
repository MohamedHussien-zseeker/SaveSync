"""Reusable UI interaction wrappers for workflow tests.

Provides stable, intent-based helpers for common UI operations
so workflow tests read as scenarios rather than Tkinter plumbing.
"""
import tkinter as tk
from tkinter import ttk


def select_tab(notebook: ttk.Notebook, index: int) -> None:
    notebook.select(index)


def click_button(button: ttk.Button) -> None:
    button.invoke()


def set_entry_text(entry: tk.Entry, text: str) -> None:
    entry.delete(0, tk.END)
    entry.insert(0, text)


def select_tree_item(tree: ttk.Treeview, item_id: str) -> None:
    tree.selection_set(item_id)
    tree.focus(item_id)
    tree.event_generate("<<TreeviewSelect>>")


def select_listbox_item(listbox: tk.Listbox, index: int) -> None:
    listbox.selection_clear(0, tk.END)
    listbox.selection_set(index)
    listbox.activate(index)
    listbox.event_generate("<<ListboxSelect>>")

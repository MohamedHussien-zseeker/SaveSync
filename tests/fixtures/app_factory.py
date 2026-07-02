"""Create a SaveSync test app instance for workflow testing."""
import tkinter as tk
from tkinter import ttk


def _walk_children(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_children(child)


def find_notebook(root):
    for w in _walk_children(root):
        if isinstance(w, ttk.Notebook):
            return w
    return None


def find_button(root, text):
    for w in _walk_children(root):
        if isinstance(w, ttk.Button) and w.cget("text") == text:
            return w
    return None


def find_label(root, text_hint):
    for w in _walk_children(root):
        if isinstance(w, ttk.Label) and text_hint in (w.cget("text") or ""):
            return w
    return None


def find_treeview(root):
    for w in _walk_children(root):
        if isinstance(w, ttk.Treeview):
            return w
    return None


def find_listbox(root):
    for w in _walk_children(root):
        if isinstance(w, tk.Listbox):
            return w
    return None


def find_scrolled_text(root):
    for w in _walk_children(root):
        if isinstance(w, tk.Text):
            return w
    return None


def find_labelframe(root, text):
    for w in _walk_children(root):
        if isinstance(w, ttk.LabelFrame) and w.cget("text") == text:
            return w
    return None


def find_label_containing(root, substring):
    for w in _walk_children(root):
        if isinstance(w, ttk.Label) and substring in (w.cget("text") or ""):
            return w
    return None


def find_progressbar(root):
    for w in _walk_children(root):
        if isinstance(w, ttk.Progressbar):
            return w
    return None


def get_tab_labels(notebook):
    return [notebook.tab(i, "text") for i in range(notebook.index("end"))]


def create_app(tmp_path, monkeypatch):
    """Build a SaveSync test app and return widget references.

    Patches config directories to tmp_path, prevents mainloop
    from blocking, and returns (root, refs_dict).

    refs_dict contains: notebook, tree, dir_list, log_area,
    and named buttons/labels keyed by their text.
    """
    config_dir = tmp_path / ".config" / "savesync"
    monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
    monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
    import core
    core.ACCOUNTS_FILE = config_dir / "accounts.json"

    saved = tk.Tk.mainloop
    roots = []

    def _noop_mainloop(self):
        roots.append(self)

    tk.Tk.mainloop = _noop_mainloop

    try:
        import SaveSync
        SaveSync._main_impl()
        root = roots[0] if roots else tk._default_root
        if root is None:
            raise RuntimeError("No Tk root created")

        root.update()
        refs = _build_refs(root)
        return root, refs
    finally:
        tk.Tk.mainloop = saved


def _build_refs(root):
    refs = {}
    refs["root"] = root
    refs["notebook"] = find_notebook(root)

    for w in _walk_children(root):
        if isinstance(w, ttk.Button):
            text = w.cget("text")
            key = f"btn_{text}"
            refs[key] = w
        if isinstance(w, ttk.Label):
            text = w.cget("text") or ""
            if text:
                key = f"lbl_{text}"
                refs[key] = w

    refs["tree"] = find_treeview(root)
    refs["dir_list"] = find_listbox(root)

    for w in _walk_children(root):
        if isinstance(w, tk.Text):
            refs["log_area"] = w
            break

    return refs

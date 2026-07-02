"""Create a SaveSync test app instance for workflow testing."""
import tkinter as tk
import customtkinter as ctk


def _walk_children(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_children(child)


def find_notebook(root):
    return None


def find_button(root, text):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkButton) and w.cget("text") == text:
            return w
    return None


def find_label(root, text_hint):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkLabel) and text_hint in (w.cget("text") or ""):
            return w
    return None


def find_treeview(root):
    return None


def find_listbox(root):
    return None


def find_scrolled_text(root):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkTextbox):
            return w
    return None


def find_labelframe(root, text):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkLabel) and text in (w.cget("text") or ""):
            parent = w.master
            if parent and isinstance(parent, (ctk.CTkFrame, ctk.CTkScrollableFrame)):
                return parent
    return None


def find_label_containing(root, substring):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkLabel) and substring in (w.cget("text") or ""):
            return w
    return None


def find_progressbar(root):
    for w in _walk_children(root):
        if isinstance(w, ctk.CTkProgressBar):
            return w
    return None


def get_tab_labels(app):
    return list(app.nav_btns.keys())


def create_app(tmp_path, monkeypatch):
    """Build a SaveSync test app and return widget references.

    Patches config directories to tmp_path, prevents mainloop
    from blocking, and returns (root, refs_dict).

    refs_dict contains: app, nav_btns, and named buttons/labels
    keyed by their text.
    """
    config_dir = tmp_path / ".config" / "savesync"
    monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
    monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
    import core
    core.ACCOUNTS_FILE = config_dir / "accounts.json"

    saved = tk.Tk.mainloop

    def _noop_mainloop(self):
        pass

    tk.Tk.mainloop = _noop_mainloop

    try:
        import SaveSync
        app = SaveSync._main_impl()
        root = app.root
        root.update()
        refs = _build_refs(root, app)
        return root, refs
    finally:
        tk.Tk.mainloop = saved


def _build_refs(root, app=None):
    refs = {}
    refs["root"] = root
    if app:
        refs["app"] = app
        refs["nav_btns"] = app.nav_btns

    for w in _walk_children(root):
        if isinstance(w, ctk.CTkButton):
            text = w.cget("text")
            key = f"btn_{text}"
            refs[key] = w
        if isinstance(w, ctk.CTkLabel):
            text = w.cget("text") or ""
            if text:
                key = f"lbl_{text}"
                refs[key] = w
        if isinstance(w, ctk.CTkTextbox):
            if "log_area" not in refs:
                refs["log_area"] = w
        if isinstance(w, ctk.CTkProgressBar):
            refs["progress"] = w

    return refs

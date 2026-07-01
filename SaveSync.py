#!/usr/bin/env python3
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

__version__ = "2.4.0-beta1"


def _self_test():
    """Import and init all modules without opening the GUI. Replaces --version for deeper validation."""
    errors = []
    modules = [
        ("credential_store", "get_credential_store, redact_secrets"),
        ("providers", "get_provider_registry"),
        ("config_sync", "ConfigSync, SyncConfig, _get_device_id"),
        ("core", "SaveSyncCore, Profile, SaveSyncDaemon"),
        ("cloud", "create_provider, LocalFolder"),
        ("logging_system", "get_logging_system"),
    ]
    for mod_name, names in modules:
        try:
            m = __import__(mod_name)
            for n in names.split(", "):
                n = n.strip()
                if n and not hasattr(m, n):
                    errors.append(f"{mod_name} missing {n}")
        except Exception as e:
            errors.append(f"{mod_name} import failed: {e}")

    if not errors:
        try:
            from credential_store import get_credential_store
            store = get_credential_store()
            store.name()
            from config_sync import _get_device_id
            _get_device_id()
            from providers import get_provider_registry
            registry = get_provider_registry()
            registry.list_providers()
        except Exception as e:
            errors.append(f"init failed: {e}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"SaveSync v{__version__} self-test: OK")
    print(f"  credential store: {get_credential_store().name()}")
    print(f"  device id: {_get_device_id()}")
    providers = get_provider_registry().list_providers()
    for p in providers:
        print(f"  provider: {p['name']} ({p['display_name']})")


def _startup_log(entry: str):
    """Write a crash-log entry to %APPDATA%\\SaveSync\\startup.log or equivalent."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent.resolve()
    else:
        base = Path(sys.argv[0]).parent.resolve() if sys.argv[0] else Path.cwd()
    try:
        test = base / ".writable_test"
        test.touch()
        test.unlink()
        log_dir = base
    except (OSError, PermissionError):
        if sys.platform == "win32":
            log_dir = Path(os.environ.get("APPDATA",
                                          Path.home() / "AppData" / "Roaming")) / "SaveSync"
        else:
            log_dir = Path(os.environ.get("XDG_DATA_HOME",
                                          Path.home() / ".local" / "share")) / "SaveSync"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "startup.log"
    try:
        with open(str(log_file), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {entry}\n")
    except Exception:
        pass


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"SaveSync v{__version__}")
        return

    if "--self-test" in sys.argv:
        _self_test()
        return

    _startup_log("starting")
    _sync_now_flag = "--sync-now" in sys.argv
    _cancel_after = None
    _close_after = None
    try:
        idx = sys.argv.index("--cancel-after")
        _cancel_after = float(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
    try:
        idx = sys.argv.index("--close-after")
        _close_after = float(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
    try:
        _main_impl(_sync_now_flag, _cancel_after, _close_after)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        _startup_log(f"CRASH: {tb}")
        raise


def _main_impl(sync_now_flag=False, cancel_after=None, close_after=None):
    import tkinter as tk
    from tkinter import ttk, scrolledtext, filedialog, messagebox
    from core import SaveSyncCore, SaveSyncDaemon, SyncWorker, Profile, GuiLogHandler, setup_file_logger
    from logging_system import get_logging_system, shutdown as log_shutdown
    from credential_store import get_credential_store, redact_secrets
    from providers import (
        Account, OAuthResult, ProviderRegistry, get_provider_registry,
        LocalAdapter, DropboxAdapter, GoogleDriveAdapter, OneDriveAdapter,
    )
    from config_sync import ConfigSync, SyncConfig, DeviceConfig, _get_device_id

    core = SaveSyncCore()
    log = get_logging_system()

    root = tk.Tk()
    root.title("SaveSync")
    root.geometry("960x720")
    root.minsize(800, 600)

    BG = "#1a1b26"
    BG2 = "#24253a"
    BG3 = "#1e1f34"
    FG = "#c0caf5"
    FG2 = "#a9b1d6"
    ACCENT = "#7aa2f7"
    GREEN = "#9ece6a"
    RED = "#f7768e"
    YELLOW = "#e0af68"
    BORDER = "#3b4261"
    SEL_BG = "#2f3b6b"

    style = ttk.Style()
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=FG, fieldbackground=BG2,
                    selectbackground=SEL_BG, selectforeground=FG,
                    borderwidth=0, focuscolor="")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
    style.configure("TButton", background=BG2, foreground=FG, font=("Segoe UI", 9),
                    borderwidth=1, relief="flat", padding=(12, 6))
    style.map("TButton",
              background=[("active", SEL_BG), ("pressed", ACCENT)],
              foreground=[("active", FG)])
    style.configure("Primary.TButton", background=ACCENT, foreground=BG,
                    font=("Segoe UI", 10, "bold"), padding=(16, 8))
    style.map("Primary.TButton",
              background=[("active", "#89b4fa"), ("pressed", "#5a8cf5")],
              foreground=[("active", BG)])
    style.configure("Destructive.TButton", background="#3b1f2e", foreground=RED,
                    font=("Segoe UI", 9), padding=(12, 6))
    style.map("Destructive.TButton",
              background=[("active", "#4c2435"), ("pressed", "#5a293c")],
              foreground=[("active", RED)])
    style.configure("Small.TButton", font=("Segoe UI", 8), padding=(8, 3))
    style.configure("TEntry", fieldbackground=BG2, foreground=FG, insertcolor=FG,
                    borderwidth=1, relief="solid", padding=6)
    style.configure("TCombobox", fieldbackground=BG2, foreground=FG,
                    selectbackground=SEL_BG, arrowcolor=FG, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", BG2)])
    style.configure("Treeview", background=BG2, foreground=FG, fieldbackground=BG2,
                    rowheight=32, font=("Segoe UI", 9))
    style.map("Treeview", background=[("selected", SEL_BG)],
              foreground=[("selected", FG)])
    style.configure("Treeview.Heading", background=BG, foreground=FG2,
                    font=("Segoe UI", 9, "bold"), borderwidth=0,
                    relief="flat", padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", BG2)])
    style.configure("Header.TLabel", background=BG, foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
    style.configure("Section.TLabel", background=BG, foreground=FG2,
                    font=("Segoe UI", 9, "bold"))
    style.configure("Empty.TLabel", background=BG, foreground="#565f89",
                    font=("Segoe UI", 9))
    style.configure("StatusBar.TLabel", background=BG2, foreground=FG2,
                    font=("Segoe UI", 9))
    style.configure("Card.TFrame", background=BG3, relief="solid", borderwidth=1)
    style.configure("CardLabel.TLabel", background=BG3, foreground=FG,
                    font=("Segoe UI", 10))
    style.configure("CardHeader.TLabel", background=BG3, foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
    style.configure("CardEmpty.TLabel", background=BG3, foreground="#565f89",
                    font=("Segoe UI", 9))

    status_bar = ttk.Frame(root, style="TFrame")
    status_bar.pack(fill=tk.X)
    inner_status = ttk.Frame(status_bar, style="TFrame")
    inner_status.pack(fill=tk.X, padx=12, pady=(8, 4))

    status_profile_lbl = ttk.Label(inner_status, text="No profile",
                                   style="StatusBar.TLabel",
                                   foreground=ACCENT, font=("Segoe UI", 9, "bold"))
    status_profile_lbl.pack(side=tk.LEFT, padx=(0, 16))
    status_provider_lbl = ttk.Label(inner_status, text="", style="StatusBar.TLabel")
    status_provider_lbl.pack(side=tk.LEFT, padx=(0, 16))
    status_folders_lbl = ttk.Label(inner_status, text="0 folders",
                                   style="StatusBar.TLabel")
    status_folders_lbl.pack(side=tk.LEFT, padx=(0, 16))
    status_state_lbl = ttk.Label(inner_status, text="● Ready",
                                 foreground=GREEN,
                                 font=("Segoe UI", 9, "bold"))
    status_state_lbl.pack(side=tk.LEFT)
    version_lbl = ttk.Label(inner_status, text=f"v{__version__}",
                            style="StatusBar.TLabel")
    version_lbl.pack(side=tk.RIGHT)

    notebook = ttk.Notebook()
    notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    home_frame = ttk.Frame(notebook)
    profiles_frame = ttk.Frame(notebook)
    accounts_frame = ttk.Frame(notebook)
    activity_frame = ttk.Frame(notebook)
    settings_frame = ttk.Frame(notebook)

    notebook.add(home_frame, text=" Home ")
    notebook.add(profiles_frame, text=" Profiles ")
    notebook.add(accounts_frame, text=" Accounts ")
    notebook.add(activity_frame, text=" Activity ")
    notebook.add(settings_frame, text=" Settings ")

    daemon_ref = [None]
    sync_worker_ref = [None]
    current_profile = [core.profiles[0] if core.profiles else None]
    config_sync = ConfigSync()

    # ─── Home View ──────────────────────────────────────────────
    home_canvas = tk.Canvas(home_frame, background=BG, borderwidth=0,
                            highlightthickness=0)
    home_scroll = ttk.Scrollbar(home_frame, orient=tk.VERTICAL,
                                command=home_canvas.yview)
    home_canvas.configure(yscrollcommand=home_scroll.set)
    home_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    home_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    home_content = ttk.Frame(home_canvas)
    home_content.bind("<Configure>",
                      lambda e: home_canvas.configure(
                          scrollregion=home_canvas.bbox("all")))
    home_canvas.create_window((0, 0), window=home_content, anchor="nw")

    def _home_mousewheel(event):
        home_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    home_canvas.bind_all("<MouseWheel>", _home_mousewheel, add="+")

    overview_frame = ttk.LabelFrame(home_content, text=" Overview ", padding=12)
    overview_frame.pack(fill=tk.X, pady=(0, 8), padx=8)

    def _stat_row(parent, label, value, row):
        ttk.Label(parent, text=label, style="StatusBar.TLabel",
                  width=12).grid(row=row, column=0, sticky=tk.W, pady=2)
        val_lbl = ttk.Label(parent, text=value, style="StatusValue.TLabel",
                            font=("Segoe UI", 9, "bold"))
        val_lbl.grid(row=row, column=1, sticky=tk.W, pady=2, padx=(8, 0))
        return val_lbl

    overview_grid = ttk.Frame(overview_frame)
    overview_grid.pack(fill=tk.X)
    stat_labels = {}
    for i, (lbl, val) in enumerate([("Profile", ""), ("Provider", ""),
                                    ("Folders", "0"), ("Status", "● Ready")]):
        stat_labels[lbl.lower()] = _stat_row(overview_grid, lbl, val, i)

    actions_frame = ttk.LabelFrame(home_content, text=" Quick Actions ", padding=12)
    actions_frame.pack(fill=tk.X, pady=(0, 8), padx=8)

    qa_row = ttk.Frame(actions_frame)
    qa_row.pack(fill=tk.X)
    sync_now_btn = ttk.Button(qa_row, text="Sync Now", style="Primary.TButton")
    sync_now_btn.pack(side=tk.LEFT, padx=(0, 6))
    start_stop_btn = ttk.Button(qa_row, text="Start Sync", style="TButton")
    start_stop_btn.pack(side=tk.LEFT, padx=(0, 6))
    restore_btn = ttk.Button(qa_row, text="Restore", style="TButton")
    restore_btn.pack(side=tk.LEFT)
    manage_btn = ttk.Button(qa_row, text="Manage Profiles →",
                            style="Small.TButton")
    manage_btn.pack(side=tk.RIGHT)

    # ─── Progress Area ─────────────────────────────────────────
    progress_frame = ttk.LabelFrame(home_content, text=" Progress ", padding=12)
    progress_frame.pack(fill=tk.X, pady=(0, 8), padx=8)

    progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
    progress_bar.pack(fill=tk.X, pady=(0, 6))

    prog_inner = ttk.Frame(progress_frame)
    prog_inner.pack(fill=tk.X)

    file_lbl = ttk.Label(prog_inner, text="", style="StatusBar.TLabel")
    file_lbl.pack(anchor=tk.W)

    info_row = ttk.Frame(prog_inner)
    info_row.pack(fill=tk.X, pady=(2, 0))
    bytes_lbl = ttk.Label(info_row, text="", style="StatusBar.TLabel")
    bytes_lbl.pack(side=tk.LEFT, padx=(0, 16))
    speed_lbl = ttk.Label(info_row, text="", style="StatusBar.TLabel")
    speed_lbl.pack(side=tk.LEFT)

    prog_btns = ttk.Frame(progress_frame)
    prog_btns.pack(fill=tk.X, pady=(6, 0))
    cancel_btn = ttk.Button(prog_btns, text="Cancel Operation",
                            style="Destructive.TButton", state="disabled")
    cancel_btn.pack(side=tk.RIGHT)

    def _reset_progress_area():
        progress_bar.stop()
        progress_bar.configure(mode="indeterminate", value=0)
        file_lbl.configure(text="")
        bytes_lbl.configure(text="")
        speed_lbl.configure(text="")
        cancel_btn.configure(state="disabled")

    _reset_progress_area()

    # ─── Profiles View ──────────────────────────────────────────
    prof_top = ttk.Frame(profiles_frame)
    prof_top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    prof_left = ttk.Frame(prof_top, width=220)
    prof_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
    prof_left.pack_propagate(False)

    ttk.Label(prof_left, text="PROFILES", style="Section.TLabel").pack(
        anchor=tk.W, pady=(0, 4))

    tree_frame = ttk.Frame(prof_left, borderwidth=1, relief="solid")
    tree_frame.pack(fill=tk.BOTH, expand=True)
    tree = ttk.Treeview(tree_frame, columns=("name",), show="headings",
                         height=10, selectmode="browse")
    tree.heading("name", text="")
    tree.column("name", width=210)
    tree.pack(fill=tk.BOTH, expand=True)

    prof_btns = ttk.Frame(prof_left)
    prof_btns.pack(fill=tk.X, pady=(6, 0))
    add_prof_btn = ttk.Button(prof_btns, text="+ New",
                              style="Small.TButton")
    add_prof_btn.pack(side=tk.LEFT, padx=(0, 4))
    del_prof_btn = ttk.Button(prof_btns, text="— Delete",
                              style="Destructive.TButton")
    del_prof_btn.pack(side=tk.LEFT)

    prof_detail = ttk.LabelFrame(prof_top, text=" Profile Details ", padding=12)
    prof_detail.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    g = prof_detail
    ttk.Label(g, text="Name", style="StatusBar.TLabel").grid(
        row=0, column=0, sticky=tk.W, pady=2)
    profile_name_var = tk.StringVar()
    ttk.Label(g, textvariable=profile_name_var,
              style="StatusValue.TLabel").grid(
        row=0, column=1, sticky=tk.W, pady=2, padx=(8, 0))

    ttk.Label(g, text="Provider", style="StatusBar.TLabel").grid(
        row=1, column=0, sticky=tk.W, pady=2)
    prov_desc_var = tk.StringVar()
    ttk.Label(g, textvariable=prov_desc_var, style="StatusValue.TLabel",
              wraplength=400).grid(row=1, column=1, sticky=tk.W, pady=2, padx=(8, 0))

    ttk.Label(g, text="Sync Mode", style="StatusBar.TLabel").grid(
        row=2, column=0, sticky=tk.W, pady=2)
    sync_mode_var = tk.StringVar()
    ttk.Label(g, textvariable=sync_mode_var,
              style="StatusValue.TLabel").grid(
        row=2, column=1, sticky=tk.W, pady=2, padx=(8, 0))
    toggle_mode_btn = ttk.Button(g, text="Toggle", style="Small.TButton")
    toggle_mode_btn.grid(row=2, column=2, padx=(8, 0))

    folders_lbl = ttk.LabelFrame(g, text=" Watched Folders ", padding=8)
    folders_lbl.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))

    dir_list = tk.Listbox(folders_lbl, height=4, bg=BG2, fg=FG,
                          selectbackground=SEL_BG, relief="flat",
                          borderwidth=0, activestyle="none", font=("Segoe UI", 9))
    dir_list.pack(fill=tk.X, pady=(0, 6))

    dir_empty = ttk.Label(dir_list, text="No folders added yet",
                          style="Empty.TLabel")
    dir_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    dir_btns = ttk.Frame(folders_lbl)
    dir_btns.pack(fill=tk.X)
    add_dir_btn = ttk.Button(dir_btns, text="+ Add Save Folder",
                             style="TButton")
    add_dir_btn.pack(side=tk.LEFT, padx=(0, 4))
    rm_dir_btn = ttk.Button(dir_btns, text="— Remove",
                            style="Destructive.TButton")
    rm_dir_btn.pack(side=tk.LEFT)

    dest_lbl = ttk.LabelFrame(g, text=" Sync Destination ", padding=8)
    dest_lbl.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))

    dest_prov = ttk.Label(dest_lbl, textvariable=prov_desc_var,
                          wraplength=500, style="StatusValue.TLabel")
    dest_prov.pack(anchor=tk.W, pady=(0, 6))
    browse_btn = ttk.Button(dest_lbl, text="Browse Destination...",
                            style="TButton")
    browse_btn.pack(anchor=tk.W)
    dest_empty = ttk.Label(dest_lbl, text="No destination configured",
                           style="Empty.TLabel")

    # ─── Accounts View ──────────────────────────────────────────
    acct_top = ttk.Frame(accounts_frame)
    acct_top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    acct_header = ttk.Frame(acct_top)
    acct_header.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(acct_header, text="CONNECTED ACCOUNTS",
              style="Section.TLabel").pack(side=tk.LEFT)
    add_acct_btn = ttk.Button(acct_header, text="+ Connect Account",
                              style="Primary.TButton")
    add_acct_btn.pack(side=tk.RIGHT)

    acct_canvas = tk.Canvas(acct_top, background=BG, borderwidth=0,
                            highlightthickness=0)
    acct_scroll = ttk.Scrollbar(acct_top, orient=tk.VERTICAL,
                                command=acct_canvas.yview)
    acct_canvas.configure(yscrollcommand=acct_scroll.set)
    acct_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    acct_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    acct_content = ttk.Frame(acct_canvas)
    acct_content.bind("<Configure>",
                      lambda e: acct_canvas.configure(
                          scrollregion=acct_canvas.bbox("all")))
    acct_canvas.create_window((0, 0), window=acct_content, anchor="nw")

    def _acct_mousewheel(event):
        acct_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    acct_canvas.bind_all("<MouseWheel>", _acct_mousewheel, add="+")

    # ─── Activity View ──────────────────────────────────────────
    act_top = ttk.Frame(activity_frame)
    act_top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    log_area = scrolledtext.ScrolledText(
        act_top, height=10, font=("Consolas", 9), bg=BG2, fg=FG,
        insertbackground=FG, relief="flat", borderwidth=0,
        selectbackground=SEL_BG, highlightbackground=BORDER,
        highlightcolor=BORDER, highlightthickness=0)
    log_area.pack(fill=tk.BOTH, expand=True)

    log_area.tag_config("INFO", foreground=FG)
    log_area.tag_config("SYNC", foreground=GREEN)
    log_area.tag_config("WARN", foreground=YELLOW)
    log_area.tag_config("ERROR", foreground=RED)

    act_btns = ttk.Frame(act_top)
    act_btns.pack(fill=tk.X, pady=(6, 0))
    clear_log_btn = ttk.Button(act_btns, text="Clear Log",
                               style="Small.TButton")
    clear_log_btn.pack(side=tk.RIGHT)

    # ─── Settings View ──────────────────────────────────────────
    set_canvas = tk.Canvas(settings_frame, background=BG, borderwidth=0,
                           highlightthickness=0)
    set_scroll = ttk.Scrollbar(settings_frame, orient=tk.VERTICAL,
                               command=set_canvas.yview)
    set_canvas.configure(yscrollcommand=set_scroll.set)
    set_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    set_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    set_content = ttk.Frame(set_canvas)
    set_content.bind("<Configure>",
                     lambda e: set_canvas.configure(
                         scrollregion=set_canvas.bbox("all")))
    set_canvas.create_window((0, 0), window=set_content, anchor="nw")

    def _set_mousewheel(event):
        set_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    set_canvas.bind_all("<MouseWheel>", _set_mousewheel, add="+")

    sync_config_frame = ttk.LabelFrame(set_content, text=" Config Sync ",
                                       padding=12)
    sync_config_frame.pack(fill=tk.X, pady=(0, 8), padx=8)

    sync_config_inner = ttk.Frame(sync_config_frame)
    sync_config_inner.pack(fill=tk.X)
    ttk.Label(sync_config_inner, text="Device ID:",
              style="StatusBar.TLabel").grid(row=0, column=0, sticky=tk.W, pady=2)
    device_id_var = tk.StringVar(value=_get_device_id())
    ttk.Label(sync_config_inner, textvariable=device_id_var,
              style="StatusValue.TLabel").grid(row=0, column=1, sticky=tk.W,
                                               pady=2, padx=(8, 0))

    general_frame = ttk.LabelFrame(set_content, text=" General ", padding=12)
    general_frame.pack(fill=tk.X, pady=(0, 8), padx=8)

    general_inner = ttk.Frame(general_frame)
    general_inner.pack(fill=tk.X)
    ttk.Label(general_inner, text="Version:",
              style="StatusBar.TLabel").grid(row=0, column=0, sticky=tk.W, pady=2)
    ttk.Label(general_inner, text=__version__,
              style="StatusValue.TLabel").grid(row=0, column=1, sticky=tk.W,
                                               pady=2, padx=(8, 0))
    ttk.Label(general_inner, text="Credential Store:",
              style="StatusBar.TLabel").grid(row=1, column=0, sticky=tk.W, pady=2)
    cred_store_var = tk.StringVar(value=core.credential_store.name())
    ttk.Label(general_inner, textvariable=cred_store_var,
              style="StatusValue.TLabel").grid(row=1, column=1, sticky=tk.W,
                                               pady=2, padx=(8, 0))

    # ─── Callbacks ──────────────────────────────────────────────

    def _refresh_status_bar():
        p = current_profile[0]
        if p:
            status_profile_lbl.configure(text=p.name)
            prov_type = p.provider_config.get("type", "local")
            status_provider_lbl.configure(text=f"Provider: {prov_type}")
            status_folders_lbl.configure(text=f"{len(p.watch_dirs)} folders")
            if daemon_ref[0] and daemon_ref[0].running:
                status_state_lbl.configure(text="● Running", foreground=GREEN)
            else:
                status_state_lbl.configure(text="● Ready", foreground=GREEN)
        else:
            status_profile_lbl.configure(text="No profile")
            status_provider_lbl.configure(text="")
            status_folders_lbl.configure(text="0 folders")
            status_state_lbl.configure(text="● Ready", foreground=GREEN)

    def _refresh_home():
        p = current_profile[0]
        if p:
            stat_labels["profile"].configure(text=p.name)
            stat_labels["provider"].configure(
                text=p.provider_config.get("type", "local"))
            stat_labels["folders"].configure(text=str(len(p.watch_dirs)))
            if daemon_ref[0] and daemon_ref[0].running:
                stat_labels["status"].configure(text="● Running",
                                                foreground=GREEN)
            else:
                stat_labels["status"].configure(text="● Ready",
                                                foreground=GREEN)
        else:
            for lbl in stat_labels.values():
                lbl.configure(text="—")

    def _refresh_profile_view():
        p = current_profile[0]
        if not p:
            return
        profile_name_var.set(p.name)
        dir_list.delete(0, tk.END)
        for d in p.watch_dirs:
            dir_list.insert(tk.END, d)
        _update_dir_empty_state()
        prov_type = p.provider_config.get("type", "local")
        prov_desc_var.set(_provider_desc(p.provider_config))
        sync_mode_var.set("On-Close" if p.sync_on_close else "Instant")
        _update_dest_empty_state()

    def _update_dir_empty_state():
        if dir_list.size() == 0:
            dir_empty.lift()
        else:
            dir_empty.lower()

    def _update_dest_empty_state():
        p = current_profile[0]
        if not p:
            return
        if p.provider_config.get("type") == "local" and not p.provider_config.get("path"):
            dest_empty.place(in_=dest_lbl, relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            dest_empty.place_forget()

    def _provider_desc(config: dict) -> str:
        t = config.get("type", "local")
        if t == "local":
            return f"Local Folder: {config.get('path', '~/SaveSyncBackup')}"
        elif t == "dropbox":
            return "Dropbox"
        elif t == "google_drive":
            return "Google Drive"
        elif t == "onedrive":
            return "OneDrive"
        return "Unknown"

    def _load_profile_list():
        tree.delete(*tree.get_children())
        for p in core.profiles:
            tag = "active" if p is current_profile[0] else ""
            tree.insert("", "end", values=(p.name,), tags=(tag,))
        tree.tag_configure("active", background=SEL_BG, foreground=FG)

    def _switch_profile(profile: Profile):
        if daemon_ref[0] and daemon_ref[0].running:
            daemon_ref[0].stop()
            daemon_ref[0] = None
        current_profile[0] = profile
        _refresh_profile_view()
        _load_profile_list()
        _refresh_status_bar()
        _refresh_home()
        start_stop_btn.configure(text="Start Sync")
        log.audit.action("profile_switched", {"profile": profile.name})

    def _select_profile(event=None):
        sel = tree.selection()
        if not sel:
            return
        item = tree.item(sel[0])
        name = item["values"][0]
        for p in core.profiles:
            if p.name == name:
                _switch_profile(p)
                break

    # ─── Profile CRUD ──────────────────────────────────────────

    def _add_profile():
        dlg = tk.Toplevel(root)
        dlg.title("New Profile")
        dlg.geometry("420x300")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Profile Name:", style="StatusBar.TLabel").pack(anchor=tk.W)
        name_var = tk.StringVar()
        ttk.Entry(frm, textvariable=name_var, style="TEntry").pack(fill=tk.X, pady=4)
        ttk.Label(frm, text="Provider:", style="StatusBar.TLabel").pack(anchor=tk.W, pady=(8, 2))
        prov_var = tk.StringVar(value="local")
        prov_combo = ttk.Combobox(frm, textvariable=prov_var,
                                  values=("local", "dropbox", "google_drive", "onedrive"),
                                  state="readonly")
        prov_combo.pack(fill=tk.X)
        ttk.Label(frm, text="Account (optional):", style="StatusBar.TLabel").pack(anchor=tk.W, pady=(8, 2))
        acct_var = tk.StringVar(value="none")
        acct_vars = ["none"]
        for a in core.accounts:
            acct_vars.append(f"{a.provider}: {a.display_email or a.display_name}")
        acct_combo = ttk.Combobox(frm, textvariable=acct_var,
                                  values=acct_vars, state="readonly")
        acct_combo.pack(fill=tk.X)
        btn_row = ttk.Frame(frm)
        btn_row.pack(anchor=tk.E, pady=(12, 0))
        def do_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Name required", "Enter a profile name.")
                return
            for p in core.profiles:
                if p.name == name:
                    messagebox.showwarning("Exists", f"Profile '{name}' already exists.")
                    return
            prov_type = prov_var.get()
            config = {"type": prov_type}
            account_ref = None
            sel_acct = acct_var.get()
            if sel_acct and sel_acct != "none":
                for a in core.accounts:
                    key = f"{a.provider}: {a.display_email or a.display_name}"
                    if key == sel_acct:
                        account_ref = a.account_id
                        break
            if prov_type == "local":
                path = os.path.expanduser(f"~/SaveSync_{name.replace(' ', '_')}")
                config["path"] = path
            elif prov_type in ("dropbox", "google_drive", "onedrive"):
                if not account_ref:
                    messagebox.showinfo("Account Required",
                                        "Connect an account in the Accounts tab first.")
                    dlg.destroy()
                    _open_oauth_wizard(prov_type)
                    return
            profile = Profile(name, [], config, account_ref=account_ref)
            core.profiles.append(profile)
            core.save_profiles()
            log.audit.action("profile_created", {"profile": name, "type": prov_type})
            _switch_profile(profile)
            dlg.destroy()
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy,
                   style="TButton").pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_row, text="Create", style="Primary.TButton",
                   command=do_create).pack(side=tk.RIGHT)

    def _delete_profile():
        p = current_profile[0]
        if not p:
            return
        if len(core.profiles) <= 1:
            messagebox.showwarning("Can't delete", "Must have at least one profile.")
            return
        ok = messagebox.askyesno("Delete", f"Delete profile '{p.name}'?")
        if not ok:
            return
        core.profiles = [x for x in core.profiles if x is not p]
        core.save_profiles()
        log.audit.action("profile_deleted", {"profile": p.name})
        _switch_profile(core.profiles[0])

    # ─── OAuth Wizard ──────────────────────────────────────────

    def _open_oauth_wizard(provider_type: str):
        dlg = tk.Toplevel(root)
        dlg.title(f"Connect {provider_type.title()}")
        dlg.geometry("500x400")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        registry = get_provider_registry()
        adapter_cls = registry.get(provider_type)
        if not adapter_cls:
            messagebox.showerror("Error", f"Unknown provider: {provider_type}")
            dlg.destroy()
            return

        ttk.Label(frm, text=f"Connect to {adapter_cls.display_name}",
                  style="Header.TLabel").pack(anchor=tk.W, pady=(0, 12))

        client_config = {}
        if adapter_cls.needs_client_config:
            ttk.Label(frm, text=adapter_cls.client_config_label,
                      style="StatusBar.TLabel").pack(anchor=tk.W)
            hint = ttk.Label(frm, text=adapter_cls.client_config_hint,
                             foreground="#565f89",
                             font=("Segoe UI", 8))
            hint.pack(anchor=tk.W, pady=(0, 6))

            if provider_type == "google_drive":
                _google_client_wizard(frm, client_config, dlg)
            elif provider_type in ("dropbox", "onedrive"):
                _simple_client_wizard(frm, client_config, provider_type, dlg)
        else:
            _local_connect_wizard(frm, client_config, dlg)

    def _google_client_wizard(parent, client_config, dlg):
        path_var = tk.StringVar()
        ttk.Label(parent, text="OAuth Client JSON file:",
                  style="StatusBar.TLabel").pack(anchor=tk.W, pady=(4, 2))
        entry_frame = ttk.Frame(parent)
        entry_frame.pack(fill=tk.X)
        ttk.Entry(entry_frame, textvariable=path_var,
                  style="TEntry").pack(side=tk.LEFT, fill=tk.X, expand=True)
        def browse():
            p = filedialog.askopenfile(title="Select client_secret*.json",
                                       filetypes=[("JSON", "*.json")])
            if p:
                path_var.set(p.name)
        ttk.Button(entry_frame, text="Browse", command=browse,
                   style="Small.TButton").pack(side=tk.RIGHT, padx=(4, 0))

        def proceed():
            path = path_var.get().strip()
            if not path or not os.path.exists(path):
                messagebox.showwarning("File required", "Select your OAuth client JSON file.")
                return
            try:
                with open(path) as f:
                    data = json.load(f)
                client_config.update(data)
                _do_oauth_flow("google_drive", client_config, dlg)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read client config: {e}")

        ttk.Button(parent, text="Connect to Google",
                   style="Primary.TButton",
                   command=proceed).pack(anchor=tk.E, pady=(12, 0))

    def _simple_client_wizard(parent, client_config, provider_type, dlg):
        ttk.Label(parent, text="Client ID:",
                  style="StatusBar.TLabel").pack(anchor=tk.W, pady=(4, 2))
        cid_var = tk.StringVar()
        ttk.Entry(parent, textvariable=cid_var,
                  style="TEntry").pack(fill=tk.X, pady=2)
        ttk.Label(parent, text="Client Secret:",
                  style="StatusBar.TLabel").pack(anchor=tk.W, pady=(4, 2))
        cs_var = tk.StringVar()
        ttk.Entry(parent, textvariable=cs_var,
                  style="TEntry", show="*").pack(fill=tk.X, pady=2)

        def proceed():
            if not cid_var.get().strip():
                messagebox.showwarning("Client ID required", "Enter your client ID.")
                return
            key = "app_key" if provider_type == "dropbox" else "client_id"
            secret_key = "app_secret" if provider_type == "dropbox" else "client_secret"
            client_config[key] = cid_var.get().strip()
            client_config[secret_key] = cs_var.get().strip()
            _do_oauth_flow(provider_type, client_config, dlg)

        ttk.Button(parent, text=f"Connect to {provider_type.title()}",
                   style="Primary.TButton",
                   command=proceed).pack(anchor=tk.E, pady=(12, 0))

    def _local_connect_wizard(parent, client_config, dlg):
        ttk.Label(parent, text="Backup folder path:",
                  style="StatusBar.TLabel").pack(anchor=tk.W, pady=(4, 2))
        path_var = tk.StringVar(value=os.path.expanduser("~/SaveSyncBackup"))
        browse_frame = ttk.Frame(parent)
        browse_frame.pack(fill=tk.X)
        ttk.Entry(browse_frame, textvariable=path_var,
                  style="TEntry").pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse():
            p = filedialog.askdirectory(title="Select backup folder")
            if p:
                path_var.set(p)

        ttk.Button(browse_frame, text="Browse", command=browse,
                   style="Small.TButton").pack(side=tk.RIGHT, padx=(4, 0))

        def proceed():
            client_config["path"] = path_var.get().strip()
            adapter = LocalAdapter()
            oauth_result = OAuthResult("", "", 0, f"local_{uuid.uuid4().hex[:8]}", "", "Local Folder")
            account = adapter.connect(oauth_result, client_config)
            core.add_account(account)
            _refresh_accounts()
            log.audit.action("account_connected", {"provider": "local"})
            messagebox.showinfo("Connected", f"Local folder connected: {client_config['path']}")
            dlg.destroy()

        ttk.Button(parent, text="Connect", style="Primary.TButton",
                   command=proceed).pack(anchor=tk.E, pady=(12, 0))

    def _do_oauth_flow(provider_type: str, client_config: dict, dlg):
        dlg.destroy()
        import urllib.parse
        import webbrowser
        import http.server

        state = uuid.uuid4().hex[:16]
        code_verifier = uuid.uuid4().hex[:32]
        redirect_uri = "http://127.0.0.1:18080/"

        registry = get_provider_registry()
        adapter = registry.get_instance(provider_type)
        if not adapter:
            messagebox.showerror("Error", f"Unknown provider: {provider_type}")
            return

        auth_url = adapter.build_oauth_url(client_config, redirect_uri,
                                           state, code_verifier)

        wait_dlg = tk.Toplevel(root)
        wait_dlg.title("Waiting for Authorization")
        wait_dlg.geometry("450x140")
        wait_dlg.configure(bg=BG)
        wait_dlg.transient(root)
        ttk.Label(wait_dlg,
                  text="Your browser will open.\nAuthorize the app, then return here.",
                  style="StatusBar.TLabel",
                  wraplength=400).pack(pady=16)
        ttk.Label(wait_dlg,
                  text=adapter.display_name,
                  style="Header.TLabel").pack()
        status_lbl = ttk.Label(wait_dlg, text="Waiting for browser authorization...",
                               style="StatusBar.TLabel")
        status_lbl.pack(pady=(8, 0))
        cancel_btn = ttk.Button(wait_dlg, text="Cancel", style="TButton")
        cancel_btn.pack(pady=(8, 0))

        webbrowser.open(auth_url)

        parsed = urllib.parse.urlparse(redirect_uri)
        port = parsed.port or 18080
        code_result = [None]
        auth_event = threading.Event()

        class OAuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                qs = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(qs)
                recv_state = params.get("state", [None])[0]
                if recv_state != state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"State mismatch")
                    return
                code_result[0] = params.get("code", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization received!</h2>"
                    b"<p>You can close this tab.</p></body></html>")
                auth_event.set()

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", port), OAuthHandler)
        server_thread = threading.Thread(target=lambda: _serve_until(server, auth_event), daemon=True)
        server_thread.start()

        def _check_oauth():
            if auth_event.is_set():
                server.server_close()
                wait_dlg.destroy()
                code = code_result[0]
                if not code:
                    messagebox.showwarning("Cancelled",
                                           "Authentication was cancelled or timed out.")
                    return
                status_lbl.configure(text="Exchanging token...")
                root.update_idletasks()
                root.after(10, lambda: _finish_oauth(provider_type, client_config,
                                                     code, code_verifier, adapter))
            elif not wait_dlg.winfo_exists():
                server.server_close()
                return
            else:
                root.after(200, _check_oauth)

        def _serve_until(srv, stop_event):
            srv.timeout = 0.5
            deadline = time.time() + 120
            while not stop_event.is_set() and time.time() < deadline:
                srv.handle_request()
            srv.server_close()

        cancel_btn.configure(command=lambda: [auth_event.set(), wait_dlg.destroy()])
        root.after(200, _check_oauth)

    def _finish_oauth(provider_type, client_config, code, code_verifier, adapter):
        try:
            oauth_result = adapter.exchange_code(client_config,
                                                 "http://127.0.0.1:18080/",
                                                 code, code_verifier)
            account = adapter.connect(oauth_result, client_config)
            core.add_account(account)
            _refresh_accounts()
            log.audit.action("account_connected",
                             {"provider": provider_type, "account": account.account_id})
            messagebox.showinfo("Connected",
                                f"{adapter.display_name} connected as "
                                f"{account.display_email or account.display_name}")
        except Exception as e:
            messagebox.showerror("Auth Failed", f"Token exchange failed: {e}")

    # ─── Accounts List ─────────────────────────────────────────

    def _refresh_accounts():
        for w in acct_content.winfo_children():
            w.destroy()
        if not core.accounts:
            ttk.Label(acct_content, text="No accounts connected yet",
                      style="Empty.TLabel",
                      font=("Segoe UI", 12)).pack(expand=True, pady=40)
            ttk.Label(acct_content,
                      text='Click "Connect Account" to add Google Drive, Dropbox, OneDrive, or Local Folder.',
                      style="Empty.TLabel").pack()
        for account in core.accounts:
            card = ttk.Frame(acct_content, style="Card.TFrame", padding=12)
            card.pack(fill=tk.X, pady=(0, 8))
            header = ttk.Frame(card, style="Card.TFrame")
            header.pack(fill=tk.X)
            ttk.Label(header,
                      text=account.display_name or account.provider,
                      style="CardHeader.TLabel").pack(side=tk.LEFT)
            ttk.Label(header,
                      text=account.display_email,
                      style="CardEmpty.TLabel").pack(side=tk.LEFT, padx=(8, 0))

            adapter = core.provider_registry.get_instance_for_account(account)
            if adapter:
                ok, status = adapter.status(account)
                status_color = GREEN if ok else RED
            else:
                ok, status = False, "unknown"
                status_color = YELLOW
            ttk.Label(header,
                      text=f"● {status}",
                      foreground=status_color,
                      style="CardEmpty.TLabel").pack(side=tk.RIGHT)

            detail = ttk.Frame(card, style="Card.TFrame")
            detail.pack(fill=tk.X, pady=(4, 0))
            ttk.Label(detail,
                      text=f"Provider: {account.provider}  |  ID: {account.account_id[:12]}...",
                      style="CardEmpty.TLabel").pack(side=tk.LEFT)

            def disconnect(a=account):
                ok = messagebox.askyesno("Disconnect",
                                         f"Disconnect {a.display_name or a.provider}?")
                if ok:
                    core.remove_account(a.account_id)
                    _refresh_accounts()
                    log.audit.action("account_disconnected", {"provider": a.provider})

            ttk.Button(detail, text="Disconnect",
                       style="Destructive.TButton",
                       command=disconnect).pack(side=tk.RIGHT)

    add_acct_btn.configure(command=lambda: _show_connect_dialog())
    manage_btn.configure(command=lambda: notebook.select(profiles_frame))

    def _show_connect_dialog():
        dlg = tk.Toplevel(root)
        dlg.title("Connect Account")
        dlg.geometry("380x260")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Select provider type:",
                  style="Header.TLabel").pack(anchor=tk.W, pady=(0, 12))
        for prov in ["google_drive", "dropbox", "onedrive", "local"]:
            registry = get_provider_registry()
            cls = registry.get(prov)
            if cls:
                btn = ttk.Button(frm, text=cls.display_name, style="TButton")
                btn.pack(fill=tk.X, pady=2)
                btn.configure(command=lambda p=prov: [_open_oauth_wizard(p), dlg.destroy()])

    # ─── Binding Commands ───────────────────────────────────────

    tree.bind("<<TreeviewSelect>>", _select_profile)
    add_prof_btn.configure(command=_add_profile)
    del_prof_btn.configure(command=_delete_profile)
    toggle_mode_btn.configure(command=lambda: _toggle_sync_mode())
    browse_btn.configure(command=lambda: _browse_provider_path())

    def _toggle_sync_mode():
        p = current_profile[0]
        if not p:
            return
        p.sync_on_close = not p.sync_on_close
        core.save_profiles()
        _refresh_profile_view()

    def _browse_provider_path():
        p = current_profile[0]
        if not p:
            return
        if p.provider_config.get("type") != "local":
            messagebox.showinfo("Cloud Provider", "Path is managed by the cloud provider.")
            return
        path = filedialog.askdirectory(
            title="Select backup destination",
            initialdir=p.provider_config.get("path", os.path.expanduser("~")))
        if path:
            p.provider_config["path"] = path
            core.save_profiles()
            _refresh_profile_view()

    add_dir_btn.configure(command=lambda: _add_dir())
    rm_dir_btn.configure(command=lambda: _remove_dir())

    def _add_dir():
        p = current_profile[0]
        if not p:
            return
        path = filedialog.askdirectory(title="Select save folder")
        if path and path not in p.watch_dirs:
            p.watch_dirs.append(path)
            core.save_profiles()
            log.audit.action("watch_dir_added", {"profile": p.name, "path": path})
            _refresh_profile_view()

    def _remove_dir():
        p = current_profile[0]
        if not p:
            return
        sel = dir_list.curselection()
        if sel:
            removed = p.watch_dirs.pop(sel[0])
            core.save_profiles()
            log.audit.action("watch_dir_removed", {"profile": p.name, "path": removed})
            _refresh_profile_view()

    def _toggle_sync():
        p = current_profile[0]
        if not p:
            return
        if daemon_ref[0] and daemon_ref[0].running:
            daemon_ref[0].stop()
            daemon_ref[0] = None
            start_stop_btn.configure(text="Start Sync")
            sync_now_btn.configure(text="Sync Now")
            _refresh_status_bar()
            _refresh_home()
            log.audit.action("sync_stopped", {"profile": p.name})
            return
        if not p.watch_dirs:
            messagebox.showwarning("No Folders", "Add at least one watched folder.")
            return
        daemon_ref[0] = SaveSyncDaemon(core, p)
        daemon_ref[0].start()
        start_stop_btn.configure(text="Stop Sync")
        sync_now_btn.configure(text="Sync Now")
        _refresh_status_bar()
        _refresh_home()
        log.audit.action("sync_started", {"profile": p.name})

    _progress_after_id = None
    _operation_gen = 0

    def _fmt_bytes(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def _fmt_duration(secs):
        if secs < 60:
            return f"{int(secs)}s"
        m = int(secs // 60)
        s = int(secs % 60)
        if m < 60:
            return f"{m}m {s}s"
        return f"{m // 60}h {m % 60}m"

    def _stop_progress_polling():
        nonlocal _progress_after_id
        if _progress_after_id:
            try:
                root.after_cancel(_progress_after_id)
            except Exception:
                pass
            _progress_after_id = None

    def _start_progress_polling(gen):
        _stop_progress_polling()

        def _poll():
            nonlocal _progress_after_id, _operation_gen
            if gen != _operation_gen:
                return
            worker = sync_worker_ref[0]
            if not worker or not worker.is_running or not worker.op_state:
                _progress_after_id = root.after(200, _poll)
                return
            snap = worker.op_state.snapshot()

            phase = snap.phase or ""
            if phase in ("Scanning", "Preparing"):
                progress_bar.stop()
                progress_bar.configure(mode="indeterminate")
                progress_bar.start(15)
            else:
                progress_bar.stop()
                progress_bar.configure(mode="determinate")
                if snap.bytes_total > 0:
                    pct = min(100.0, (snap.bytes_transferred / snap.bytes_total) * 100)
                    progress_bar["value"] = pct

            file_lbl.configure(text=snap.current_file or phase or "")
            if snap.bytes_total > 0:
                b = _fmt_bytes(snap.bytes_transferred)
                t = _fmt_bytes(snap.bytes_total)
                files_info = ""
                if snap.files_total > 0:
                    files_info = f"  ({snap.files_completed}/{snap.files_total} files)"
                bytes_lbl.configure(text=f"{b} of {t}{files_info}")
            else:
                bytes_lbl.configure(text=_fmt_bytes(snap.bytes_transferred))

            if snap.speed_bps > 0:
                eta_secs = 0
                if snap.bytes_total > 0:
                    remaining = max(0, snap.bytes_total - snap.bytes_transferred)
                    eta_secs = remaining / snap.speed_bps
                speed_str = f"{_fmt_bytes(snap.speed_bps)}/s"
                if snap.phase in ("Uploading", "Downloading") and 0 < eta_secs < 86400:
                    speed_str += f"  ETA: {_fmt_duration(eta_secs)}"
                speed_lbl.configure(text=speed_str)

            _progress_after_id = root.after(200, _poll)

        _poll()

    def _handle_done(success, message, stats=None):
        _stop_progress_polling()
        progress_bar.stop()
        progress_bar.configure(mode="determinate", value=100 if success else 0)
        cancel_btn.configure(state="disabled")
        if message:
            file_lbl.configure(text=message)
        if stats:
            dur = stats.get("duration_ms", 0) / 1000
            spd = stats.get("speed_bps", 0)
            parts = []
            if dur > 0:
                parts.append(f"{dur:.1f}s")
            if spd > 0:
                parts.append(f"{_fmt_bytes(spd)}/s")
            if parts:
                bytes_lbl.configure(text="  ".join(parts))
        sync_now_btn.configure(text="Sync Now", style="Primary.TButton")
        restore_btn.configure(text="Restore", style="TButton")
        start_stop_btn.configure(state="normal")
        add_prof_btn.configure(state="normal")
        _refresh_status_bar()
        _refresh_home()

    def _cancel_operation():
        nonlocal _operation_gen
        _operation_gen += 1
        worker = sync_worker_ref[0]
        sync_worker_ref[0] = None
        if worker:
            worker.cancel()

    def _sync_now():
        nonlocal _operation_gen
        p = current_profile[0]
        if not p:
            return
        if sync_worker_ref[0] and sync_worker_ref[0].is_running:
            _cancel_operation()
            sync_now_btn.configure(text="Sync Now", style="Primary.TButton")
            restore_btn.configure(text="Restore", style="TButton")
            start_stop_btn.configure(state="normal")
            add_prof_btn.configure(state="normal")
            return
        _operation_gen += 1
        my_gen = _operation_gen

        def _gen_guard(success, message, stats=None):
            if my_gen == _operation_gen:
                _handle_done(success, message, stats)

        log.audit.action("manual_sync", {"profile": p.name})
        worker = SyncWorker(core, p)
        sync_worker_ref[0] = worker
        sync_now_btn.configure(text="Cancel", style="Destructive.TButton")
        restore_btn.configure(text="Restore", state="disabled")
        start_stop_btn.configure(state="disabled")
        add_prof_btn.configure(state="disabled")
        cancel_btn.configure(state="normal")
        file_lbl.configure(text="Starting sync...")
        bytes_lbl.configure(text="")
        speed_lbl.configure(text="")
        progress_bar.stop()
        progress_bar.configure(mode="indeterminate")
        progress_bar.start(15)
        _start_progress_polling(my_gen)
        worker.sync_all(done_callback=_gen_guard)

    def _restore():
        nonlocal _operation_gen
        p = current_profile[0]
        if not p:
            return
        if sync_worker_ref[0] and sync_worker_ref[0].is_running:
            _cancel_operation()
            sync_now_btn.configure(text="Sync Now", style="Primary.TButton")
            restore_btn.configure(text="Restore", style="TButton")
            start_stop_btn.configure(state="normal")
            add_prof_btn.configure(state="normal")
            return
        ok = messagebox.askyesno("Restore",
                                 "Restore all missing files from backup? "
                                 "This will download files that don't exist locally.")
        if not ok:
            return
        _operation_gen += 1
        my_gen = _operation_gen

        def _gen_guard(success, message, stats=None):
            if my_gen == _operation_gen:
                _handle_done(success, message, stats)

        log.audit.action("restore_requested", {"profile": p.name})
        worker = SyncWorker(core, p)
        sync_worker_ref[0] = worker
        restore_btn.configure(text="Cancel", style="Destructive.TButton")
        sync_now_btn.configure(text="Sync Now", state="disabled")
        start_stop_btn.configure(state="disabled")
        add_prof_btn.configure(state="disabled")
        cancel_btn.configure(state="normal")
        file_lbl.configure(text="Starting restore...")
        bytes_lbl.configure(text="")
        speed_lbl.configure(text="")
        progress_bar.stop()
        progress_bar.configure(mode="indeterminate")
        progress_bar.start(15)
        _start_progress_polling(my_gen)
        worker.restore_all(done_callback=_gen_guard)

    def _clear_log():
        log_area.delete("1.0", tk.END)

    sync_now_btn.configure(command=_sync_now)
    start_stop_btn.configure(command=_toggle_sync)
    restore_btn.configure(command=_restore)
    cancel_btn.configure(command=_cancel_operation)
    clear_log_btn.configure(command=_clear_log)

    # ─── Onboarding ─────────────────────────────────────────────

    def _show_onboarding():
        if len(core.accounts) > 0:
            return
        if core.profiles and core.profiles[0].provider_config.get("type") == "local" and os.path.exists(
            os.path.expanduser("~/SaveSyncBackup")):
            return
        dlg = tk.Toplevel(root)
        dlg.title("Welcome to SaveSync")
        dlg.geometry("520x380")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=24)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Welcome to SaveSync",
                  style="Header.TLabel",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 16))
        ttk.Label(frm,
                  text="SaveSync keeps your save files backed up and synced across devices.\n\n"
                       "You can use it with:\n"
                       "  • Local folders (no account needed)\n"
                       "  • Google Drive (BYO OAuth client)\n"
                       "  • Dropbox (BYO app key)\n"
                       "  • OneDrive (BYO app registration)\n\n"
                       "Get started by connecting a storage provider, or use a local folder right away.",
                  wraplength=460, style="StatusBar.TLabel",
                  font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 24))
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill=tk.X)
        skip_btn = ttk.Button(btn_row, text="Use Local Folder",
                              style="TButton")
        skip_btn.pack(side=tk.LEFT, padx=(0, 8))
        connect_btn = ttk.Button(btn_row, text="Connect a Provider",
                                 style="Primary.TButton")
        connect_btn.pack(side=tk.RIGHT)
        skip_btn.configure(command=lambda: [_setup_local_onboarding(), dlg.destroy()])
        connect_btn.configure(command=lambda: [dlg.destroy(), _show_connect_dialog()])

    def _setup_local_onboarding():
        adapter = LocalAdapter()
        path = os.path.expanduser("~/SaveSyncBackup")
        result = OAuthResult("", "", 0, f"local_{uuid.uuid4().hex[:8]}", "", "Local Folder")
        account = adapter.connect(result, {"path": path})
        core.add_account(account)
        _refresh_accounts()
        for p in core.profiles:
            if p.provider_config.get("type") == "local":
                p.provider_config["path"] = path
                core.save_profiles()
                break
        log.audit.action("onboarding_completed", {"type": "local"})

    # ─── Init ────────────────────────────────────────────────────

    gui_handler = GuiLogHandler(log_area)
    core.logger = setup_file_logger(gui_handler)
    core.log_handler = lambda msg: None

    config_sync.logger = core.logger
    config_sync.log_handler = core.log_handler

    _load_profile_list()
    if core.profiles:
        _switch_profile(core.profiles[0])
    _refresh_home()
    _refresh_status_bar()
    _refresh_accounts()

    root.after(200, _show_onboarding)

    # ─── On Close ────────────────────────────────────────────────

    def on_close():
        _stop_progress_polling()
        _operation_gen += 1

        worker = sync_worker_ref[0]
        if worker and worker.is_running:
            worker.cancel()
            try:
                worker._thread.join(timeout=5)
            except Exception:
                pass
            if worker._thread and worker._thread.is_alive():
                core.log("Shutdown: sync worker thread abandoned")
            sync_worker_ref[0] = None

        p = current_profile[0]
        if p and p.sync_on_close:
            if daemon_ref[0] and daemon_ref[0].running:
                daemon_ref[0].sync_all_now()
                daemon_ref[0].stop()
            else:
                d = SaveSyncDaemon(core, p)
                d.sync_all_now()
        elif daemon_ref[0] and daemon_ref[0].running:
            daemon_ref[0].stop()

        log_shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    if "--gui-smoke-test" in sys.argv:
        for i in range(notebook.index("end")):
            notebook.select(i)
            root.update_idletasks()
        root.destroy()
        return

    if sync_now_flag:

        def _auto_sync():
            nonlocal _operation_gen
            p = current_profile[0]
            if not p:
                _startup_log("--sync-now: no profile loaded, aborting")
                return
            if not p.watch_dirs:
                _startup_log("--sync-now: no watch dirs configured, aborting")
                return
            _sync_now()

        root.after(500, _auto_sync)

    if cancel_after is not None:

        def _auto_cancel():
            _startup_log("--cancel-after: triggering cancel")
            if sync_worker_ref[0] and sync_worker_ref[0].is_running:
                _cancel_operation()
                sync_now_btn.configure(text="Sync Now", style="Primary.TButton")
                restore_btn.configure(text="Restore", style="TButton")
                start_stop_btn.configure(state="normal")
                add_prof_btn.configure(state="normal")
                _startup_log("--cancel-after: cancel triggered")
            else:
                _startup_log("--cancel-after: no running operation to cancel")

        root.after(int(cancel_after * 1000), _auto_cancel)

    if close_after is not None:

        def _auto_close():
            _startup_log("--close-after: triggering close")
            on_close()

        root.after(int(close_after * 1000), _auto_close)

    root.mainloop()


if __name__ == "__main__":
    main()

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

import customtkinter as ctk

__version__ = "2.0.0"


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

    if "--help" in sys.argv or "-h" in sys.argv:
        print("SaveSync \u2014 game save backup and sync tool")
        print()
        print("Usage: SaveSync [options]")
        print()
        print("Options:")
        print("  --version, -v       Show version and exit")
        print("  --help, -h          Show this help and exit")
        print("  --self-test         Run built-in self-test")
        print("  --gui-smoke-test    Validate UI renders without blocking")
        print("  --sync-now          Trigger sync on startup")
        print("  --cancel-after <s>  Cancel ongoing op after N seconds")
        print("  --close-after <s>   Close app after N seconds")
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


SIDEBAR_ICONS = {
    "home": "\u2302",
    "games": "\u266B",
    "cloud": "\u2601",
    "activity": "\u2630",
    "settings": "\u2699",
}

PAGE_NAMES = ["home", "games", "cloud", "activity", "settings"]
PAGE_LABELS = ["Home", "Games", "Cloud", "Activity", "Settings"]

ACCENT = "#7aa2f7"
GREEN = "#9ece6a"
RED = "#f7768e"
YELLOW = "#e0af68"
CARD_BG = "#1e1f34"
CARD_BORDER = "#2f3b6b"
SECTION_BG = "#24253a"


class SaveSyncApp:
    def __init__(self, sync_now_flag=False, cancel_after=None, close_after=None):
        self.sync_now_flag = sync_now_flag
        self.cancel_after = cancel_after
        self.close_after = close_after

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        from core import SaveSyncCore, SaveSyncDaemon, SyncWorker, Profile, GuiLogHandler, setup_file_logger
        from logging_system import get_logging_system, shutdown as log_shutdown
        from credential_store import get_credential_store, redact_secrets
        from providers import (
            Account, OAuthResult, ProviderRegistry, get_provider_registry,
            LocalAdapter, DropboxAdapter, GoogleDriveAdapter, OneDriveAdapter,
        )
        from config_sync import ConfigSync, SyncConfig, DeviceConfig, _get_device_id

        self.SaveSyncCore = SaveSyncCore
        self.SaveSyncDaemon = SaveSyncDaemon
        self.SyncWorker = SyncWorker
        self.Profile = Profile
        self.GuiLogHandler = GuiLogHandler
        self.setup_file_logger = setup_file_logger
        self.get_logging_system = get_logging_system
        self.log_shutdown = log_shutdown
        self.get_credential_store = get_credential_store
        self.redact_secrets = redact_secrets
        self.Account = Account
        self.OAuthResult = OAuthResult
        self.get_provider_registry = get_provider_registry
        self.LocalAdapter = LocalAdapter
        self.DropboxAdapter = DropboxAdapter
        self.GoogleDriveAdapter = GoogleDriveAdapter
        self.OneDriveAdapter = OneDriveAdapter
        self.ConfigSync = ConfigSync
        self._get_device_id = _get_device_id

        self.core = SaveSyncCore()
        self.log = get_logging_system()
        self.config_sync = ConfigSync()
        self.daemon_ref = [None]
        self.sync_worker_ref = [None]
        self.current_profile = [self.core.profiles[0] if self.core.profiles else None]
        self._progress_after_id = None
        self._operation_gen = 0

        self.root = ctk.CTk()
        self.root.title("SaveSync")
        self.root.geometry("1060x740")
        self.root.minsize(900, 640)

        self._build_layout()
        self._build_home_page()
        self._build_games_page()
        self._build_cloud_page()
        self._build_activity_page()
        self._build_settings_page()

        self.gui_handler = GuiLogHandler(self.log_area)
        self.core.logger = setup_file_logger(self.gui_handler)
        self.core.log_handler = lambda msg: None
        self.config_sync.logger = self.core.logger
        self.config_sync.log_handler = self.core.log_handler

        self._load_profile_list()
        if self.core.profiles:
            self._switch_profile(self.core.profiles[0])
        self._refresh_home()
        self._refresh_status_bar()
        self._refresh_accounts()

        self.root.after(200, self._show_onboarding)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if "--gui-smoke-test" in sys.argv:
            for page in PAGE_NAMES:
                self._show_page(page)
                self.root.update_idletasks()
            self.root.destroy()
            return

        if sync_now_flag:
            self.root.after(500, self._auto_sync)
        if cancel_after is not None:
            self.root.after(int(cancel_after * 1000), self._auto_cancel)
        if close_after is not None:
            self.root.after(int(close_after * 1000), self._auto_close)

        self.root.mainloop()

    # ─── Layout ───────────────────────────────────────────────────

    def _build_layout(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(self.root, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nswe")
        self.sidebar.grid_rowconfigure(5, weight=1)

        logo = ctk.CTkLabel(self.sidebar, text="SaveSync",
                            font=ctk.CTkFont(size=18, weight="bold"),
                            anchor="w")
        logo.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 16))

        self.nav_btns = {}
        for i, (name, label) in enumerate(zip(PAGE_NAMES, PAGE_LABELS)):
            icon = SIDEBAR_ICONS.get(name, "")
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {icon}  {label}" if icon else label,
                anchor="w",
                fg_color="transparent",
                text_color=("#1a1b26", "#c0caf5"),
                hover_color=("#dce4ee", "#2f3b6b"),
                font=ctk.CTkFont(size=13),
                corner_radius=8,
                command=lambda n=name: self._show_page(n),
            )
            btn.grid(row=i + 1, column=0, sticky="ew", padx=10, pady=2)
            self.nav_btns[name] = btn

        self.content = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#1a1b26")
        self.content.grid(row=0, column=1, sticky="nswe")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self._build_status_bar()

        self.pages = {}
        self.active_page = None

    def _build_status_bar(self):
        self.status_bar = ctk.CTkFrame(self.content, height=36, corner_radius=0,
                                       fg_color="#24253a")
        self.status_bar.grid(row=2, column=0, sticky="ew")
        self.status_bar.grid_columnconfigure(4, weight=1)

        self.status_profile_lbl = ctk.CTkLabel(
            self.status_bar, text="No profile",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT, anchor="w", padx=4)
        self.status_profile_lbl.grid(row=0, column=0, padx=(16, 8), pady=6, sticky="w")

        self.status_provider_lbl = ctk.CTkLabel(
            self.status_bar, text="", font=ctk.CTkFont(size=11), anchor="w")
        self.status_provider_lbl.grid(row=0, column=1, padx=4, pady=6, sticky="w")

        self.status_folders_lbl = ctk.CTkLabel(
            self.status_bar, text="0 folders", font=ctk.CTkFont(size=11), anchor="w")
        self.status_folders_lbl.grid(row=0, column=2, padx=4, pady=6, sticky="w")

        self.status_state_lbl = ctk.CTkLabel(
            self.status_bar, text="Ready",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=GREEN, anchor="w")
        self.status_state_lbl.grid(row=0, column=3, padx=4, pady=6, sticky="w")

        self.version_lbl = ctk.CTkLabel(
            self.status_bar, text=f"v{__version__}",
            font=ctk.CTkFont(size=10), text_color="#565f89")
        self.version_lbl.grid(row=0, column=5, padx=(4, 16), pady=6, sticky="e")

    def _show_page(self, name):
        if self.active_page == name:
            return
        if self.active_page and self.active_page in self.pages:
            self.pages[self.active_page].grid_forget()
        for n, btn in self.nav_btns.items():
            if n == name:
                btn.configure(fg_color=("#dce4ee", "#2f3b6b"), text_color=("#1a1b26", ACCENT))
            else:
                btn.configure(fg_color="transparent", text_color=("#1a1b26", "#c0caf5"))
        frame = self.pages.get(name)
        if frame:
            frame.grid(row=1, column=0, sticky="nswe", padx=0, pady=0)
        self.active_page = name

    # ─── Helpers ──────────────────────────────────────────────────

    def _fmt_bytes(self, n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def _fmt_duration(self, secs):
        if secs < 60:
            return f"{int(secs)}s"
        m = int(secs // 60)
        s = int(secs % 60)
        if m < 60:
            return f"{m}m {s}s"
        return f"{m // 60}h {m % 60}m"

    def _provider_desc(self, config: dict) -> str:
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

    # ─── Home Page ────────────────────────────────────────────────

    def _build_home_page(self):
        frame = ctk.CTkScrollableFrame(self.content, fg_color="#1a1b26",
                                       corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        self.pages["home"] = frame
        self._home_frame = frame

        header = ctk.CTkLabel(frame, text="Dashboard",
                              font=ctk.CTkFont(size=22, weight="bold"),
                              anchor="w", padx=0)
        header.grid(row=0, column=0, sticky="w", padx=28, pady=(24, 4))

        sub = ctk.CTkLabel(frame, text="Overview of your protected games",
                           font=ctk.CTkFont(size=13), text_color="#565f89",
                           anchor="w")
        sub.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                            border_width=1, border_color=CARD_BORDER)
        card.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 4))
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="Profile",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 4))
        self.home_profile_val = ctk.CTkLabel(
            card, text="\u2014", font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w")
        self.home_profile_val.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=(14, 4))

        ctk.CTkLabel(card, text="Provider",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=1, column=0, sticky="w", padx=20, pady=2)
        self.home_provider_val = ctk.CTkLabel(
            card, text="\u2014", font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w")
        self.home_provider_val.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=2)

        ctk.CTkLabel(card, text="Folders",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=2, column=0, sticky="w", padx=20, pady=2)
        self.home_folders_val = ctk.CTkLabel(
            card, text="0", font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w")
        self.home_folders_val.grid(row=2, column=1, sticky="w", padx=(0, 20), pady=2)

        ctk.CTkLabel(card, text="Status",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=3, column=0, sticky="w", padx=20, pady=(2, 14))
        self.home_status_val = ctk.CTkLabel(
            card, text="Ready", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=GREEN, anchor="w")
        self.home_status_val.grid(row=3, column=1, sticky="w", padx=(0, 20), pady=(2, 14))

        actions_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                                    border_width=1, border_color=CARD_BORDER)
        actions_card.grid(row=3, column=0, sticky="ew", padx=28, pady=(12, 4))
        actions_card.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(actions_card, text="Quick Actions",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=4, sticky="w",
                            padx=20, pady=(14, 10))

        self.sync_now_btn = ctk.CTkButton(
            actions_card, text="Sync Now", font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, hover_color="#89b4fa", text_color="#1a1b26",
            corner_radius=8, height=36, command=self._sync_now,
        )
        self.sync_now_btn.grid(row=1, column=0, padx=(20, 6), pady=(0, 14), sticky="w")

        self.start_stop_btn = ctk.CTkButton(
            actions_card, text="Start Sync", font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=36,
            command=self._toggle_sync,
        )
        self.start_stop_btn.grid(row=1, column=1, padx=6, pady=(0, 14), sticky="w")

        self.restore_btn = ctk.CTkButton(
            actions_card, text="Restore", font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=36,
            command=self._restore,
        )
        self.restore_btn.grid(row=1, column=2, padx=6, pady=(0, 14), sticky="w")

        self.manage_btn = ctk.CTkButton(
            actions_card, text="Manage Games", font=ctk.CTkFont(size=12),
            fg_color="transparent", text_color="#565f89",
            corner_radius=8, height=30,
            command=lambda: self._show_page("games"),
        )
        self.manage_btn.grid(row=1, column=3, padx=(6, 20), pady=(0, 14), sticky="e")

        prog_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                                 border_width=1, border_color=CARD_BORDER)
        prog_card.grid(row=4, column=0, sticky="ew", padx=28, pady=(12, 4))
        prog_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(prog_card, text="Progress",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 10))

        self.progress_bar = ctk.CTkProgressBar(prog_card, height=6, corner_radius=3,
                                                fg_color="#2f3b6b",
                                                progress_color=ACCENT)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 6))
        self.progress_bar.set(0)

        self.file_lbl = ctk.CTkLabel(prog_card, text="",
                                     font=ctk.CTkFont(size=12), anchor="w")
        self.file_lbl.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 2))

        info_row = ctk.CTkFrame(prog_card, fg_color="transparent")
        info_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 4))
        info_row.grid_columnconfigure(1, weight=1)

        self.bytes_lbl = ctk.CTkLabel(info_row, text="",
                                      font=ctk.CTkFont(size=11), anchor="w")
        self.bytes_lbl.grid(row=0, column=0, sticky="w", padx=(0, 16))

        self.speed_lbl = ctk.CTkLabel(info_row, text="",
                                      font=ctk.CTkFont(size=11), anchor="w")
        self.speed_lbl.grid(row=0, column=1, sticky="w")

        self.cancel_btn = ctk.CTkButton(
            prog_card, text="Cancel", font=ctk.CTkFont(size=12),
            fg_color="#3b1f2e", hover_color="#4c2435",
            text_color=RED, corner_radius=8, height=30,
            state="disabled", command=self._cancel_operation,
        )
        self.cancel_btn.grid(row=4, column=0, sticky="e", padx=20, pady=(4, 14))

        recent_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                                   border_width=1, border_color=CARD_BORDER)
        recent_card.grid(row=5, column=0, sticky="ew", padx=28, pady=(12, 24))
        recent_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(recent_card, text="Recent Activity",
                     font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 10))

        self.recent_lbl = ctk.CTkLabel(
            recent_card, text="No activity yet. Start a sync to see progress here.",
            font=ctk.CTkFont(size=12), text_color="#565f89", anchor="w",
            justify="left")
        self.recent_lbl.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 14))

    # ─── Games (Profiles) Page ────────────────────────────────────

    def _build_games_page(self):
        frame = ctk.CTkFrame(self.content, fg_color="#1a1b26", corner_radius=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.pages["games"] = frame

        header = ctk.CTkLabel(frame, text="Games",
                              font=ctk.CTkFont(size=22, weight="bold"),
                              anchor="w")
        header.grid(row=0, column=0, columnspan=2, sticky="w", padx=28, pady=(24, 16))

        left_panel = ctk.CTkFrame(frame, fg_color="#1e1f34", corner_radius=10,
                                  width=220, border_width=1, border_color=CARD_BORDER)
        left_panel.grid(row=1, column=0, sticky="nswe", padx=(28, 8), pady=(0, 28))
        left_panel.grid_rowconfigure(1, weight=1)
        left_panel.grid_propagate(False)

        ctk.CTkLabel(left_panel, text="PROFILES",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#565f89").grid(row=0, column=0, sticky="w",
                                                padx=14, pady=(12, 6))

        self.profile_list_frame = ctk.CTkScrollableFrame(
            left_panel, fg_color="transparent", corner_radius=0)
        self.profile_list_frame.grid(row=1, column=0, sticky="nswe", padx=6, pady=0)

        btn_row = ctk.CTkFrame(left_panel, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        self.add_prof_btn = ctk.CTkButton(
            btn_row, text="+ New", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=32,
            command=self._add_profile,
        )
        self.add_prof_btn.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        self.del_prof_btn = ctk.CTkButton(
            btn_row, text="Delete", font=ctk.CTkFont(size=12),
            fg_color="#3b1f2e", text_color=RED, corner_radius=8, height=32,
            command=self._delete_profile,
        )
        self.del_prof_btn.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        detail_panel = ctk.CTkScrollableFrame(frame, fg_color=CARD_BG,
                                               corner_radius=10,
                                               border_width=1,
                                               border_color=CARD_BORDER)
        detail_panel.grid(row=1, column=1, sticky="nswe", padx=(8, 28), pady=(0, 28))
        detail_panel.grid_columnconfigure(1, weight=1)
        self._detail_panel = detail_panel

        ctk.CTkLabel(detail_panel, text="Profile Details",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=3, sticky="w",
                            padx=20, pady=(16, 12))

        ctk.CTkLabel(detail_panel, text="Name",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=1, column=0, sticky="w", padx=20, pady=3)
        self.profile_name_val = ctk.CTkLabel(
            detail_panel, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.profile_name_val.grid(row=1, column=1, sticky="w", padx=8, pady=3)

        ctk.CTkLabel(detail_panel, text="Provider",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=2, column=0, sticky="w", padx=20, pady=3)
        self.prov_desc_val = ctk.CTkLabel(
            detail_panel, text="", font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=400)
        self.prov_desc_val.grid(row=2, column=1, sticky="w", padx=8, pady=3)

        ctk.CTkLabel(detail_panel, text="Sync Mode",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=3, column=0, sticky="w", padx=20, pady=3)
        self.sync_mode_val = ctk.CTkLabel(
            detail_panel, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.sync_mode_val.grid(row=3, column=1, sticky="w", padx=8, pady=3)

        self.toggle_mode_btn = ctk.CTkButton(
            detail_panel, text="Toggle", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=30,
            command=self._toggle_sync_mode,
        )
        self.toggle_mode_btn.grid(row=3, column=2, padx=(8, 20), pady=3)

        folders_section = ctk.CTkFrame(detail_panel, fg_color="transparent",
                                       corner_radius=0)
        folders_section.grid(row=4, column=0, columnspan=3, sticky="ew",
                             padx=20, pady=(12, 4))
        folders_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(folders_section, text="Watched Folders",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.dir_list_frame = ctk.CTkScrollableFrame(
            folders_section, fg_color="#1a1b26", corner_radius=6,
            border_width=1, border_color=CARD_BORDER, height=100)
        self.dir_list_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.dir_empty = ctk.CTkLabel(
            self.dir_list_frame, text="No folders added yet",
            font=ctk.CTkFont(size=12), text_color="#565f89")
        self.dir_empty.pack(expand=True, pady=20)

        dir_btns = ctk.CTkFrame(folders_section, fg_color="transparent")
        dir_btns.grid(row=2, column=0, sticky="w", pady=(0, 4))

        self.add_dir_btn = ctk.CTkButton(
            dir_btns, text="+ Add Save Folder", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=30,
            command=self._add_dir,
        )
        self.add_dir_btn.pack(side="left", padx=(0, 6))

        self.rm_dir_btn = ctk.CTkButton(
            dir_btns, text="Remove", font=ctk.CTkFont(size=12),
            fg_color="#3b1f2e", text_color=RED, corner_radius=8, height=30,
            command=self._remove_dir,
        )
        self.rm_dir_btn.pack(side="left")

        dest_section = ctk.CTkFrame(detail_panel, fg_color="transparent",
                                    corner_radius=0)
        dest_section.grid(row=5, column=0, columnspan=3, sticky="ew",
                          padx=20, pady=(8, 16))
        dest_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(dest_section, text="Sync Destination",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.dest_prov_lbl = ctk.CTkLabel(
            dest_section, text="", font=ctk.CTkFont(size=12), anchor="w",
            wraplength=500)
        self.dest_prov_lbl.grid(row=1, column=0, sticky="w", pady=(0, 4))

        self.browse_btn = ctk.CTkButton(
            dest_section, text="Browse Destination", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=30,
            command=self._browse_provider_path,
        )
        self.browse_btn.grid(row=2, column=0, sticky="w", pady=(0, 4))

        self.dest_empty_lbl = ctk.CTkLabel(
            dest_section, text="No destination configured",
            font=ctk.CTkFont(size=12), text_color="#565f89")

    # ─── Cloud (Accounts) Page ────────────────────────────────────

    def _build_cloud_page(self):
        frame = ctk.CTkFrame(self.content, fg_color="#1a1b26", corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        self.pages["cloud"] = frame

        header_row = ctk.CTkFrame(frame, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        header_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header_row, text="Connected Accounts",
                     font=ctk.CTkFont(size=22, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w")

        self.add_acct_btn = ctk.CTkButton(
            header_row, text="+ Connect Account", font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, hover_color="#89b4fa", text_color="#1a1b26",
            corner_radius=8, height=34,
            command=self._show_connect_dialog,
        )
        self.add_acct_btn.grid(row=0, column=1, sticky="e")

        self.acct_content = ctk.CTkScrollableFrame(
            frame, fg_color="#1a1b26", corner_radius=0)
        self.acct_content.grid(row=1, column=0, sticky="nswe", padx=28, pady=(0, 28))
        self.acct_content.grid_columnconfigure(0, weight=1)

    # ─── Activity (Log) Page ──────────────────────────────────────

    def _build_activity_page(self):
        frame = ctk.CTkFrame(self.content, fg_color="#1a1b26", corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.pages["activity"] = frame

        header_row = ctk.CTkFrame(frame, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        header_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header_row, text="Activity Log",
                     font=ctk.CTkFont(size=22, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w")

        self.clear_log_btn = ctk.CTkButton(
            header_row, text="Clear Log", font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1, border_color="#4b5275",
            text_color="#c0caf5", corner_radius=8, height=30,
            command=self._clear_log,
        )
        self.clear_log_btn.grid(row=0, column=1, sticky="e")

        self.log_area = ctk.CTkTextbox(frame, font=ctk.CTkFont(family="Consolas", size=11),
                                       fg_color="#1e1f34", text_color="#c0caf5",
                                       corner_radius=8, border_width=1,
                                       border_color=CARD_BORDER, wrap="word")
        self.log_area.grid(row=1, column=0, sticky="nswe", padx=28, pady=(0, 28))

    # ─── Settings Page ────────────────────────────────────────────

    def _build_settings_page(self):
        frame = ctk.CTkScrollableFrame(self.content, fg_color="#1a1b26",
                                       corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        self.pages["settings"] = frame

        ctk.CTkLabel(frame, text="Settings",
                     font=ctk.CTkFont(size=22, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=28, pady=(24, 20))

        general_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                                    border_width=1, border_color=CARD_BORDER)
        general_card.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 12))
        general_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(general_card, text="General",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=3, sticky="w",
                            padx=20, pady=(16, 10))

        ctk.CTkLabel(general_card, text="Version",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=1, column=0, sticky="w", padx=20, pady=3)
        ctk.CTkLabel(general_card, text=__version__,
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=1, column=1, sticky="w", padx=8, pady=3)

        ctk.CTkLabel(general_card, text="Credential Store",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=2, column=0, sticky="w", padx=20, pady=(3, 16))
        self.cred_store_val = ctk.CTkLabel(
            general_card, text=self.core.credential_store.name(),
            font=ctk.CTkFont(size=14, weight="bold"))
        self.cred_store_val.grid(row=2, column=1, sticky="w", padx=8, pady=(3, 16))

        device_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10,
                                   border_width=1, border_color=CARD_BORDER)
        device_card.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 24))
        device_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(device_card, text="Device",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=3, sticky="w",
                            padx=20, pady=(16, 10))

        ctk.CTkLabel(device_card, text="Device ID",
                     font=ctk.CTkFont(size=12), text_color="#565f89"
                     ).grid(row=1, column=0, sticky="w", padx=20, pady=(3, 16))
        ctk.CTkLabel(device_card, text=self._get_device_id(),
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=1, column=1, sticky="w", padx=8, pady=(3, 16))

    # ─── Status & Refresh ─────────────────────────────────────────

    def _refresh_status_bar(self):
        p = self.current_profile[0]
        if p:
            self.status_profile_lbl.configure(text=p.name)
            prov_type = p.provider_config.get("type", "local")
            self.status_provider_lbl.configure(text=f"Provider: {prov_type}")
            self.status_folders_lbl.configure(text=f"{len(p.watch_dirs)} folders")
            if self.daemon_ref[0] and self.daemon_ref[0].running:
                self.status_state_lbl.configure(text="Running", text_color=GREEN)
            else:
                self.status_state_lbl.configure(text="Ready", text_color=GREEN)
        else:
            self.status_profile_lbl.configure(text="No profile")
            self.status_provider_lbl.configure(text="")
            self.status_folders_lbl.configure(text="0 folders")
            self.status_state_lbl.configure(text="Ready", text_color=GREEN)

    def _refresh_home(self):
        p = self.current_profile[0]
        if p:
            self.home_profile_val.configure(text=p.name)
            self.home_provider_val.configure(
                text=p.provider_config.get("type", "local"))
            self.home_folders_val.configure(text=str(len(p.watch_dirs)))
            if self.daemon_ref[0] and self.daemon_ref[0].running:
                self.home_status_val.configure(text="Running", text_color=GREEN)
            else:
                self.home_status_val.configure(text="Ready", text_color=GREEN)
        else:
            self.home_profile_val.configure(text="\u2014")
            self.home_provider_val.configure(text="\u2014")
            self.home_folders_val.configure(text="0")
            self.home_status_val.configure(text="Ready", text_color=GREEN)

    def _refresh_profile_view(self):
        p = self.current_profile[0]
        if not p:
            return
        self.profile_name_val.configure(text=p.name)
        for w in self.dir_list_frame.winfo_children():
            w.destroy()
        if not p.watch_dirs:
            lbl = ctk.CTkLabel(
                self.dir_list_frame, text="No folders added yet",
                font=ctk.CTkFont(size=12), text_color="#565f89")
            lbl.pack(expand=True, pady=20)
        else:
            for d in p.watch_dirs:
                lbl = ctk.CTkLabel(
                    self.dir_list_frame, text=f"  \u2022  {d}",
                    font=ctk.CTkFont(size=12), anchor="w")
                lbl.pack(fill="x", padx=6, pady=1)
        prov_type = p.provider_config.get("type", "local")
        self.prov_desc_val.configure(text=self._provider_desc(p.provider_config))
        self.sync_mode_val.configure(text="On-Close" if p.sync_on_close else "Instant")
        if p.provider_config.get("type") == "local" and not p.provider_config.get("path"):
            self.dest_empty_lbl.grid(row=2, column=0, sticky="w", pady=(0, 4))
        else:
            self.dest_empty_lbl.grid_forget()

    def _load_profile_list(self):
        for w in self.profile_list_frame.winfo_children():
            w.destroy()
        for p in self.core.profiles:
            is_active = p is self.current_profile[0]
            fg = ACCENT if is_active else "transparent"
            tc = ("#1a1b26", ACCENT) if is_active else ("#1a1b26", "#c0caf5")
            btn = ctk.CTkButton(
                self.profile_list_frame, text=p.name,
                anchor="w", fg_color=fg, text_color=tc,
                hover_color="#2f3b6b",
                font=ctk.CTkFont(size=12),
                corner_radius=6,
                command=lambda profile=p: self._switch_profile(profile),
            )
            btn.pack(fill="x", padx=4, pady=2)

    def _switch_profile(self, profile):
        if self.daemon_ref[0] and self.daemon_ref[0].running:
            self.daemon_ref[0].stop()
            self.daemon_ref[0] = None
        self.current_profile[0] = profile
        self._refresh_profile_view()
        self._load_profile_list()
        self._refresh_status_bar()
        self._refresh_home()
        self.start_stop_btn.configure(text="Start Sync")
        self.log.audit.action("profile_switched", {"profile": profile.name})

    # ─── Profile CRUD ─────────────────────────────────────────────

    def _add_profile(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("New Profile")
        dlg.geometry("420x340")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.bind("<Key-Escape>", lambda e: dlg.destroy())
        dlg.focus_set()

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(frm, text="Profile Name:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(0, 4))
        name_var = ctk.StringVar()
        name_entry = ctk.CTkEntry(frm, textvariable=name_var,
                                  font=ctk.CTkFont(size=13))
        name_entry.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(frm, text="Provider:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(0, 4))
        prov_var = ctk.StringVar(value="local")
        prov_combo = ctk.CTkOptionMenu(
            frm, variable=prov_var,
            values=("local", "dropbox", "google_drive", "onedrive"),
            font=ctk.CTkFont(size=13))
        prov_combo.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(frm, text="Account (optional):",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(0, 4))
        acct_var = ctk.StringVar(value="none")
        acct_vars = ["none"]
        for a in self.core.accounts:
            acct_vars.append(f"{a.provider}: {a.display_email or a.display_name}")
        acct_combo = ctk.CTkOptionMenu(
            frm, variable=acct_var,
            values=acct_vars,
            font=ctk.CTkFont(size=13))
        acct_combo.pack(fill="x", pady=(0, 16))

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(anchor="e")

        def do_create():
            name = name_var.get().strip()
            if not name:
                self._msg("Name required", "Enter a profile name.", "warning")
                return
            for p in self.core.profiles:
                if p.name == name:
                    self._msg("Exists", f"Profile '{name}' already exists.", "warning")
                    return
            prov_type = prov_var.get()
            config = {"type": prov_type}
            account_ref = None
            sel_acct = acct_var.get()
            if sel_acct and sel_acct != "none":
                for a in self.core.accounts:
                    key = f"{a.provider}: {a.display_email or a.display_name}"
                    if key == sel_acct:
                        account_ref = a.account_id
                        break
            if prov_type == "local":
                path = os.path.expanduser(f"~/SaveSync_{name.replace(' ', '_')}")
                config["path"] = path
            elif prov_type in ("dropbox", "google_drive", "onedrive"):
                if not account_ref:
                    self._msg("Account Required",
                              "Connect an account in the Cloud tab first.", "info",
                              on_close=lambda: [dlg.destroy(), self._open_oauth_wizard(prov_type)])
                    return
            profile = self.Profile(name, [], config, account_ref=account_ref)
            self.core.profiles.append(profile)
            self.core.save_profiles()
            self.log.audit.action("profile_created", {"profile": name, "type": prov_type})
            self._switch_profile(profile)
            dlg.destroy()

        def _create_on_key(e):
            do_create()

        ctk.CTkButton(btn_row, text="Cancel",
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      border_color="#4b5275", text_color="#c0caf5",
                      corner_radius=8, height=32,
                      command=dlg.destroy).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btn_row, text="Create",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, text_color="#1a1b26",
                      corner_radius=8, height=32,
                      command=do_create).pack(side="right")
        name_entry.bind("<Return>", _create_on_key)

    def _delete_profile(self):
        p = self.current_profile[0]
        if not p:
            return
        if len(self.core.profiles) <= 1:
            self._msg("Can't delete", "Must have at least one profile.", "warning")
            return
        ok = self._ask("Delete", f"Delete profile '{p.name}'?")
        if not ok:
            return
        self.core.profiles = [x for x in self.core.profiles if x is not p]
        self.core.save_profiles()
        self.log.audit.action("profile_deleted", {"profile": p.name})
        self._switch_profile(self.core.profiles[0])

    # ─── OAuth Wizard ─────────────────────────────────────────────

    def _open_oauth_wizard(self, provider_type: str):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(f"Connect {provider_type.title()}")
        dlg.geometry("520x420")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.bind("<Key-Escape>", lambda e: dlg.destroy())
        dlg.focus_set()

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=24, pady=20)

        registry = self.get_provider_registry()
        adapter_cls = registry.get(provider_type)
        if not adapter_cls:
            self._msg("Error", f"Unknown provider: {provider_type}", "error")
            dlg.destroy()
            return

        ctk.CTkLabel(frm, text=f"Connect to {adapter_cls.display_name}",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
                     ).pack(anchor="w", pady=(0, 12))

        client_config = {}
        if adapter_cls.needs_client_config:
            ctk.CTkLabel(frm, text=adapter_cls.client_config_label,
                         font=ctk.CTkFont(size=12), text_color="#565f89",
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(frm, text=adapter_cls.client_config_hint,
                         font=ctk.CTkFont(size=11), text_color="#565f89",
                         anchor="w").pack(anchor="w", pady=(0, 8))

            if provider_type == "google_drive":
                self._google_client_wizard(frm, client_config, dlg)
            elif provider_type in ("dropbox", "onedrive"):
                self._simple_client_wizard(frm, client_config, provider_type, dlg)
        else:
            self._local_connect_wizard(frm, client_config, dlg)

    def _google_client_wizard(self, parent, client_config, dlg):
        ctk.CTkLabel(parent, text="OAuth Client JSON file:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(4, 2))
        entry_frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry_frame.pack(fill="x")
        path_var = ctk.StringVar()
        entry = ctk.CTkEntry(entry_frame, textvariable=path_var,
                             font=ctk.CTkFont(size=12))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse():
            import tkinter.filedialog as fd
            p = fd.askopenfilename(title="Select client_secret*.json",
                                   filetypes=[("JSON", "*.json")])
            if p:
                path_var.set(p)

        ctk.CTkButton(entry_frame, text="Browse",
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      border_color="#4b5275", text_color="#c0caf5",
                      corner_radius=8, height=30,
                      command=browse).pack(side="right")

        def proceed():
            path = path_var.get().strip()
            if not path or not os.path.exists(path):
                self._msg("File required", "Select your OAuth client JSON file.", "warning")
                return
            try:
                with open(path) as f:
                    data = json.load(f)
                client_config.update(data)
                self._do_oauth_flow("google_drive", client_config, dlg)
            except Exception as e:
                self._msg("Error", f"Failed to read client config: {e}", "error")

        ctk.CTkButton(parent, text="Connect to Google",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, text_color="#1a1b26",
                      corner_radius=8, height=34,
                      command=proceed).pack(anchor="e", pady=(16, 0))

    def _simple_client_wizard(self, parent, client_config, provider_type, dlg):
        ctk.CTkLabel(parent, text="Client ID:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(4, 2))
        cid_var = ctk.StringVar()
        ctk.CTkEntry(parent, textvariable=cid_var,
                     font=ctk.CTkFont(size=12)).pack(fill="x", pady=2)
        ctk.CTkLabel(parent, text="Client Secret:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(4, 2))
        cs_var = ctk.StringVar()
        ctk.CTkEntry(parent, textvariable=cs_var,
                     font=ctk.CTkFont(size=12),
                     show="*").pack(fill="x", pady=2)

        def proceed():
            if not cid_var.get().strip():
                self._msg("Client ID required", "Enter your client ID.", "warning")
                return
            key = "app_key" if provider_type == "dropbox" else "client_id"
            secret_key = "app_secret" if provider_type == "dropbox" else "client_secret"
            client_config[key] = cid_var.get().strip()
            client_config[secret_key] = cs_var.get().strip()
            self._do_oauth_flow(provider_type, client_config, dlg)

        ctk.CTkButton(parent, text=f"Connect to {provider_type.title()}",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, text_color="#1a1b26",
                      corner_radius=8, height=34,
                      command=proceed).pack(anchor="e", pady=(16, 0))

    def _local_connect_wizard(self, parent, client_config, dlg):
        ctk.CTkLabel(parent, text="Backup folder path:",
                     font=ctk.CTkFont(size=12), anchor="w"
                     ).pack(anchor="w", pady=(4, 2))
        path_var = ctk.StringVar(value=os.path.expanduser("~/SaveSyncBackup"))
        browse_frame = ctk.CTkFrame(parent, fg_color="transparent")
        browse_frame.pack(fill="x")
        ctk.CTkEntry(browse_frame, textvariable=path_var,
                     font=ctk.CTkFont(size=12)).pack(side="left", fill="x",
                                                     expand=True, padx=(0, 6))

        def browse():
            import tkinter.filedialog as fd
            p = fd.askdirectory(title="Select backup folder")
            if p:
                path_var.set(p)

        ctk.CTkButton(browse_frame, text="Browse",
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      border_color="#4b5275", text_color="#c0caf5",
                      corner_radius=8, height=30,
                      command=browse).pack(side="right")

        def proceed():
            client_config["path"] = path_var.get().strip()
            adapter = self.LocalAdapter()
            oauth_result = self.OAuthResult("", "", 0, f"local_{uuid.uuid4().hex[:8]}",
                                            "", "Local Folder")
            account = adapter.connect(oauth_result, client_config)
            self.core.add_account(account)
            self._refresh_accounts()
            self.log.audit.action("account_connected", {"provider": "local"})
            self._msg("Connected",
                      f"Local folder connected: {client_config['path']}", "info")
            dlg.destroy()

        ctk.CTkButton(parent, text="Connect",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, text_color="#1a1b26",
                      corner_radius=8, height=34,
                      command=proceed).pack(anchor="e", pady=(16, 0))

    def _do_oauth_flow(self, provider_type, client_config, dlg):
        dlg.destroy()
        import urllib.parse
        import webbrowser
        import http.server

        state = uuid.uuid4().hex[:16]
        code_verifier = uuid.uuid4().hex[:32]
        redirect_uri = "http://127.0.0.1:18080/"

        registry = self.get_provider_registry()
        adapter = registry.get_instance(provider_type)
        if not adapter:
            self._msg("Error", f"Unknown provider: {provider_type}", "error")
            return

        auth_url = adapter.build_oauth_url(client_config, redirect_uri,
                                           state, code_verifier)

        wait_dlg = ctk.CTkToplevel(self.root)
        wait_dlg.title("Waiting for Authorization")
        wait_dlg.geometry("450x140")
        wait_dlg.transient(self.root)
        wait_dlg.grab_set()
        wait_dlg.bind("<Key-Escape>", lambda e: [auth_event.set(), wait_dlg.destroy()])
        wait_dlg.focus_set()

        ctk.CTkLabel(wait_dlg,
                     text="Your browser will open.\nAuthorize the app, then return here.",
                     font=ctk.CTkFont(size=12), wraplength=400).pack(pady=16)
        ctk.CTkLabel(wait_dlg, text=adapter.display_name,
                     font=ctk.CTkFont(size=14, weight="bold")).pack()
        status_lbl = ctk.CTkLabel(wait_dlg, text="Waiting for browser authorization...",
                                  font=ctk.CTkFont(size=11))
        status_lbl.pack(pady=(8, 0))
        cancel_btn = ctk.CTkButton(wait_dlg, text="Cancel",
                                   font=ctk.CTkFont(size=12),
                                   fg_color="transparent", border_width=1,
                                   border_color="#4b5275", text_color="#c0caf5",
                                   corner_radius=8, height=30)
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
        server_thread = threading.Thread(target=lambda: self._serve_until(server, auth_event), daemon=True)
        server_thread.start()

        def _check_oauth():
            if auth_event.is_set():
                server.server_close()
                wait_dlg.destroy()
                code = code_result[0]
                if not code:
                    self._msg("Cancelled",
                              "Authentication was cancelled or timed out.", "warning")
                    return
                status_lbl.configure(text="Exchanging token...")
                self.root.update_idletasks()
                self.root.after(10, lambda: self._finish_oauth(provider_type, client_config,
                                                               code, code_verifier, adapter))
            elif not wait_dlg.winfo_exists():
                server.server_close()
                return
            else:
                self.root.after(200, _check_oauth)

        cancel_btn.configure(command=lambda: [auth_event.set(), wait_dlg.destroy()])
        self.root.after(200, _check_oauth)

    def _serve_until(self, srv, stop_event):
        srv.timeout = 0.5
        deadline = time.time() + 120
        while not stop_event.is_set() and time.time() < deadline:
            srv.handle_request()
        srv.server_close()

    def _finish_oauth(self, provider_type, client_config, code, code_verifier, adapter):
        try:
            oauth_result = adapter.exchange_code(client_config,
                                                 "http://127.0.0.1:18080/",
                                                 code, code_verifier)
            account = adapter.connect(oauth_result, client_config)
            self.core.add_account(account)
            self._refresh_accounts()
            self.log.audit.action("account_connected",
                                  {"provider": provider_type, "account": account.account_id})
            self._msg("Connected",
                      f"{adapter.display_name} connected as "
                      f"{account.display_email or account.display_name}", "info")
        except Exception as e:
            self._msg("Auth Failed", f"Token exchange failed: {e}", "error")

    # ─── Accounts ─────────────────────────────────────────────────

    def _refresh_accounts(self):
        for w in self.acct_content.winfo_children():
            w.destroy()
        if not self.core.accounts:
            ctk.CTkLabel(self.acct_content,
                         text="No accounts connected yet",
                         font=ctk.CTkFont(size=14),
                         text_color="#565f89").pack(expand=True, pady=40)
            ctk.CTkLabel(self.acct_content,
                         text="Click \"Connect Account\" to add Google Drive, Dropbox, OneDrive, or Local Folder.",
                         font=ctk.CTkFont(size=12),
                         text_color="#565f89").pack()

        for account in self.core.accounts:
            card = ctk.CTkFrame(self.acct_content, fg_color=CARD_BG,
                                corner_radius=10, border_width=1,
                                border_color=CARD_BORDER)
            card.pack(fill="x", pady=(0, 10))
            card.grid_columnconfigure(1, weight=1)

            adapter = self.core.provider_registry.get_instance_for_account(account)
            if adapter:
                ok, status = adapter.status(account)
                status_color = GREEN if ok else RED
            else:
                ok, status = False, "unknown"
                status_color = YELLOW

            ctk.CTkLabel(card,
                         text=account.display_name or account.provider,
                         font=ctk.CTkFont(size=14, weight="bold")
                         ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(card,
                         text=account.display_email,
                         font=ctk.CTkFont(size=12),
                         text_color="#565f89"
                         ).grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(14, 2))
            ctk.CTkLabel(card,
                         text=status,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=status_color
                         ).grid(row=0, column=2, sticky="e", padx=(0, 16), pady=(14, 2))

            ctk.CTkLabel(card,
                         text=f"Provider: {account.provider}  |  ID: {account.account_id[:12]}...",
                         font=ctk.CTkFont(size=11),
                         text_color="#565f89"
                         ).grid(row=1, column=0, columnspan=2, sticky="w",
                                padx=16, pady=(0, 14))

            def disconnect(a=account):
                ok = self._ask("Disconnect", f"Disconnect {a.display_name or a.provider}?")
                if ok:
                    self.core.remove_account(a.account_id)
                    self._refresh_accounts()
                    self.log.audit.action("account_disconnected", {"provider": a.provider})

            ctk.CTkButton(card, text="Disconnect",
                          font=ctk.CTkFont(size=12),
                          fg_color="#3b1f2e", hover_color="#4c2435",
                          text_color=RED, corner_radius=8, height=30,
                          command=disconnect).grid(row=1, column=2, sticky="e",
                                                   padx=(0, 16), pady=(0, 10))

    # ─── Connect Dialog ───────────────────────────────────────────

    def _show_connect_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Connect Account")
        dlg.geometry("380x300")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.bind("<Key-Escape>", lambda e: dlg.destroy())
        dlg.focus_set()

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(frm, text="Select provider type:",
                     font=ctk.CTkFont(size=14, weight="bold"), anchor="w"
                     ).pack(anchor="w", pady=(0, 14))

        for prov in ["google_drive", "dropbox", "onedrive", "local"]:
            registry = self.get_provider_registry()
            cls = registry.get(prov)
            if cls:
                btn = ctk.CTkButton(
                    frm, text=cls.display_name,
                    font=ctk.CTkFont(size=13),
                    fg_color="transparent", border_width=1,
                    border_color="#4b5275", text_color="#c0caf5",
                    corner_radius=8, height=34,
                    command=lambda p=prov: [self._open_oauth_wizard(p), dlg.destroy()],
                )
                btn.pack(fill="x", pady=3)

    # ─── Sync / Restore ───────────────────────────────────────────

    def _toggle_sync_mode(self):
        p = self.current_profile[0]
        if not p:
            return
        p.sync_on_close = not p.sync_on_close
        self.core.save_profiles()
        self._refresh_profile_view()

    def _browse_provider_path(self):
        p = self.current_profile[0]
        if not p:
            return
        if p.provider_config.get("type") != "local":
            self._msg("Cloud Provider", "Path is managed by the cloud provider.", "info")
            return
        import tkinter.filedialog as fd
        path = fd.askdirectory(
            title="Select backup destination",
            initialdir=p.provider_config.get("path", os.path.expanduser("~")))
        if path:
            p.provider_config["path"] = path
            self.core.save_profiles()
            self._refresh_profile_view()

    def _add_dir(self):
        p = self.current_profile[0]
        if not p:
            return
        import tkinter.filedialog as fd
        path = fd.askdirectory(title="Select save folder")
        if path and path not in p.watch_dirs:
            p.watch_dirs.append(path)
            self.core.save_profiles()
            self.log.audit.action("watch_dir_added", {"profile": p.name, "path": path})
            self._refresh_profile_view()

    def _remove_dir(self):
        p = self.current_profile[0]
        if not p:
            return
        import tkinter.filedialog as fd
        from tkinter import messagebox as mb
        from tkinter import simpledialog
        items = self.dir_list_frame.winfo_children()
        if not items or len(items) == 0 or (
            len(items) == 1 and isinstance(items[0], ctk.CTkLabel)
            and "No folders added yet" in items[0].cget("text")):
            return
        sel_dlg = ctk.CTkToplevel(self.root)
        sel_dlg.title("Remove Folder")
        sel_dlg.geometry("300x200")
        sel_dlg.transient(self.root)
        sel_dlg.grab_set()
        sel_dlg.focus_set()

        ctk.CTkLabel(sel_dlg, text="Select folder to remove:",
                     font=ctk.CTkFont(size=12)).pack(pady=(12, 6))

        list_frame = ctk.CTkScrollableFrame(sel_dlg, fg_color="#1e1f34",
                                             corner_radius=6,
                                             height=100)
        list_frame.pack(fill="x", padx=12, pady=(0, 8))

        selected = [None]

        for d in p.watch_dirs:
            btn = ctk.CTkButton(
                list_frame, text=d,
                anchor="w", fg_color="transparent",
                text_color="#c0caf5", font=ctk.CTkFont(size=11),
                corner_radius=4,
                command=lambda path=d, b=None: None,
            )
            btn.pack(fill="x", padx=4, pady=1)
            actual_btn = btn

            def make_cb(path=d, button=actual_btn):
                def cb():
                    selected[0] = path
                    for child in list_frame.winfo_children():
                        child.configure(fg_color="transparent")
                    button.configure(fg_color="#2f3b6b")
                return cb
            btn.configure(command=make_cb())

        def do_remove():
            if selected[0] is None:
                self._msg("Select", "Select a folder to remove.", "warning")
                return
            p.watch_dirs.remove(selected[0])
            self.core.save_profiles()
            self.log.audit.action("watch_dir_removed", {"profile": p.name, "path": selected[0]})
            self._refresh_profile_view()
            sel_dlg.destroy()

        ctk.CTkButton(sel_dlg, text="Remove",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color="#3b1f2e", text_color=RED,
                      corner_radius=8, height=32,
                      command=do_remove).pack(pady=(4, 12))

    def _toggle_sync(self):
        p = self.current_profile[0]
        if not p:
            return
        if self.daemon_ref[0] and self.daemon_ref[0].running:
            self.daemon_ref[0].stop()
            self.daemon_ref[0] = None
            self.start_stop_btn.configure(text="Start Sync")
            self.sync_now_btn.configure(text="Sync Now")
            self._refresh_status_bar()
            self._refresh_home()
            self.log.audit.action("sync_stopped", {"profile": p.name})
            return
        if not p.watch_dirs:
            self._msg("No Folders", "Add at least one watched folder.", "warning")
            return
        self.daemon_ref[0] = self.SaveSyncDaemon(self.core, p)
        self.daemon_ref[0].start()
        self.start_stop_btn.configure(text="Stop Sync")
        self.sync_now_btn.configure(text="Sync Now")
        self._refresh_status_bar()
        self._refresh_home()
        self.log.audit.action("sync_started", {"profile": p.name})

    def _stop_progress_polling(self):
        if self._progress_after_id:
            try:
                self.root.after_cancel(self._progress_after_id)
            except Exception:
                pass
            self._progress_after_id = None

    def _start_progress_polling(self, gen):
        self._stop_progress_polling()

        def _poll():
            if gen != self._operation_gen:
                return
            worker = self.sync_worker_ref[0]
            if not worker or not worker.is_running or not worker.op_state:
                self._progress_after_id = self.root.after(200, _poll)
                return
            snap = worker.op_state.snapshot()

            phase = snap.phase or ""
            if phase in ("Scanning", "Preparing"):
                self.progress_bar.set(0)
            elif snap.bytes_total > 0:
                pct = min(1.0, snap.bytes_transferred / snap.bytes_total)
                self.progress_bar.set(pct)

            self.file_lbl.configure(text=snap.current_file or phase or "")
            if snap.bytes_total > 0:
                b = self._fmt_bytes(snap.bytes_transferred)
                t = self._fmt_bytes(snap.bytes_total)
                files_info = ""
                if snap.files_total > 0:
                    files_info = f"  ({snap.files_completed}/{snap.files_total} files)"
                self.bytes_lbl.configure(text=f"{b} of {t}{files_info}")
            else:
                self.bytes_lbl.configure(text=self._fmt_bytes(snap.bytes_transferred))

            if snap.speed_bps > 0:
                eta_secs = 0
                if snap.bytes_total > 0:
                    remaining = max(0, snap.bytes_total - snap.bytes_transferred)
                    eta_secs = remaining / snap.speed_bps
                speed_str = f"{self._fmt_bytes(snap.speed_bps)}/s"
                if snap.phase in ("Uploading", "Downloading") and 0 < eta_secs < 86400:
                    speed_str += f"  ETA: {self._fmt_duration(eta_secs)}"
                self.speed_lbl.configure(text=speed_str)

            self._progress_after_id = self.root.after(200, _poll)

        _poll()

    def _handle_done(self, success, message, stats=None):
        self._stop_progress_polling()
        self.progress_bar.set(1.0 if success else 0)
        self.cancel_btn.configure(state="disabled")
        if message:
            self.file_lbl.configure(text=message)
        if stats:
            dur = stats.get("duration_ms", 0) / 1000
            spd = stats.get("speed_bps", 0)
            parts = []
            if dur > 0:
                parts.append(f"{dur:.1f}s")
            if spd > 0:
                parts.append(f"{self._fmt_bytes(spd)}/s")
            if parts:
                self.bytes_lbl.configure(text="  ".join(parts))
        self.sync_now_btn.configure(text="Sync Now", state="normal",
                                    fg_color=ACCENT, text_color="#1a1b26")
        self.restore_btn.configure(text="Restore", state="normal",
                                   fg_color="transparent", text_color="#c0caf5")
        self.start_stop_btn.configure(state="normal")
        self.add_prof_btn.configure(state="normal")
        self._refresh_status_bar()
        self._refresh_home()

    def _cancel_operation(self):
        self._operation_gen += 1
        worker = self.sync_worker_ref[0]
        self.sync_worker_ref[0] = None
        if worker:
            worker.cancel()

    def _sync_now(self):
        p = self.current_profile[0]
        if not p:
            return
        if self.sync_worker_ref[0] and self.sync_worker_ref[0].is_running:
            self._cancel_operation()
            self.sync_now_btn.configure(text="Sync Now",
                                        fg_color=ACCENT, text_color="#1a1b26")
            self.restore_btn.configure(text="Restore",
                                       fg_color="transparent", text_color="#c0caf5")
            self.start_stop_btn.configure(state="normal")
            self.add_prof_btn.configure(state="normal")
            return
        self._operation_gen += 1
        my_gen = self._operation_gen

        def _gen_guard(success, message, stats=None):
            if my_gen == self._operation_gen:
                self._handle_done(success, message, stats)

        self.log.audit.action("manual_sync", {"profile": p.name})
        worker = self.SyncWorker(self.core, p)
        self.sync_worker_ref[0] = worker
        self.sync_now_btn.configure(text="Cancel", fg_color="#3b1f2e", text_color=RED)
        self.restore_btn.configure(text="Restore", state="disabled",
                                   fg_color="transparent", text_color="#565f89")
        self.start_stop_btn.configure(state="disabled")
        self.add_prof_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.file_lbl.configure(text="Starting sync...")
        self.bytes_lbl.configure(text="")
        self.speed_lbl.configure(text="")
        self.progress_bar.set(0)
        self._start_progress_polling(my_gen)
        worker.sync_all(done_callback=_gen_guard)

    def _restore(self):
        p = self.current_profile[0]
        if not p:
            return
        if self.sync_worker_ref[0] and self.sync_worker_ref[0].is_running:
            self._cancel_operation()
            self.sync_now_btn.configure(text="Sync Now", fg_color=ACCENT, text_color="#1a1b26")
            self.restore_btn.configure(text="Restore", fg_color="transparent", text_color="#c0caf5")
            self.start_stop_btn.configure(state="normal")
            self.add_prof_btn.configure(state="normal")
            return
        ok = self._ask("Restore",
                       "Restore all missing files from backup? "
                       "This will download files that don't exist locally.")
        if not ok:
            return
        self._operation_gen += 1
        my_gen = self._operation_gen

        def _gen_guard(success, message, stats=None):
            if my_gen == self._operation_gen:
                self._handle_done(success, message, stats)

        self.log.audit.action("restore_requested", {"profile": p.name})
        worker = self.SyncWorker(self.core, p)
        self.sync_worker_ref[0] = worker
        self.restore_btn.configure(text="Cancel", fg_color="#3b1f2e", text_color=RED)
        self.sync_now_btn.configure(text="Sync Now", state="disabled",
                                    fg_color="transparent", text_color="#565f89")
        self.start_stop_btn.configure(state="disabled")
        self.add_prof_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.file_lbl.configure(text="Starting restore...")
        self.bytes_lbl.configure(text="")
        self.speed_lbl.configure(text="")
        self.progress_bar.set(0)
        self._start_progress_polling(my_gen)
        worker.restore_all(done_callback=_gen_guard)

    def _clear_log(self):
        self.log_area.delete("1.0", "end")

    # ─── Onboarding ───────────────────────────────────────────────

    def _show_onboarding(self):
        if len(self.core.accounts) > 0:
            return
        if self.core.profiles and self.core.profiles[0].provider_config.get("type") == "local" and os.path.exists(
            os.path.expanduser("~/SaveSyncBackup")):
            return
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Welcome to SaveSync")
        dlg.geometry("540x400")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.bind("<Key-Escape>", lambda e: dlg.destroy())
        dlg.focus_set()

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=28, pady=24)

        ctk.CTkLabel(frm, text="Welcome to SaveSync",
                     font=ctk.CTkFont(size=18, weight="bold"), anchor="w"
                     ).pack(anchor="w", pady=(0, 16))
        ctk.CTkLabel(frm,
                     text="SaveSync keeps your save files backed up and synced across devices.\n\n"
                          "You can use it with:\n"
                          "  \u2022 Local folders (no account needed)\n"
                          "  \u2022 Google Drive (BYO OAuth client)\n"
                          "  \u2022 Dropbox (BYO app key)\n"
                          "  \u2022 OneDrive (BYO app registration)\n\n"
                          "Get started by connecting a storage provider, "
                          "or use a local folder right away.",
                     font=ctk.CTkFont(size=12),
                     wraplength=480, justify="left").pack(anchor="w", pady=(0, 24))

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(fill="x")

        ctk.CTkButton(btn_row, text="Use Local Folder",
                      font=ctk.CTkFont(size=13),
                      fg_color="transparent", border_width=1,
                      border_color="#4b5275", text_color="#c0caf5",
                      corner_radius=8, height=34,
                      command=lambda: [self._setup_local_onboarding(), dlg.destroy()]
                      ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Connect a Provider",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, text_color="#1a1b26",
                      corner_radius=8, height=34,
                      command=lambda: [dlg.destroy(), self._show_connect_dialog()]
                      ).pack(side="right")

    def _setup_local_onboarding(self):
        adapter = self.LocalAdapter()
        path = os.path.expanduser("~/SaveSyncBackup")
        result = self.OAuthResult("", "", 0, f"local_{uuid.uuid4().hex[:8]}", "", "Local Folder")
        account = adapter.connect(result, {"path": path})
        self.core.add_account(account)
        self._refresh_accounts()
        for p in self.core.profiles:
            if p.provider_config.get("type") == "local":
                p.provider_config["path"] = path
                self.core.save_profiles()
                break
        self.log.audit.action("onboarding_completed", {"type": "local"})

    # ─── On Close ─────────────────────────────────────────────────

    def _on_close(self):
        self._stop_progress_polling()
        self._operation_gen += 1

        worker = self.sync_worker_ref[0]
        if worker and worker.is_running:
            worker.cancel()
            try:
                worker._thread.join(timeout=5)
            except Exception:
                pass
            if worker._thread and worker._thread.is_alive():
                self.core.log("Shutdown: sync worker thread abandoned")
            self.sync_worker_ref[0] = None

        p = self.current_profile[0]
        if p and p.sync_on_close:
            if self.daemon_ref[0] and self.daemon_ref[0].running:
                self.daemon_ref[0].sync_all_now()
                self.daemon_ref[0].stop()
            else:
                d = self.SaveSyncDaemon(self.core, p)
                d.sync_all_now()
        elif self.daemon_ref[0] and self.daemon_ref[0].running:
            self.daemon_ref[0].stop()

        self.log_shutdown()
        self.root.destroy()

    # ─── Auto CLI ─────────────────────────────────────────────────

    def _auto_sync(self):
        p = self.current_profile[0]
        if not p:
            _startup_log("--sync-now: no profile loaded, aborting")
            return
        if not p.watch_dirs:
            _startup_log("--sync-now: no watch dirs configured, aborting")
            return
        self._sync_now()

    def _auto_cancel(self):
        _startup_log("--cancel-after: triggering cancel")
        if self.sync_worker_ref[0] and self.sync_worker_ref[0].is_running:
            self._cancel_operation()
            self.sync_now_btn.configure(text="Sync Now", fg_color=ACCENT, text_color="#1a1b26")
            self.restore_btn.configure(text="Restore", fg_color="transparent", text_color="#c0caf5")
            self.start_stop_btn.configure(state="normal")
            self.add_prof_btn.configure(state="normal")
            _startup_log("--cancel-after: cancel triggered")
        else:
            _startup_log("--cancel-after: no running operation to cancel")

    def _auto_close(self):
        _startup_log("--close-after: triggering close")
        self._on_close()

    # ─── Dialogs ──────────────────────────────────────────────────

    def _msg(self, title, message, kind="info", on_close=None):
        from tkinter import messagebox as mb
        if kind == "warning":
            mb.showwarning(title, message)
        elif kind == "error":
            mb.showerror(title, message)
        else:
            mb.showinfo(title, message)
        if on_close:
            on_close()

    def _ask(self, title, message):
        from tkinter import messagebox as mb
        return mb.askyesno(title, message)


def _main_impl(sync_now_flag=False, cancel_after=None, close_after=None):
    app = SaveSyncApp(sync_now_flag, cancel_after, close_after)
    return app


if __name__ == "__main__":
    main()

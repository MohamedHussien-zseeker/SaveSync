"""Take screenshots of each SaveSync tab for the README.
Run under Xvfb: python3 assets/take_screenshots.py"""
import sys, os, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk

# Patch: the app imports normally
sys.argv = ['SaveSync.py', '--gui-smoke-test']
import SaveSync

# Copy-paste the _main_impl internals we need
from core import SaveSyncCore
from logging_system import get_logging_system
from state import OperationState
from providers import get_provider_registry, LocalAdapter
from exceptions import SaveSyncError
import uuid, json, os as os_mod, threading, time as time_mod, hashlib, shutil
from pathlib import Path
from config_sync import ConfigSync
import tkinter.filedialog, tkinter.messagebox, tkinter.simpledialog

log = get_logging_system()
core = SaveSyncCore()

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
BORDER = "#4b5275"
SEL_BG = "#2f3b6b"

style = ttk.Style()
style.theme_use("clam")
style.configure(".", background=BG, foreground=FG, fieldbackground=BG2,
                selectbackground=SEL_BG, selectforeground=FG,
                borderwidth=0, focuscolor=ACCENT)
style.configure("TFrame", background=BG)
style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
style.configure("TButton", background=BG2, foreground=FG, font=("Segoe UI", 9),
                borderwidth=1, relief="flat", padding=(12, 6))
style.map("TButton", background=[("active", SEL_BG), ("pressed", ACCENT)],
          foreground=[("active", FG)])
style.configure("Primary.TButton", background=ACCENT, foreground=BG,
                font=("Segoe UI", 10, "bold"), padding=(16, 8))
style.map("Primary.TButton", background=[("active", "#89b4fa"), ("pressed", "#5a8cf5")],
          foreground=[("active", BG)])
style.configure("Destructive.TButton", background="#3b1f2e", foreground=RED,
                font=("Segoe UI", 9), padding=(12, 6))
style.map("Destructive.TButton", background=[("active", "#4c2435"), ("pressed", "#5a293c")],
          foreground=[("active", RED)])
style.configure("Small.TButton", font=("Segoe UI", 8), padding=(8, 3))
style.configure("TEntry", fieldbackground=BG2, foreground=FG, insertcolor=FG,
                borderwidth=1, relief="solid", padding=6)
style.configure("TCombobox", fieldbackground=BG2, foreground=FG,
                selectbackground=SEL_BG, arrowcolor=FG, padding=4)
style.map("TCombobox", fieldbackground=[("readonly", BG2)])
style.configure("Treeview", background=BG2, foreground=FG, fieldbackground=BG2,
                rowheight=32, font=("Segoe UI", 9))
style.map("Treeview", background=[("selected", SEL_BG)], foreground=[("selected", FG)])
style.configure("Treeview.Heading", background=BG, foreground=FG2,
                font=("Segoe UI", 9, "bold"), borderwidth=0,
                relief="flat", padding=(6, 4))
style.map("Treeview.Heading", background=[("active", BG2)])
style.configure("Header.TLabel", background=BG, foreground=ACCENT,
                font=("Segoe UI", 10, "bold"))
style.configure("Section.TLabel", background=BG, foreground=FG2,
                font=("Segoe UI", 9, "bold"))
style.configure("Empty.TLabel", background=BG, foreground=FG2,
                font=("Segoe UI", 9))
style.configure("StatusBar.TLabel", background=BG2, foreground=FG2,
                font=("Segoe UI", 9))
style.configure("Card.TFrame", background=BG3, relief="solid", borderwidth=1)
style.configure("CardLabel.TLabel", background=BG3, foreground=FG,
                font=("Segoe UI", 10))
style.configure("CardHeader.TLabel", background=BG3, foreground=ACCENT,
                font=("Segoe UI", 10, "bold"))
style.configure("CardEmpty.TLabel", background=BG3, foreground=FG2,
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
status_sync_state_lbl = ttk.Label(inner_status, text="Ready",
                                  style="StatusBar.TLabel")
status_sync_state_lbl.pack(side=tk.LEFT, padx=(0, 16))
version_lbl = ttk.Label(inner_status, text=f"v{SaveSync.__version__}",
                        style="StatusBar.TLabel",
                        foreground=FG)
version_lbl.pack(side=tk.RIGHT)

notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 0))

tab_names = ["Dashboard", "Profiles", "Accounts", "Activity", "Settings"]
tabs = {}

for name in tab_names:
    frame = ttk.Frame(notebook)
    notebook.add(frame, text=name)
    tabs[name] = frame

# --- Dashboard tab ---
dash_frame = tabs["Dashboard"]

# Welcome card
welcome = ttk.Frame(dash_frame, style="Card.TFrame")
welcome.pack(fill=tk.X, pady=(0, 12), ipadx=12, ipady=12)
tlabel = ttk.Label(welcome, text="Welcome to SaveSync", style="CardHeader.TLabel")
tlabel.pack(anchor=tk.W, padx=12, pady=(12, 4))
ttk.Label(welcome, text="Your game saves, protected.", style="CardLabel.TLabel").pack(anchor=tk.W, padx=12, pady=(0, 12))

# Quick actions
actions = ttk.Frame(dash_frame)
actions.pack(fill=tk.X, pady=(0, 12))
ttk.Label(actions, text="Quick Actions", style="Section.TLabel").pack(anchor=tk.W)
btn_row = ttk.Frame(actions)
btn_row.pack(fill=tk.X, pady=(8, 0))
for text in ["Sync Now", "Restore", "Backup All", "Verify Backups"]:
    ttk.Button(btn_row, text=text, style="TButton").pack(side=tk.LEFT, padx=(0, 8))

# Progress section
progress_frame = ttk.Frame(dash_frame)
progress_frame.pack(fill=tk.X, pady=(0, 12))
ttk.Label(progress_frame, text="Recent Activity", style="Section.TLabel").pack(anchor=tk.W)
ttk.Label(progress_frame, text="No recent activity. Create a profile to get started.",
          style="Empty.TLabel").pack(anchor=tk.W, pady=(8, 0))

# Activity overview
overview = ttk.Frame(dash_frame)
overview.pack(fill=tk.BOTH, expand=True)
ttk.Label(overview, text="Overview", style="Section.TLabel").pack(anchor=tk.W)
cards = ttk.Frame(overview)
cards.pack(fill=tk.X, pady=(8, 0))
card_data = [
    ("Profiles", "0 active", "Create profiles to manage backups"),
    ("Storage Used", "0 B", "Sync files to see storage usage"),
    ("Last Sync", "Never", "Run your first sync to populate"),
]
for title, value, desc in card_data:
    card = ttk.Frame(cards, style="Card.TFrame")
    card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipadx=8, ipady=8)
    ttk.Label(card, text=title, style="CardHeader.TLabel").pack(anchor=tk.W, padx=8, pady=(8, 2))
    ttk.Label(card, text=value, style="CardLabel.TLabel",
              font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, padx=8)
    ttk.Label(card, text=desc, style="CardEmpty.TLabel",
              wraplength=180).pack(anchor=tk.W, padx=8, pady=(0, 8))

# --- Profiles tab ---
prof_frame = tabs["Profiles"]
top_bar = ttk.Frame(prof_frame)
top_bar.pack(fill=tk.X)
ttk.Label(top_bar, text="My Profiles", style="Header.TLabel").pack(side=tk.LEFT)
btn_container = ttk.Frame(top_bar)
btn_container.pack(side=tk.RIGHT)
ttk.Button(btn_container, text="+ Add Profile", style="Primary.TButton").pack(side=tk.LEFT, padx=(0, 4))
ttk.Button(btn_container, text="Delete", style="Destructive.TButton").pack(side=tk.LEFT)

tree_frame = ttk.Frame(prof_frame)
tree_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
tree = ttk.Treeview(tree_frame, columns=("name",), show="headings",
                    selectmode="browse")
tree.heading("name", text="Profile Name")
tree.column("name", width=300)
tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
tree.configure(yscrollcommand=scrollbar.set)

# Insert a sample profile
tree.insert("", tk.END, values=("Default",))

# Profile detail
detail_frame = ttk.LabelFrame(prof_frame, text="Profile Details", style="Card.TFrame")
detail_frame.pack(fill=tk.X, pady=(8, 0))
ttk.Label(detail_frame, text="Select a profile to view details.",
          style="Empty.TLabel").pack(pady=12)

# --- Accounts tab ---
acct_frame = tabs["Accounts"]
acct_top = ttk.Frame(acct_frame)
acct_top.pack(fill=tk.X)
ttk.Label(acct_top, text="Connected Accounts", style="Header.TLabel").pack(side=tk.LEFT)
ttk.Button(acct_top, text="+ Connect Account", style="Primary.TButton").pack(side=tk.RIGHT)
acct_content = ttk.Frame(acct_frame)
acct_content.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
ttk.Label(acct_content, text="No accounts connected. Click 'Connect Account' to add one.",
          style="Empty.TLabel").pack(pady=24)

# --- Activity tab ---
act_frame = tabs["Activity"]
act_top = ttk.Frame(act_frame)
act_top.pack(fill=tk.X)
ttk.Label(act_top, text="Activity Log", style="Header.TLabel").pack(side=tk.LEFT)
ttk.Button(act_top, text="Clear Log", style="TButton").pack(side=tk.RIGHT)
log_frame = ttk.Frame(act_frame)
log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
log_text = tk.Text(log_frame, height=10, font=("Consolas", 9), bg=BG2, fg=FG,
                   insertbackground=FG, relief="flat", borderwidth=0,
                   selectbackground=SEL_BG, highlightbackground=BORDER,
                   highlightcolor=BORDER, highlightthickness=0)
log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_text.yview)
log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
log_text.configure(yscrollcommand=log_scroll.set)
log_text.insert(tk.END, "Welcome to SaveSync v" + SaveSync.__version__ + "\n")
log_text.insert(tk.END, "No activity yet. Sync or restore to see events here.\n")
log_text.insert(tk.END, "Use the Log Filter above to filter by event type.\n")

# --- Settings tab ---
set_frame = tabs["Settings"]
ttk.Label(set_frame, text="Settings", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 12))
settings_items = [
    ("General", [
        ("Launch on startup", "Automatically start SaveSync when you log in"),
        ("Minimize to tray", "Keep SaveSync running in the system tray"),
        ("Auto-sync on close", "Sync your saves when you close a game"),
    ]),
    ("Notifications", [
        ("Sync complete alerts", "Show a notification when sync finishes"),
        ("Error alerts", "Show a notification when an error occurs"),
    ]),
    ("Backup", [
        ("Max backups per file", "3"),
        ("Verify after sync", "Check SHA-256 after every copy"),
    ]),
]
for section_title, items in settings_items:
    sec = ttk.LabelFrame(set_frame, text=section_title, style="Card.TFrame")
    sec.pack(fill=tk.X, pady=(0, 8))
    for label, desc in items:
        row = ttk.Frame(sec)
        row.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row, text=label, style="CardLabel.TLabel").pack(side=tk.LEFT)
        ttk.Label(row, text=desc, style="CardEmpty.TLabel").pack(side=tk.RIGHT)

root.update_idletasks()
root.update()

# Take screenshots
output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(output_dir, exist_ok=True)

# Map tab index to name
tab_labels = ["dashboard", "profiles", "accounts", "activity", "settings"]

for i in range(notebook.index("end")):
    notebook.select(i)
    root.update_idletasks()
    root.update()
    time_mod.sleep(0.3)
    x = root.winfo_x()
    y = root.winfo_y()
    w = root.winfo_width()
    h = root.winfo_height()
    filename = os.path.join(output_dir, f"{tab_labels[i]}.png")
    subprocess.run(["import", "-window", "root", "-crop", f"{w}x{h}+{x}+{y}", filename],
                   capture_output=True)
    print(f"Saved: {filename}")

root.destroy()
print("All screenshots captured.")

"""Take screenshots of each SaveSync page for documentation.
Run under Xvfb: python3 assets/take_screenshots.py"""
import sys, os, subprocess, time as time_mod
import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prevent mainloop from blocking
saved_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self: None

import SaveSync
# Patch onboarding to noop so it doesn't pop up a dialog
SaveSync.SaveSyncApp._show_onboarding = lambda self: None

app = SaveSync._main_impl()
root = app.root
root.geometry("960x720")
root.update()

output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(output_dir, exist_ok=True)

page_order = ["home", "games", "cloud", "activity", "settings"]
page_names = {"home": "dashboard", "games": "profiles", "cloud": "accounts",
              "activity": "activity", "settings": "settings"}

for page in page_order:
    app._show_page(page)
    root.update_idletasks()
    root.update()
    time_mod.sleep(0.3)
    x = root.winfo_x()
    y = root.winfo_y()
    w = root.winfo_width()
    h = root.winfo_height()
    filename = os.path.join(output_dir, f"{page_names[page]}.png")
    subprocess.run(["import", "-window", "root", "-crop", f"{w}x{h}+{x}+{y}", filename],
                   capture_output=True)
    print(f"Saved: {filename}")

root.destroy()
tk.Tk.mainloop = saved_mainloop
print("All screenshots captured.")

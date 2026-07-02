"""Reusable UI interaction wrappers for workflow tests.

Provides stable, intent-based helpers for common UI operations
so workflow tests read as scenarios rather than Tkinter plumbing.
"""


def navigate_to(app, page_name):
    btn = app.nav_btns.get(page_name)
    if btn:
        btn.invoke()


def click_button(button):
    button.invoke()


def set_entry_text(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)




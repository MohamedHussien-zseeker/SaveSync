"""Custom assertion helpers for workflow tests."""
import tkinter as tk


def assert_text_visible(widget, substring: str) -> None:
    text = ""
    try:
        text = widget.cget("text") or ""
    except (tk.TclError, AttributeError):
        try:
            text = widget.get("1.0", "end-1c")
        except Exception:
            pass
    assert substring in text, f"Expected '{substring}' in widget text, got: {text[:200]}"


def assert_button_enabled(button) -> None:
    state = str(button.cget("state"))
    assert state != "disabled", f"Button '{button.cget('text')}' is disabled but should be enabled"


def assert_button_disabled(button) -> None:
    state = str(button.cget("state"))
    assert state == "disabled", f"Button '{button.cget('text')}' is enabled but should be disabled"


def assert_status(notebook, tab_index: int, expected_text: str) -> None:
    actual = notebook.tab(tab_index, "text").strip()
    assert actual == expected_text, f"Tab {tab_index}: expected '{expected_text}', got '{actual}'"


def assert_log_contains(log_area, substring: str) -> None:
    content = log_area.get("1.0", "end-1c")
    assert substring in content, f"Log does not contain '{substring}'.\nLog content:\n{content[:500]}"

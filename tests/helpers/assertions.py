"""Custom assertion helpers for workflow tests."""


def assert_text_visible(widget, substring):
    text = ""
    try:
        text = widget.cget("text") or ""
    except Exception:
        try:
            text = widget.get("1.0", "end-1c")
        except Exception:
            pass
    assert substring in text, f"Expected '{substring}' in widget text, got: {text[:200]}"


def assert_button_enabled(button):
    state = str(button.cget("state"))
    assert state != "disabled", f"Button '{button.cget('text')}' is disabled but should be enabled"


def assert_button_disabled(button):
    state = str(button.cget("state"))
    assert state == "disabled", f"Button '{button.cget('text')}' is enabled but should be disabled"


def assert_log_contains(log_area, substring):
    content = log_area.get("1.0", "end-1c")
    assert substring in content, f"Log does not contain '{substring}'.\nLog content:\n{content[:500]}"

"""Shared fixtures for workflow tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from tests.fixtures.app_factory import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create a SaveSync test app.

    Yields (root, refs). The app is torn down after the test.
    """
    root, refs = create_app(tmp_path, monkeypatch)
    try:
        yield root, refs
    finally:
        try:
            root.destroy()
        except Exception:
            pass

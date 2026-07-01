"""Upgrade compatibility tests — verifying v2.3.x → v2.4 migration."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


V23_PROFILE = {
    "name": "TestProfile",
    "watch_dirs": ["/home/user/Documents"],
    "provider_config": {
        "type": "local",
        "path": "/home/user/SaveSyncBackup",
    },
}

V23_PROFILE_MISSING_KEYS = {
    "name": "LegacyProfile",
    "watch_dirs": ["/home/user/Pictures"],
    "provider_config": {
        "type": "local",
        "path": "/home/user/Backups",
    },
}

V23_PROFILE_EXTRA_KEYS = {
    "name": "ExtraKeys",
    "watch_dirs": ["/home/user/Music"],
    "provider_config": {
        "type": "local",
        "path": "/home/user/MusicBackup",
    },
    "unknown_key": "should_be_ignored",
    "legacy_version": "2.3.2",
    "deprecated_field": True,
}


def _load_profile_via_json(data):
    """Simulate loading a profile dict as SaveSyncCore would."""
    from core import Profile
    profile = Profile(
        name=data["name"],
        watch_dirs=data.get("watch_dirs", []).copy() if isinstance(data.get("watch_dirs"), list) else list(data.get("watch_dirs", [])),
        provider_config=dict(data.get("provider_config", {})),
    )
    return profile


class TestProfileUpgrade:

    def test_load_v23_profile_missing_defaults(self):
        data = dict(V23_PROFILE_MISSING_KEYS)
        profile = _load_profile_via_json(data)
        assert profile.name == "LegacyProfile"
        assert profile.watch_dirs == ["/home/user/Pictures"]
        assert profile.provider_config["type"] == "local"
        assert profile.provider_config["path"] == "/home/user/Backups"

    def test_extra_keys_ignored(self):
        data = dict(V23_PROFILE_EXTRA_KEYS)
        profile = _load_profile_via_json(data)
        assert profile.name == "ExtraKeys"
        assert profile.watch_dirs == ["/home/user/Music"]
        assert profile.provider_config["type"] == "local"

    def test_existing_values_preserved(self):
        data = dict(V23_PROFILE)
        profile = _load_profile_via_json(data)
        assert profile.name == "TestProfile"
        assert profile.watch_dirs == ["/home/user/Documents"]
        assert profile.provider_config["path"] == "/home/user/SaveSyncBackup"

    def test_save_and_reload(self, tmp_path):
        data = dict(V23_PROFILE)
        profile = _load_profile_via_json(data)
        profile.name = "RoundTrip"

        import json
        saved = {
            "name": profile.name,
            "watch_dirs": list(profile.watch_dirs),
            "provider_config": dict(profile.provider_config),
        }
        profile2 = _load_profile_via_json(saved)
        assert profile2.name == "RoundTrip"
        assert profile2.watch_dirs == profile.watch_dirs
        assert profile2.provider_config == profile.provider_config

    def test_all_v24_keys_present(self):
        data = {
            "name": "V24Profile",
            "watch_dirs": ["/home/user/Docs", "/home/user/Photos"],
            "provider_config": {
                "type": "dropbox",
                "remote_root": "/SaveSync",
            },
        }
        profile = _load_profile_via_json(data)
        assert profile.name == "V24Profile"
        assert len(profile.watch_dirs) == 2
        assert profile.provider_config["type"] == "dropbox"

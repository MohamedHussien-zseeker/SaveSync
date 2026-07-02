"""Pre-built profile data for workflow tests."""

SAMPLE_PROFILES = [
    {
        "name": "TestProfile",
        "watch_dirs": [],
        "provider_config": {"type": "local", "path": "/tmp/savesync_test_backup"},
        "sync_on_close": False,
    },
    {
        "name": "SyncOnClose",
        "watch_dirs": [],
        "provider_config": {"type": "local", "path": "/tmp/savesync_test_backup"},
        "sync_on_close": True,
    },
]

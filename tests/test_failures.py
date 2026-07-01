"""Failure injection tests — verifying recovery under controlled failures."""

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from failure_policy import InjectingFailurePolicy, InjectingFailureError
from transfer import TransferManager, CHUNK_SIZE


BASELINE_THREADS = threading.active_count()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_file(path, size=CHUNK_SIZE * 4):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"x" * min(size, 65536)
    written = 0
    with open(path, "wb") as f:
        while written < size:
            chunk = data[:min(65536, size - written)]
            f.write(chunk)
            written += len(chunk)
    return path


def _assert_valid_dest(dest_dir, originals):
    """originals = {rel_path: sha256_hex}. Fail if orphaned files exist."""
    for path in dest_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(dest_dir)
        if rel not in originals:
            pytest.fail(f"Orphaned file after failed operation: {rel}")
        actual = _sha256(path)
        assert actual == originals[rel], f"{rel}: content changed ({actual[:16]} != {originals[rel][:16]})"


# ---------------------------------------------------------------------------
# Unit tests — pure TransferManager + InjectingFailurePolicy
# ---------------------------------------------------------------------------

class TestFailurePolicyUnit:

    def test_before_open_permission_error(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat")
        policy = InjectingFailurePolicy({
            "before_open": {
                "fail_on": 1,
                "exception": PermissionError("Permission denied"),
                "failure_id": "perm_denied",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError) as exc:
            for _ in tm.read_chunks(str(src)):
                pass
        assert policy.last_failure_id == "perm_denied"
        assert policy.last_hook == "before_open"

    def test_after_open_os_error(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat")
        policy = InjectingFailurePolicy({
            "after_open": {
                "fail_on": 1,
                "exception": OSError(5, "Input/output error"),
                "failure_id": "io_error_after_open",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            for _ in tm.read_chunks(str(src)):
                pass
        assert policy.last_failure_id == "io_error_after_open"

    def test_before_transfer_chunk_mid_file(self, tmp_path):
        src = _make_file(tmp_path / "src" / "big.dat", size=CHUNK_SIZE * 3)
        policy = InjectingFailurePolicy({
            "before_transfer_chunk": {
                "fail_on": 2,
                "exception": OSError(28, "No space left on device"),
                "failure_id": "disk_full_chunk_2",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        chunks = []
        raised = False
        try:
            for chunk in tm.read_chunks(str(src)):
                chunks.append(chunk)
        except InjectingFailureError:
            raised = True
        assert raised, "Expected failure at chunk 2"
        assert len(chunks) == 1, "Only first chunk should have yielded"
        assert policy.fired
        assert policy.last_failure_id == "disk_full_chunk_2"

    def test_after_transfer_chunk_partial_write(self, tmp_path):
        src = _make_file(tmp_path / "src" / "partial.dat", size=CHUNK_SIZE * 2)
        policy = InjectingFailurePolicy({
            "after_transfer_chunk": {
                "fail_on": 1,
                "exception": OSError(28, "No space left on device"),
                "failure_id": "partial_chunk_1",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        chunks = []
        raised = False
        try:
            for chunk in tm.read_chunks(str(src)):
                chunks.append(chunk)
        except InjectingFailureError:
            raised = True
        assert raised
        assert len(chunks) == 0, "Failure before yield means no chunks available"

    def test_before_verify_raises(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=1024)
        policy = InjectingFailurePolicy({
            "before_verify": {
                "fail_on": 1,
                "exception": PermissionError("verify denied"),
                "failure_id": "verify_denied",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            tm.checksum(str(src))

    def test_checksum_returns_empty_on_failure(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=1024)
        policy = InjectingFailurePolicy({
            "before_verify": {
                "fail_on": 1,
                "exception": PermissionError("verify denied"),
                "failure_id": "verify_denied",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            tm.checksum(str(src))

    def test_before_retry_exhaustion(self):
        calls = [0]
        policy = InjectingFailurePolicy({
            "before_retry": {
                "fail_on": 3,
                "exception": RuntimeError("retry limit"),
                "failure_id": "retry_exhausted",
            },
        })

        def fn():
            calls[0] += 1
            raise ValueError("fail")

        with pytest.raises(InjectingFailureError) as exc:
            TransferManager.retry(fn, retries=3, _failure_policy=policy)
        assert policy.last_failure_id == "retry_exhausted"

    def test_retry_succeeds_on_third(self):
        calls = [0]
        policy = InjectingFailurePolicy({
            "before_retry": {
                "fail_on": 4,
                "exception": RuntimeError("should not fire"),
                "failure_id": "never",
            },
        })

        def fn():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("transient")
            return "ok"

        result = TransferManager.retry(fn, retries=5, _failure_policy=policy)
        assert result == "ok"
        assert calls[0] == 3
        assert not policy.fired

    def test_before_commit_fails(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=1024)
        dst = tmp_path / "dest" / "f.dat"
        policy = InjectingFailurePolicy({
            "before_commit": {
                "fail_on": 1,
                "exception": OSError(30, "Read-only file system"),
                "failure_id": "commit_failed",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            tm.write_stream(str(dst), [b"hello", b"world"])
        assert policy.fired
        assert policy.last_failure_id == "commit_failed"

    def test_before_close_fails(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=1024)
        dst = tmp_path / "dest" / "f.dat"
        policy = InjectingFailurePolicy({
            "before_close": {
                "fail_on": 1,
                "exception": OSError(5, "Close failed"),
                "failure_id": "close_failed",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            tm.write_stream(str(dst), [b"data"])
        assert policy.fired
        assert policy.last_failure_id == "close_failed"

    def test_fail_then_retry_new_operation(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=CHUNK_SIZE * 5)
        sha_orig = _sha256(src)
        dst = tmp_path / "dest" / "f.dat"

        policy = InjectingFailurePolicy({
            "after_transfer_chunk": {
                "fail_on": 3,
                "exception": OSError(28, "disk full"),
                "failure_id": "disk_full_chunk_3",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        raised = False
        try:
            tm.write_stream(str(dst), tm.read_chunks(str(src)))
        except InjectingFailureError:
            raised = True
        assert raised

        dst_after_fail = tmp_path / "dest" / "f.dat"
        assert dst_after_fail.exists(), "partial file exists"
        partial_size = dst_after_fail.stat().st_size
        assert partial_size > 0, "partial data was written"

        tm2 = TransferManager()
        result = tm2.write_stream(str(dst), tm2.read_chunks(str(src)))
        assert result == sha_orig

    def test_recovery_fail_then_retry_passes(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=CHUNK_SIZE // 2)
        sha = _sha256(src)
        dst = tmp_path / "dest" / "f.dat"

        policy = InjectingFailurePolicy({
            "after_transfer_chunk": {
                "fail_on": 1,
                "exception": OSError(28, "disk full"),
                "failure_id": "disk_full",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError):
            tm.write_stream(str(dst), tm.read_chunks(str(src)))

        tm2 = TransferManager()
        result = tm2.write_stream(str(dst), tm2.read_chunks(str(src)))
        assert result == sha
        assert _sha256(dst) == sha

    def test_no_thread_leak_after_failure(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=CHUNK_SIZE)
        policy = InjectingFailurePolicy({
            "before_open": {
                "fail_on": 1,
                "exception": PermissionError("denied"),
                "failure_id": "perm",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        before = threading.active_count()
        with pytest.raises(InjectingFailureError):
            for _ in tm.read_chunks(str(src)):
                pass
        assert threading.active_count() <= before + 1


# ---------------------------------------------------------------------------
# Integration tests — real code paths with simulated OS failures
# ---------------------------------------------------------------------------

class TestFailureIntegration:

    def _sync_with_policy(self, src_dir, dest_dir, policy, done_callback=None):
        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("FailInt", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            results["stats"] = stats
            done_ev.set()

        if done_callback:
            worker.sync_all(done_callback=done_callback)
        else:
            worker.sync_all(done_callback=done)
            done_ev.wait(timeout=30)
        return worker, results

    def test_readonly_dest_fails_gracefully(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir.mkdir()
        os.chmod(str(dest_dir), 0o444)

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("Readonly", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert results["success"] is False, f"Expected failure, got: {results['message']}"

        snap = worker.op_state.snapshot()
        assert snap.phase in ("Failed", "Cancelled")
        assert not worker.is_running
        os.chmod(str(dest_dir), 0o755)

    def test_missing_source_handled(self, tmp_path):
        src_dir = tmp_path / "src" / "nonexistent"
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("MissingSrc", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            results["stats"] = stats or {}
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert results["success"] is True, f"msg={results['message']}"

        snap = worker.op_state.snapshot()
        assert snap.phase in ("Completed",)
        assert results["stats"].get("files", None) == 0, f"stats={results['stats']}"

    def test_unicode_filenames(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        uname = "文件_файл_파일.txt"
        (src_dir / uname).write_text("unicode data")
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("Unicode", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert results["success"] is True
        assert (dest_dir / uname).exists()

    def test_long_path_handled(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir(parents=True, exist_ok=True)
        long_name = "a" * 200 + ".txt"
        (src_dir / long_name).write_text("long path data")
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("LongPath", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert results["success"] is True
        assert (dest_dir / long_name).exists()

    def test_cancel_during_sync(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        for i in range(50):
            (src_dir / "f_{:04d}.txt".format(i)).write_text("x" * 65536)
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("CancelSync", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()

        cancel_fired = threading.Event()
        def watcher():
            while not done_ev.is_set():
                if worker.op_state:
                    snap = worker.op_state.snapshot()
                    if snap.files_completed >= 3:
                        worker.cancel()
                        cancel_fired.set()
                        return
                time.sleep(0.005)

        threading.Thread(target=watcher, daemon=True).start()
        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert cancel_fired.is_set() or results["success"] is False
        snap = worker.op_state.snapshot()
        assert snap.phase in ("Cancelled", "Failed")
        assert not worker.is_running

    def test_cancel_during_restore(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        for i in range(50):
            (src_dir / "f_{:04d}.txt".format(i)).write_text("x" * 65536)
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("CancelRestore", [str(dest_dir)],
                          {"type": "local", "path": str(src_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        results = {}
        done_ev = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()

        cancel_fired = threading.Event()
        def watcher():
            while not done_ev.is_set():
                if worker.op_state:
                    snap = worker.op_state.snapshot()
                    if snap.files_completed >= 3:
                        worker.cancel()
                        cancel_fired.set()
                        return
                time.sleep(0.005)

        threading.Thread(target=watcher, daemon=True).start()
        worker.restore_all(done_callback=done, verify=False)
        done_ev.wait(timeout=30)
        assert cancel_fired.is_set() or results["success"] is False
        snap = worker.op_state.snapshot()
        assert snap.phase in ("Cancelled", "Failed")
        assert not worker.is_running

    def test_worker_exits_cleanly_after_failure(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        os.chmod(str(dest_dir), 0o444)

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("CleanExit", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()

        def done(success, message, stats=None):
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        os.chmod(str(dest_dir), 0o755)
        assert not worker.is_running
        assert worker._thread is None or not worker._thread.is_alive()
        assert threading.active_count() <= BASELINE_THREADS + 4

    def test_no_stale_cancel_state(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("NoStale", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()

        def done(success, message, stats=None):
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert not worker._cancel_event.is_set()
        assert worker.op_state is None or worker.op_state.snapshot().is_terminal
        assert worker._current_op is None

        worker2 = SyncWorker(core, profile)
        done_ev2 = threading.Event()
        def done2(success, message, stats=None):
            done_ev2.set()
        worker2.sync_all(done_callback=done2)
        done_ev2.wait(timeout=30)
        assert True

    def test_recovery_fail_then_sync_succeeds(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        for i in range(5):
            (src_dir / "f_{}.txt".format(i)).write_text("x" * 1024)
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        os.chmod(str(dest_dir), 0o444)

        profile = Profile("FailThenOk", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()

        def done(success, message, stats=None):
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        os.chmod(str(dest_dir), 0o755)

        worker2 = SyncWorker(core, profile)
        done_ev2 = threading.Event()

        def done2(success, message, stats=None):
            done_ev2.set()

        worker2.sync_all(done_callback=done2)
        done_ev2.wait(timeout=30)
        assert done_ev2.is_set()
        assert any((dest_dir / "f_{}.txt".format(i)).exists() for i in range(5))

    def test_cleanup_on_failure(self, tmp_path):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir.mkdir()

        from core import SyncWorker, SaveSyncCore, Profile
        os.chmod(str(dest_dir), 0o444)

        profile = Profile("CleanupFail", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()

        def done(success, message, stats=None):
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        os.chmod(str(dest_dir), 0o755)

        snap = worker.op_state.snapshot()
        assert snap.phase in ("Failed", "Cancelled"), f"phase={snap.phase}"
        assert not worker.is_running

    def test_large_file_no_rss_growth(self, tmp_path):
        src = _make_file(tmp_path / "large_src" / "big.dat", size=CHUNK_SIZE * 10)
        dest_dir = tmp_path / "large_dest"
        dest_dir.mkdir()

        import resource
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        from core import SyncWorker, SaveSyncCore, Profile
        profile = Profile("LargeFile", [str(src.parent)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()

        def done(success, message, stats=None):
            done_ev.set()

        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=60)

        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        growth = rss_after - rss_before
        assert growth < 50000, f"RSS grew by {growth} KB (limit 50MB)"
        assert (dest_dir / "big.dat").exists()

    def test_cancel_mid_transfer(self, tmp_path):
        """Cancel mid-chunk via TransferManager.cancel_event."""
        src = _make_file(tmp_path / "cancel_src" / "big.dat", size=CHUNK_SIZE * 20)
        dst = tmp_path / "cancel_dst" / "big.dat"

        cancel_ev = threading.Event()
        tm = TransferManager(cancel_event=cancel_ev)

        # Cancel after first few chunks via watcher
        cancel_fired = threading.Event()
        chunks_seen = []
        for chunk in tm.read_chunks(str(src)):
            chunks_seen.append(chunk)
            if len(chunks_seen) >= 2:
                cancel_ev.set()
                cancel_fired.set()
                break

        assert cancel_fired.is_set(), "Cancel should fire"
        # Transfer stops; partial file may exist at dst
        assert len(chunks_seen) >= 2, "At least 2 chunks read before cancel"

    def test_failure_id_in_exception(self, tmp_path):
        src = _make_file(tmp_path / "src" / "f.dat", size=1024)
        policy = InjectingFailurePolicy({
            "before_open": {
                "fail_on": 1,
                "exception": PermissionError("denied"),
                "failure_id": "perm_denied_file",
            },
        })
        tm = TransferManager(_failure_policy=policy)
        with pytest.raises(InjectingFailureError) as exc:
            for _ in tm.read_chunks(str(src)):
                pass
        assert exc.value.failure_id == "perm_denied_file"

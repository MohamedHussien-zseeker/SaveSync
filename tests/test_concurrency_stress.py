"""Concurrency stress tests for SaveSync — proving threading model correctness."""

import os
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


BASELINE_THREADS = threading.active_count()


def _make_files(src_dir, n, size):
    src_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (src_dir / f"f_{i}.txt").write_text("x" * size)


def _check_invariants(worker, state_before, state_after, baseline, label=""):
    assert state_after is not state_before, \
        f"{label}: op_state was not replaced (same object)"
    assert state_after is not None, f"{label}: op_state is None after operation"
    assert threading.active_count() <= baseline + 4, \
        f"{label}: thread leak ({threading.active_count()} vs {baseline})"
    snap = state_after.snapshot()
    assert snap.is_terminal or snap.phase == "Failed", \
        f"{label}: non-terminal phase {snap.phase}"
    assert snap.bytes_transferred <= snap.bytes_total or snap.bytes_total == 0, \
        f"{label}: bytes exceeded total"
    assert snap.files_completed <= snap.files_total or snap.files_total == 0, \
        f"{label}: files exceeded total"


class TestM5ConcurrencyStress:

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _run_one_cycle(self, seed, n_files, cancel_at, op="sync"):
        from core import SyncWorker, SaveSyncCore, Profile

        rng = random.Random(seed)
        src_dir = self.tmp_path / f"cycle_{seed}_src"
        dest_dir = self.tmp_path / f"cycle_{seed}_dest"
        dest_dir.mkdir(parents=True, exist_ok=True)

        size = rng.randint(1024, 4096) if n_files <= 50 else 1024
        _make_files(src_dir, n_files, size)

        profile = Profile(f"Stress{seed}", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)

        state_before = worker.op_state
        results = {}
        done_ev = threading.Event()
        cancelled = threading.Event()

        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            results["stats"] = stats
            done_ev.set()

        def watcher():
            while True:
                if done_ev.is_set():
                    return
                if worker.op_state:
                    snap = worker.op_state.snapshot()
                    if snap.files_completed >= cancel_at:
                        cancelled.set()
                        worker.cancel()
                        return
                time.sleep(0.005)

        threading.Thread(target=watcher, daemon=True).start()
        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)

        state_after = worker.op_state
        _check_invariants(worker, state_before, state_after,
                          BASELINE_THREADS, f"cycle {seed} (sync)")
        snap = worker.op_state.snapshot()
        if cancelled.is_set():
            assert results.get("success") is False, \
                f"cycle {seed}: expected cancel got success"
            assert snap.phase in ("Cancelled", "Failed"), \
                f"cycle {seed}: phase={snap.phase}"
        else:
            assert snap.phase in ("Completed", "Cancelled", "Failed"), \
                f"cycle {seed}: phase={snap.phase}"

        # Restore cycle
        for d in dest_dir.iterdir():
            d.unlink()
        dest_dir.rmdir()
        restore_dir = self.tmp_path / f"cycle_{seed}_restore"
        restore_dir.mkdir(parents=True, exist_ok=True)

        profile2 = Profile(f"Restore{seed}", [str(restore_dir)],
                           {"type": "local", "path": str(src_dir)})
        worker2 = SyncWorker(core, profile2)

        results2 = {}
        done_ev2 = threading.Event()
        cancelled2 = threading.Event()

        def done2(success, message, stats=None):
            results2["success"] = success
            results2["message"] = message
            done_ev2.set()

        def watcher2():
            while True:
                if done_ev2.is_set():
                    return
                if worker2.op_state:
                    snap = worker2.op_state.snapshot()
                    if snap.files_completed >= max(1, cancel_at // 4):
                        cancelled2.set()
                        worker2.cancel()
                        return
                time.sleep(0.005)

        state_before2 = worker2.op_state
        threading.Thread(target=watcher2, daemon=True).start()
        worker2.restore_all(done_callback=done2, verify=False)
        done_ev2.wait(timeout=30)

        state_after2 = worker2.op_state
        _check_invariants(worker2, state_before2, state_after2,
                          BASELINE_THREADS, f"cycle {seed} (restore)")
        snap2 = worker2.op_state.snapshot()
        if cancelled2.is_set():
            assert results2.get("success") is False, \
                f"cycle {seed} restore: expected cancel got success"
            assert snap2.phase in ("Cancelled", "Failed"), \
                f"cycle {seed} restore: phase={snap2.phase}"
        else:
            assert snap2.phase in ("Completed", "Cancelled", "Failed"), \
                f"cycle {seed} restore: phase={snap2.phase}"

    def test_deterministic_cycles(self):
        """50 deterministic cycles: sync + cancel + restore + cancel."""
        for i in range(50):
            try:
                self._run_one_cycle(i, n_files=150, cancel_at=15)
            except AssertionError:
                print(f"\n[FAIL] deterministic cycle {i}: seed={i}, "
                      f"n_files=150, cancel_at=15")
                raise

    def test_randomized_cycles(self):
        """50 randomized cycles with varying files, sizes, cancel points."""
        master_seed = random.randrange(2**32)
        rng = random.Random(master_seed)
        timings = []
        for i in range(50):
            n_files = rng.randint(100, 300)
            cancel_at = rng.randint(20, max(20, n_files // 3))
            seed = rng.randrange(2**16)
            t0 = time.perf_counter()
            try:
                self._run_one_cycle(seed, n_files, cancel_at)
            except AssertionError:
                print(f"\n[FAIL] cycle {i}: seed={seed}, n_files={n_files}, "
                      f"cancel_at={cancel_at}, master_seed={master_seed}")
                raise
            elapsed = time.perf_counter() - t0
            timings.append(elapsed)

        avg = sum(timings) / len(timings)
        print(f"\n[timing] avg={avg:.3f}s  min={min(timings):.3f}s  "
              f"max={max(timings):.3f}s  seed={master_seed}")

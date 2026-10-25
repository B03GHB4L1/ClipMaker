import json
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from packaging.analysis_server import _wait_for_kqueue_exit, wait_for_process_exit, watch_process_owner
from packaging.clipmaker_api_server import JobManager
from packaging.smoke_test import backend, request

ROOT = Path(__file__).resolve().parents[1]


class ShutdownTests(unittest.TestCase):
    def kqueue_mocks(self, queue):
        import select
        return patch.multiple(select, create=True, kqueue=Mock(return_value=queue), kevent=Mock(),
                              KQ_FILTER_PROC=-5, KQ_EV_ADD=1, KQ_EV_ONESHOT=16,
                              KQ_NOTE_EXIT=0x80000000, KQ_EV_ERROR=0x4000)

    def test_macos_adapter_uses_exit_notification_and_closes_queue(self):
        import select
        queue = Mock()
        queue.control.return_value = [Mock(flags=0, fflags=0x80000000)]
        with self.kqueue_mocks(queue):
            self.assertTrue(_wait_for_kqueue_exit(44, 2.5))
            select.kevent.assert_called_once_with(44, filter=-5, flags=17, fflags=0x80000000)
            queue.control.assert_called_once_with([select.kevent.return_value], 1, 2.5)
        queue.close.assert_called_once()

    def test_macos_adapter_timeout_does_not_report_exit(self):
        queue = Mock()
        queue.control.return_value = []
        with self.kqueue_mocks(queue):
            self.assertFalse(_wait_for_kqueue_exit(44, 0))
        queue.close.assert_called_once()

    def test_macos_adapter_handles_already_gone_process_but_preserves_real_errors(self):
        for response in (ProcessLookupError(errno.ESRCH, "gone"),
                         [Mock(flags=0x4000, data=errno.ESRCH)]):
            queue = Mock()
            if isinstance(response, Exception):
                queue.control.side_effect = response
            else:
                queue.control.return_value = response
            with self.kqueue_mocks(queue):
                self.assertTrue(_wait_for_kqueue_exit(44, 1))
            queue.close.assert_called_once()
        queue = Mock()
        queue.control.return_value = [Mock(flags=0x4000, data=errno.EACCES)]
        with self.kqueue_mocks(queue), self.assertRaises(PermissionError):
            _wait_for_kqueue_exit(44, 1)
        queue.close.assert_called_once()

    @unittest.skipUnless(sys.platform == "darwin", "macOS kqueue regression")
    def test_macos_process_exit_is_detected_before_child_is_reaped(self):
        owner = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
        try:
            self.assertTrue(wait_for_process_exit(owner.pid, timeout=5))
        finally:
            self.assertEqual(owner.wait(timeout=5), 7)

    def test_owner_watcher_does_not_notify_on_non_exit(self):
        callback = Mock()
        with patch("packaging.analysis_server.wait_for_process_exit", return_value=False):
            monitor = watch_process_owner(44, callback)
            monitor.join(timeout=2)
            self.assertFalse(monitor.is_alive())
        callback.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "pidfd_open"), "Linux pidfd regression")
    def test_linux_process_exit_is_detected_before_zombie_is_reaped(self):
        owner = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            self.assertTrue(wait_for_process_exit(owner.pid, timeout=5))
        finally:
            owner.wait(timeout=5)

    def test_process_wait_is_bounded_and_validates_inputs(self):
        self.assertFalse(wait_for_process_exit(os.getpid(), timeout=.01))
        for pid, timeout in ((0, 0), (-1, 0), (os.getpid(), -1)):
            with self.assertRaises(ValueError):
                wait_for_process_exit(pid, timeout)

    def test_owner_watcher_notifies_when_real_owner_dies(self):
        exited = threading.Event()
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            monitor = watch_process_owner(owner.pid, exited.set)
            self.assertFalse(exited.wait(.05))
            owner.terminate()
            owner.wait(timeout=5)
            self.assertTrue(exited.wait(5))
            monitor.join(timeout=1)
            self.assertFalse(monitor.is_alive())
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=5)

    def test_closing_engine_cancels_and_joins_export_workers(self):
        manager = JobManager()
        started = threading.Event()
        finished = threading.Event()
        def execute(job, config, cancellation):
            started.set()
            cancellation.wait(5)
            finished.set()
        config = {"dry_run": True, "output_dir": ".", "output_filename": "unused.mp4"}
        with patch.object(manager, "_execute", side_effect=execute):
            manager.start(config)
            self.assertTrue(started.wait(2))
            self.assertTrue(manager.close(timeout=2))
            self.assertTrue(finished.is_set())
            with self.assertRaisesRegex(ValueError, "shutting down"):
                manager.start(config)

    def test_closing_engine_has_one_bounded_deadline(self):
        manager = JobManager()
        release = threading.Event()
        worker = threading.Thread(target=release.wait)
        manager._workers["blocked"] = worker
        worker.start()
        try:
            self.assertFalse(manager.close(timeout=.01))
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertTrue(manager.close(timeout=1))

    def test_backend_exits_after_desktop_owner_dies_and_releases_working_directory(self):
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data = root / "projects"
                data.mkdir()
                working = root / "working-directory"
                working.mkdir()
                environment = {**os.environ, "VIZORPLAY_OWNER_PID": str(owner.pid)}
                with backend([sys.executable, str(ROOT / "packaging/clipmaker_api_server.py")], data,
                             env=environment, cwd=working) as base:
                    health = request(base, "/api/health")
                    self.assertEqual(health["desktop_owner_pid"], owner.pid)
                    if os.name == "nt":
                        with self.assertRaises(PermissionError):
                            working.rmdir()
                    owner.terminate()
                    owner.wait(timeout=5)
                    self.assertTrue(wait_for_process_exit(health["pid"], timeout=15), health)
                    if health["parent_pid"] != os.getpid():
                        self.assertTrue(wait_for_process_exit(health["parent_pid"], timeout=15), health)
                    working.rmdir()
                data.rename(root / "released")
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=5)

    def test_native_acceptance_does_not_ignore_a_lingering_process(self):
        from tests.native_smoke import verify_shutdown
        for answers, key in (([False], "desktop_owner_pid"), ([True, False], "pid"), ([True, True, False], "parent_pid")):
            with self.subTest(process=key), tempfile.TemporaryDirectory() as directory, \
                 patch("tests.native_smoke.wait_for_process_exit", side_effect=answers):
                with self.assertRaisesRegex(AssertionError, "still running"):
                    verify_shutdown({"pid": 22, "desktop_owner_pid": 11, "parent_pid": 33}, Path(directory), 1)
                evidence = json.loads((Path(directory) / "shutdown-1.json").read_text())
                self.assertFalse(evidence[key]["exited"])


if __name__ == "__main__":
    unittest.main()

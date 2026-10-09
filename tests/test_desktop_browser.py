import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator import desktop_browser
from issue_delivery_orchestrator.desktop_browser import (
    open_desktop_browser,
    validate_desktop_browser,
)
from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import create_state


class DesktopBrowserTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.worktree = root / "worktree"
        self.worktree.mkdir()
        subprocess.run(["git", "init"], cwd=self.worktree, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "commit",
             "--allow-empty", "-m", "init"],
            cwd=self.worktree, check=True, capture_output=True,
        )
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.worktree, check=True, capture_output=True,
            text=True,
        ).stdout.strip()
        manifest = root / "runtime.json"
        manifest.write_text(json.dumps({"urls": {"web": "http://localhost:43123/"}}))
        self.state = create_state(
            worktree=self.worktree, run_id="run-1",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="b", base="development", created_from="origin/development",
            adopted_head=self.head, identities={"linear": "l", "github": "g"},
            mode="conductor-cloud",
        )
        self.state.update(
            status="preparing_final_runtime", activeRuntimeId="runtime-1",
            runtimes=[{"runtimeId": "runtime-1", "manifestPath": str(manifest), "cleanedAt": None}],
            finalRuntimeReset={"runtimeId": "runtime-1", "verifiedCommit": self.head},
        )
        self.socket = root / "X1"
        self.opened = root / "opened.txt"
        browser = root / "fake-chrome"
        browser.write_text(f'#!/bin/sh\necho "$DISPLAY $@" > {self.opened}\nexec sleep 30\n')
        browser.chmod(0o755)
        for target, value in (("DISPLAY_SOCKET", self.socket), ("_browser_binary", lambda: str(browser))):
            patcher = patch.object(desktop_browser, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        pid = (self.state.get("desktopBrowser") or {}).get("pid")
        if pid:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def _wait_for_browser(self):
        deadline = time.monotonic() + 15
        while not self.opened.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        return self.opened.read_text()

    def test_waits_for_the_conductor_desktop_before_opening_the_runtime_page(self):
        result = self._open_with_child_socket()
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["url"], "http://localhost:43123/orders/1")
        self.assertFalse(self.opened.exists())
        self.socket.touch()
        opened = self._wait_for_browser()
        self.assertTrue(opened.startswith(":1 "))
        self.assertIn("--user-data-dir=", opened)
        self.assertIn("http://localhost:43123/orders/1", opened)
        record = validate_desktop_browser(self.state, runtime_id="runtime-1", commit=self.head)
        self.assertEqual(record["pid"], result["pid"])

    def test_handoff_requires_a_live_window_for_the_final_runtime(self):
        with self.assertRaisesRegex(RunBlocked, "desktop-browser first"):
            validate_desktop_browser(self.state, runtime_id="runtime-1", commit=self.head)
        self.socket.touch()
        result = self._open_with_child_socket()
        self.assertEqual(result["status"], "OPENED")
        self._wait_for_browser()
        with self.assertRaisesRegex(RunBlocked, "desktop-browser first"):
            validate_desktop_browser(self.state, runtime_id="runtime-2", commit=self.head)
        os.kill(result["pid"], 9)
        os.waitpid(result["pid"], 0)
        with self.assertRaisesRegex(RunBlocked, "no longer running"):
            validate_desktop_browser(self.state, runtime_id="runtime-1", commit=self.head)

    def test_rejects_unknown_services_and_relative_paths(self):
        with self.assertRaisesRegex(RunBlocked, "start with"):
            open_desktop_browser(self.state, "web", "orders")
        with self.assertRaisesRegex(RunBlocked, "not found"):
            open_desktop_browser(self.state, "api", "/")

    def _open_with_child_socket(self):
        # The detached waiter imports the module afresh, so point it at the test socket.
        original = desktop_browser.subprocess.Popen

        def popen(command, **kwargs):
            if command[1:3] != ["-m", desktop_browser.__name__]:
                return original(command, **kwargs)
            code = (
                "import sys; from pathlib import Path; "
                "import issue_delivery_orchestrator.desktop_browser as d; "
                f"d.DISPLAY_SOCKET = Path({str(self.socket)!r}); "
                "d._wait_and_exec(*sys.argv[1:4])"
            )
            return original([command[0], "-c", code, *command[3:]], **kwargs)

        with patch.object(desktop_browser.subprocess, "Popen", popen):
            return open_desktop_browser(self.state, "web", "/orders/1")

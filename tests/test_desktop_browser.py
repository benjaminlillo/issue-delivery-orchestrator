import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator import desktop_browser
from issue_delivery_orchestrator.desktop_browser import (
    open_desktop_browser,
    prepare_desktop_replay,
)
from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import create_state, run_root

FAKE_CHROME = """#!{python}
import http.server, os, sys
port = next(a.split("=")[1] for a in sys.argv if a.startswith("--remote-debugging-port="))
with open({log!r}, "a") as log:
    log.write(os.environ.get("DISPLAY", "-") + " " + " ".join(sys.argv[1:]) + "\\n")
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", int(port)), Handler).serve_forever()
"""


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
        self.replay = run_root(self.worktree, "run-1") / "desktop-browser" / "replay.cjs"
        self.replay.parent.mkdir(parents=True, exist_ok=True)
        self.replay.write_text("// reach the starting point\n")
        self.socket = root / "X1"
        self.chrome_log = root / "chrome.log"
        self.node_log = root / "node.log"
        self.node_exit = root / "node-exit"
        self.node_exit.write_text("0")
        chrome = root / "fake-chrome"
        chrome.write_text(FAKE_CHROME.format(python=sys.executable, log=str(self.chrome_log)))
        node = root / "fake-node"
        node.write_text(f'#!/bin/sh\necho "$@" >> {self.node_log}\nexit $(cat {self.node_exit})\n')
        for script in (chrome, node):
            script.chmod(0o755)
        for target, value in (
            ("DISPLAY_SOCKET", self.socket),
            ("_browser_binary", lambda: str(chrome)),
            ("_node_binary", lambda: str(node)),
        ):
            patcher = patch.object(desktop_browser, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        pid = (self.state.get("desktopBrowser") or {}).get("pid")
        if pid:
            desktop_browser._stop_group(pid)

    def _prepare(self):
        return prepare_desktop_replay(self.state, "web", "/orders/1", self.replay)

    def test_rehearses_headlessly_without_the_desktop(self):
        prepared = self._prepare()
        self.assertEqual(prepared["rehearsal"]["status"], "REACHED")
        self.assertEqual(prepared["url"], "http://localhost:43123/orders/1")
        rehearsal = self.chrome_log.read_text()
        self.assertTrue(rehearsal.startswith("- ") and "--headless=new" in rehearsal)
        self.assertFalse(self.socket.exists())

    def test_blocks_preparation_when_the_replay_does_not_reach_the_starting_point(self):
        self.node_exit.write_text("1")
        with self.assertRaisesRegex(RunBlocked, "did not reach the starting point"):
            self._prepare()
        self.assertNotIn("desktopReplay", self.state)

    def test_opens_on_request_after_the_handoff_and_replays_in_the_visible_window(self):
        self._prepare()
        with self.assertRaisesRegex(RunBlocked, "after the final runtime handoff"):
            open_desktop_browser(self.state)
        self.state["status"] = "completed_preserved"
        with self.assertRaisesRegex(RunBlocked, "desktop is not open"):
            open_desktop_browser(self.state)
        self.socket.touch()
        opened = open_desktop_browser(self.state)
        self.assertEqual(opened["status"], "REACHED")
        desktop = self.chrome_log.read_text().splitlines()[-1]
        self.assertTrue(desktop.startswith(":1 "))
        self.assertIn("--start-maximized", desktop)
        self.assertIn(
            f"{opened['cdpUrl']} http://localhost:43123/orders/1",
            self.node_log.read_text().splitlines()[-1],
        )
        self.node_exit.write_text("1")
        reopened = open_desktop_browser(self.state)
        self.assertEqual(reopened["status"], "OPENED_WITHOUT_STARTING_POINT")
        self.assertFalse(desktop_browser._alive(opened["pid"]))

    def test_requires_a_replay_prepared_for_the_handed_off_runtime(self):
        self.state["status"] = "completed_preserved"
        self.socket.touch()
        with self.assertRaisesRegex(RunBlocked, "prepare it first"):
            open_desktop_browser(self.state)

    def test_rejects_unknown_services_relative_paths_and_outside_scripts(self):
        with self.assertRaisesRegex(RunBlocked, "start with"):
            prepare_desktop_replay(self.state, "web", "orders", self.replay)
        with self.assertRaisesRegex(RunBlocked, "not found"):
            prepare_desktop_replay(self.state, "api", "/", self.replay)
        outside = self.worktree / "replay.cjs"
        outside.write_text("")
        with self.assertRaisesRegex(RunBlocked, "inside the run directory"):
            prepare_desktop_replay(self.state, "web", "/", outside)

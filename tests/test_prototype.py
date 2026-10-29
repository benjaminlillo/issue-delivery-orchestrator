import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from issue_delivery_orchestrator import desktop_browser
from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.prototype import approve_prototype, open_prototype, prototype_root
from issue_delivery_orchestrator.state import create_state


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.worktree = root / "worktree"
        self.worktree.mkdir()
        self.state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "T"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={}, mode="conductor-cloud",
        )
        self.state["currentPhase"] = "grill"
        self.page = prototype_root(self.state) / "index.html"
        self.page.parent.mkdir(parents=True, exist_ok=True)
        self.page.write_text("<html></html>")
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
        pid = (self.state.get("prototype") or {}).get("pid")
        if pid:
            desktop_browser._stop_group(pid)

    def test_opens_the_prototype_on_the_desktop_only_when_it_is_open(self):
        with self.assertRaisesRegex(RunBlocked, "desktop is not open"):
            open_prototype(self.state, self.page)
        self.socket.touch()
        first = open_prototype(self.state, self.page)
        self.assertEqual(first["status"], "IN_REVIEW")
        self.assertTrue(self.opened.read_text().startswith(":1 "))
        self.assertIn(self.page.resolve().as_uri(), self.opened.read_text())
        second = open_prototype(self.state, self.page)
        self.assertFalse(desktop_browser._alive(first["pid"]))
        self.assertNotEqual(first["pid"], second["pid"])
        with self.assertRaisesRegex(RunBlocked, "inside"):
            open_prototype(self.state, self.worktree / "outside.html")

    def test_publishes_the_approved_screenshots_to_linear(self):
        approved = prototype_root(self.state) / "approved" / "form.png"
        approved.parent.mkdir(parents=True)
        approved.write_bytes(b"\x89PNG")
        manifest = prototype_root(self.state) / "approved" / "manifest.json"
        manifest.write_text(json.dumps({"screenshots": [
            {"title": "Formulario con error", "path": str(approved.relative_to(self.worktree))},
        ]}))
        linear = Mock()
        linear.issue.return_value = SimpleNamespace(id="issue-id", description="## Problema\n\nTexto")
        linear.upload_file.return_value = "https://uploads.linear.app/form.png"

        result = approve_prototype(self.state, linear=linear, manifest=manifest)

        self.assertEqual(result["status"], "APPROVED")
        description = linear.update_description.call_args.args[1]
        self.assertIn("## Prototipo aprobado", description)
        self.assertIn("![Formulario con error](https://uploads.linear.app/form.png)", description)
        self.assertIn("## Problema", description)
        linear.post_comment.assert_called_once()

    def test_records_a_skipped_prototype_only_during_grill(self):
        self.assertEqual(
            approve_prototype(self.state, linear=None, skip_reason="El usuario pidió sin prototipo")["status"],
            "SKIPPED",
        )
        self.state["currentPhase"] = "implement"
        with self.assertRaisesRegex(RunBlocked, "during Grill"):
            approve_prototype(self.state, linear=None, skip_reason="Tarde")

    def test_rejects_screenshots_outside_the_approved_directory(self):
        stray = prototype_root(self.state) / "draft.png"
        stray.write_bytes(b"\x89PNG")
        manifest = prototype_root(self.state) / "manifest.json"
        manifest.write_text(json.dumps({"screenshots": [
            {"title": "Borrador", "path": str(stray.relative_to(self.worktree))},
        ]}))
        with self.assertRaisesRegex(RunBlocked, "prototype/approved"):
            approve_prototype(self.state, linear=Mock(), manifest=manifest)

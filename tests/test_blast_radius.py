import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from issue_delivery_orchestrator.blast_radius import assess_blast_radius
from issue_delivery_orchestrator.config import DEFAULT_PROFILE
from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import create_state


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write(root, path, text="x\n"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


class BlastRadiusTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.worktree = self.root / "repo"
        self.worktree.mkdir()
        git(self.worktree, "init", "-q", "-b", "test")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "Test")
        write(self.worktree, ".gitignore", ".local-runtime/\n")
        write(self.worktree, "apps/shops-app/src/a.ts", 'import "@turboshop/shared-utils";\n')
        write(self.worktree, "apps/shops-backend/src/b.ts", 'import "@turboshop/shared-utils";\n')
        write(self.worktree, "libs/shared-utils/src/index.ts")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "initial")
        git(self.worktree, "update-ref", "refs/remotes/origin/test", "HEAD")
        git(self.worktree, "checkout", "-qb", "feature")
        self.state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "T"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={},
        )
        self.state.update(status="completed_preserved", pr={"url": "https://github.com/o/r/pull/7", "number": 7})
        self.github = Mock()
        self.github.repost_comment.return_value = "https://github.com/o/r/pull/7#issuecomment-1"
        for target, value in (
            ("issue_delivery_orchestrator.blast_radius.GitHubClient", Mock(return_value=self.github)),
            ("issue_delivery_orchestrator.blast_radius.settings", Mock(return_value=Mock(profile_path=DEFAULT_PROFILE))),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def commit(self, *paths):
        for path in paths:
            write(self.worktree, path, f"{path}\n")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "change")
        self.state["finalRuntimeHandoff"] = {"verifiedCommit": git(self.worktree, "rev-parse", "HEAD")}

    def assess(self, money=False, **extra):
        payload = {
            "checks": {
                "money": {"triggered": money, "evidence": "cambia el total del pedido" if money else "solo UI"},
                "permissions": {"triggered": False, "evidence": "no toca guards"},
                "mobileContract": {"triggered": False, "evidence": "no cambia endpoints"},
            },
            **extra,
        }
        path = self.root / "input.json"
        path.write_text(json.dumps(payload))
        return assess_blast_radius(self.state, path)

    def test_small_tested_change_in_one_app_is_low_and_posted_as_the_last_comment(self):
        self.commit("apps/shops-app/src/a.ts", "apps/shops-app/src/a.test.ts")
        result = self.assess()
        self.assertEqual(result["level"], "bajo")
        self.assertEqual(result["signals"]["units"], ["apps/shops-app"])
        number, marker, body = self.github.repost_comment.call_args.args
        self.assertEqual((number, marker), (7, "<!-- issue-delivery-blast-radius:run-1 -->"))
        self.assertIn("## Blast radius: bajo", body)
        self.assertEqual(self.state["blastRadius"]["level"], "bajo")

    def test_untested_change_across_apps_is_medium(self):
        self.commit("apps/shops-app/src/a.ts", "apps/shops-backend/src/b.ts")
        result = self.assess()
        self.assertEqual(result["level"], "medio")
        self.assertEqual(len(result["mediumReasons"]), 2)

    def test_hard_triggers_make_it_high(self):
        self.commit(
            "apps/shops-backend/src/database/migrations/1-x.ts",
            "libs/shared-utils/src/index.ts",
            "apps/shops-backend/src/b.test.ts",
        )
        result = self.assess(money=True)
        self.assertEqual(result["level"], "alto")
        self.assertEqual([item["id"] for item in result["triggers"]], ["migration", "sharedLibrary", "money"])
        self.assertIn("shops-app, shops-backend", result["triggers"][1]["evidence"])

    def test_requires_every_judged_trigger_with_evidence(self):
        self.commit("apps/shops-app/src/a.ts")
        path = self.root / "input.json"
        path.write_text(json.dumps({"checks": {"money": {"triggered": False, "evidence": "no"}}}))
        with self.assertRaisesRegex(RunBlocked, "missing=\\['permissions', 'mobileContract'\\]"):
            assess_blast_radius(self.state, path)
        self.github.repost_comment.assert_not_called()

    def test_requires_the_handed_off_code(self):
        self.commit("apps/shops-app/src/a.ts")
        self.state["finalRuntimeHandoff"] = {"verifiedCommit": "other"}
        with self.assertRaisesRegex(RunBlocked, "Code changed"):
            self.assess()

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.pr_ready import mark_pr_ready
from issue_delivery_orchestrator.state import create_state


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PrReadyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.worktree = Path(tmp.name)
        git(self.worktree, "init", "-q")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "Test")
        (self.worktree / ".gitignore").write_text(".local-runtime/\n")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "initial")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        self.state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "T"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={},
        )
        self.state.update(
            status="completed_preserved",
            pr={"url": "https://github.com/example/repo/pull/10", "number": 10},
            finalRuntimeHandoff={"status": "ready", "verifiedCommit": self.head},
        )
        self.github = Mock()
        self.pr = {
            "url": self.state["pr"]["url"], "isDraft": True, "mergeable": "MERGEABLE",
            "headRefOid": self.head, "labels": [],
        }
        self.github.readiness.side_effect = lambda _ref: dict(self.pr)
        self.github.mark_ready.side_effect = lambda _ref: self.pr.update(isDraft=False)
        self.github.add_label.side_effect = lambda _ref, label: self.pr.update(labels=[{"name": label}])
        patcher = patch(
            "issue_delivery_orchestrator.pr_ready.settings",
            return_value=Mock(ready_label="ASSIGN_REVIEWER"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def ready(self):
        return mark_pr_ready(self.state, github=self.github, sleeper=lambda _seconds: None)

    def test_marks_a_clean_pr_ready_and_adds_the_review_label(self):
        result = self.ready()
        self.github.verify_identity.assert_called_once()
        self.github.mark_ready.assert_called_once_with(self.state["pr"]["url"])
        self.github.add_label.assert_called_once_with(self.state["pr"]["url"], "ASSIGN_REVIEWER")
        self.assertEqual(result["label"], "ASSIGN_REVIEWER")
        self.assertEqual(self.state["readyForReview"]["headSha"], self.head)

    def test_blocks_on_conflicts_and_waits_while_github_computes_mergeability(self):
        self.pr["mergeable"] = "CONFLICTING"
        with self.assertRaisesRegex(RunBlocked, "conflicts"):
            self.ready()
        states = iter(["UNKNOWN", "UNKNOWN", "MERGEABLE"])
        self.github.readiness.side_effect = lambda _ref: {**self.pr, "mergeable": next(states, "MERGEABLE")}
        self.pr["mergeable"] = "MERGEABLE"
        self.ready()
        self.github.mark_ready.assert_called_once()

    def test_allows_lesson_cards_but_not_code_changed_after_the_handoff(self):
        lessons = self.worktree / "docs" / "lessons"
        lessons.mkdir(parents=True)
        (lessons / "card.md").write_text("# Lección\n")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "docs(lessons): add card")
        self.pr["headRefOid"] = git(self.worktree, "rev-parse", "HEAD")
        self.ready()
        (self.worktree / "code.ts").write_text("x")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "fix: resolve conflict")
        with self.assertRaisesRegex(RunBlocked, "Code changed since the final handoff"):
            self.ready()

    def test_requires_the_pushed_head(self):
        self.pr["headRefOid"] = "other"
        with self.assertRaisesRegex(RunBlocked, "Push the branch"):
            self.ready()
        self.github.mark_ready.assert_not_called()

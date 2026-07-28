import subprocess
import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.git_workspace import GitWorkspace, _matches_issue_branch


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class GitWorkspaceTests(unittest.TestCase):
    def test_accepts_only_exact_or_truncated_linear_issue_branch(self):
        expected = "benjamin/ts-12-long-linear-branch-name"

        self.assertTrue(_matches_issue_branch(expected, expected, "TS-12"))
        self.assertTrue(
            _matches_issue_branch(
                "benjamin/ts-12-long-linear",
                expected,
                "TS-12",
            )
        )
        self.assertFalse(
            _matches_issue_branch(
                "benjamin/ts-12-different",
                expected,
                "TS-12",
            )
        )
        self.assertFalse(
            _matches_issue_branch(
                "benjamin/unrelated",
                expected,
                "TS-12",
            )
        )

    def test_creates_issue_branch_from_requested_base(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / "file.txt").write_text("base\n")
            git(seed, "add", "file.txt")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(root, "clone", str(remote), str(checkout))

            workspace = GitWorkspace(checkout, worktrees)
            workspace.fetch("development")
            result = workspace.create(
                "benjamin/ts-10",
                "development",
                "TS-10",
                "run-id",
            )

            self.assertEqual(
                git(result.path, "branch", "--show-current"),
                "benjamin/ts-10",
            )
            self.assertEqual(result.created_from, "origin/development")

    def test_reuses_remote_issue_branch_even_when_requested_base_is_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / "file.txt").write_text("base\n")
            git(seed, "add", "file.txt")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(seed, "switch", "-c", "benjamin/ts-11")
            (seed / "issue.txt").write_text("existing\n")
            git(seed, "add", "issue.txt")
            git(seed, "commit", "-m", "existing issue work")
            git(seed, "push", "-u", "origin", "benjamin/ts-11")
            git(root, "clone", str(remote), str(checkout))

            workspace = GitWorkspace(checkout, worktrees)
            workspace.fetch("does-not-exist")
            result = workspace.create(
                "benjamin/ts-11",
                "does-not-exist",
                "TS-11",
                "run-id",
            )

            self.assertEqual(result.created_from, "origin/benjamin/ts-11")
            self.assertEqual(
                git(result.path, "branch", "--show-current"),
                "benjamin/ts-11",
            )

    def test_adopts_registered_worktree_and_records_existing_changes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            superset = root / "superset-worktree"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text(".local-runtime/\n")
            (seed / "file.txt").write_text("base\n")
            git(seed, "add", ".gitignore", "file.txt")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(root, "clone", str(remote), str(checkout))
            git(
                checkout,
                "worktree",
                "add",
                "-b",
                "benjamin/ts-12-long-linear",
                str(superset),
                "origin/development",
            )
            (superset / "file.txt").write_text("preexisting\n")

            workspace = GitWorkspace(checkout, worktrees)
            result = workspace.adopt(
                superset,
                "benjamin/ts-12-long-linear-branch-name",
                "TS-12",
            )

            self.assertEqual(result.path, superset.resolve())
            self.assertEqual(result.branch, "benjamin/ts-12-long-linear")
            self.assertEqual(result.created_from, "adopted:benjamin/ts-12-long-linear")
            self.assertEqual(result.adopted_status, (" M file.txt",))

    def test_adopts_detached_codex_worktree_and_creates_issue_branch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            codex = root / "codex-worktree"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text(".local-runtime/\n")
            (seed / "file.txt").write_text("base\n")
            git(seed, "add", ".gitignore", "file.txt")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(root, "clone", str(remote), str(checkout))
            git(
                checkout,
                "worktree",
                "add",
                "--detach",
                str(codex),
                "origin/development",
            )

            workspace = GitWorkspace(checkout, worktrees)
            workspace.fetch("development")
            result = workspace.adopt_codex(
                codex,
                "benjamin/ts-13-codex-mode",
                "development",
                "TS-13",
            )

            self.assertEqual(result.path, codex.resolve())
            self.assertEqual(result.branch, "benjamin/ts-13-codex-mode")
            self.assertEqual(result.created_from, "codex:origin/development")
            self.assertEqual(
                git(codex, "branch", "--show-current"),
                "benjamin/ts-13-codex-mode",
            )

    def test_codex_mode_rejects_unrelated_attached_branch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            codex = root / "codex-worktree"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text(".local-runtime/\n")
            git(seed, "add", ".gitignore")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(root, "clone", str(remote), str(checkout))
            git(
                checkout,
                "worktree",
                "add",
                "-b",
                "unrelated",
                str(codex),
                "origin/development",
            )

            workspace = GitWorkspace(checkout, worktrees)
            with self.assertRaisesRegex(RunBlocked, "does not match Linear branch"):
                workspace.adopt_codex(
                    codex,
                    "benjamin/ts-14-codex-mode",
                    "development",
                    "TS-14",
                )

    def test_codex_mode_rejects_detached_commits_outside_base(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            worktrees = root / "worktrees"
            codex = root / "codex-worktree"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "development", str(seed))
            git(seed, "config", "user.email", "test@example.com")
            git(seed, "config", "user.name", "Test")
            (seed / ".gitignore").write_text(".local-runtime/\n")
            (seed / "file.txt").write_text("base\n")
            git(seed, "add", ".gitignore", "file.txt")
            git(seed, "commit", "-m", "base")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "development")
            git(root, "clone", str(remote), str(checkout))
            git(
                checkout,
                "worktree",
                "add",
                "--detach",
                str(codex),
                "origin/development",
            )
            git(codex, "config", "user.email", "test@example.com")
            git(codex, "config", "user.name", "Test")
            (codex / "detached.txt").write_text("unpreserved\n")
            git(codex, "add", "detached.txt")
            git(codex, "commit", "-m", "detached work")

            workspace = GitWorkspace(checkout, worktrees)
            workspace.fetch("development")
            with self.assertRaisesRegex(RunBlocked, "commits not contained"):
                workspace.adopt_codex(
                    codex,
                    "benjamin/ts-15-codex-mode",
                    "development",
                    "TS-15",
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from issue_delivery_orchestrator.cli import ensure_pull_request
from issue_delivery_orchestrator.github import GitHubClient, PullRequest


class GitHubEvidenceTests(unittest.TestCase):
    def test_explicit_run_target_overrides_profile_target(self):
        client = GitHubClient(Path("/tmp"), pr_target="test")

        self.assertEqual(client.pr_target, "test")

    def test_create_passes_draft_and_persisted_target_to_github(self):
        client = GitHubClient(Path("/tmp"), pr_target="test")
        created = PullRequest(
            number=1,
            url="https://github.com/example/repo/pull/1",
            state="OPEN",
            merged_at=None,
            is_draft=True,
            head="feature",
            base="test",
        )
        result = SimpleNamespace(
            returncode=0,
            stdout=f"{created.url}\n",
            stderr="",
        )

        with (
            patch("issue_delivery_orchestrator.github.run", return_value=result) as runner,
            patch.object(client, "view", return_value=created),
        ):
            client.create("feature", "Title", Path("/tmp/body.md"))

        command = runner.call_args.args[0]
        self.assertIn("--draft", command)
        self.assertEqual(command[command.index("--base") + 1], "test")

    def test_ensure_pr_preserves_existing_draft_and_ready_states(self):
        for is_draft in (True, False):
            with self.subTest(is_draft=is_draft), tempfile.TemporaryDirectory() as raw:
                worktree = Path(raw).resolve()
                body = worktree / "body.md"
                body.touch()
                state = {
                    "worktree": str(worktree), "branch": "feature", "target": "test"
                }
                existing = PullRequest(
                    number=1, url="https://github.com/example/repo/pull/1",
                    state="OPEN", merged_at=None, is_draft=is_draft,
                    head="feature", base="test",
                )
                with (
                    patch("issue_delivery_orchestrator.cli._verified_linear",
                          return_value=(None, "test")),
                    patch("issue_delivery_orchestrator.cli.GitHubClient") as client,
                    patch("issue_delivery_orchestrator.cli.run",
                          return_value=SimpleNamespace(stdout="feature\n")) as runner,
                    patch("issue_delivery_orchestrator.cli.save_state"),
                    patch("issue_delivery_orchestrator.cli._public_state", return_value={}),
                ):
                    client.return_value.find.return_value = [existing]
                    result = ensure_pull_request(state, body, None)

                self.assertEqual(result["pr"]["is_draft"], is_draft)
                client.return_value.create.assert_not_called()
                self.assertEqual(
                    [call.args[0] for call in runner.call_args_list],
                    [["git", "branch", "--show-current"],
                     ["git", "push", "-u", "origin", "feature"]],
                )

    def test_detects_current_user_reaction(self):
        client = GitHubClient(Path("/tmp"), expected_login="benjaminlillo")
        reactions = [
            {"content": "+1", "user": {"login": "someone-else"}},
            {"content": "+1", "user": {"login": "benjaminlillo"}},
        ]
        with patch.object(
            client,
            "issue_comment_reactions",
            return_value=reactions,
        ):
            self.assertTrue(
                client.has_issue_comment_reaction(123, content="+1")
            )
            self.assertFalse(
                client.has_issue_comment_reaction(
                    123,
                    content="+1",
                    login="missing-user",
                )
            )

    def test_adds_reaction_only_when_current_user_has_not_reacted(self):
        client = GitHubClient(Path("/tmp"), expected_login="benjaminlillo")
        empty = SimpleNamespace(returncode=0, stdout="[[]]", stderr="")
        reaction = {"+1": True}
        with (
            patch(
                "issue_delivery_orchestrator.github.run",
                return_value=empty,
            ),
            patch.object(client, "_api_json", return_value=reaction) as create,
        ):
            created = client.add_issue_comment_reaction(123, content="+1")

        self.assertTrue(created)
        create.assert_called_once()

        existing = SimpleNamespace(
            returncode=0,
            stdout='[[{"content":"+1","user":{"login":"benjaminlillo"}}]]',
            stderr="",
        )
        with (
            patch(
                "issue_delivery_orchestrator.github.run",
                return_value=existing,
            ),
            patch.object(client, "_api_json") as duplicate,
        ):
            created = client.add_issue_comment_reaction(123, content="+1")

        self.assertFalse(created)
        duplicate.assert_not_called()

    def test_publishes_files_to_evidence_branch_and_returns_relative_url(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            screenshot = root / "image.png"
            screenshot.write_bytes(b"png")
            client = GitHubClient(root)

            def api(endpoint, **kwargs):
                if endpoint.endswith("/git/blobs"):
                    return {"sha": "blob-sha"}
                if "/git/ref/heads/" in endpoint:
                    return {"object": {"sha": "parent-sha"}}
                if endpoint.endswith("/git/commits/parent-sha"):
                    return {"tree": {"sha": "parent-tree"}}
                if endpoint.endswith("/git/trees"):
                    return {"sha": "new-tree"}
                if endpoint.endswith("/git/commits"):
                    return {"sha": "new-commit"}
                raise AssertionError(endpoint)

            success = (SimpleNamespace(returncode=0, stdout="{}", stderr=""), {})
            with (
                patch.object(client, "_ensure_evidence_branch"),
                patch.object(client, "_api_json", side_effect=api),
                patch.object(client, "_api_json_result", return_value=success),
            ):
                urls = client.publish_evidence_files(
                    [(screenshot, ".issue-delivery-evidence/SFW-1/run/image.png")],
                    message="publish evidence",
                )

        self.assertEqual(
            urls[".issue-delivery-evidence/SFW-1/run/image.png"],
            "../blob/codex-ui-evidence/.issue-delivery-evidence/SFW-1/run/image.png?raw=true",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from issue_delivery_orchestrator.github import GitHubClient


class GitHubEvidenceTests(unittest.TestCase):
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

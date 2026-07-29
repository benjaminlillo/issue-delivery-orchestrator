from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from issue_delivery_orchestrator.errors import OrchestrationError
from issue_delivery_orchestrator.evidence import (
    _evidence_target_path,
    _pr_body,
    _verification,
    prepare_evidence,
    publish_evidence,
)
from issue_delivery_orchestrator.png_codec import PngImage, encode_png
from issue_delivery_orchestrator.util import read_json


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temporary.name)
        git(self.worktree, "init", "-b", "test")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "Test")
        (self.worktree / "file.txt").write_text("content\n")
        git(self.worktree, "add", "file.txt")
        git(self.worktree, "commit", "-m", "initial")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        self.state = {"runtimes": [{"runtimeId": "rt-1"}]}

    def tearDown(self):
        self.temporary.cleanup()

    def manifest(
        self,
        commit: str | None = None,
        *,
        provider: str | None = None,
    ):
        verification = {
            "status": "PASS",
            "verifiedCommit": commit or self.head,
            "runtimeId": "rt-1",
            "verifiedAt": "2026-07-27T12:00:00Z",
            "scenarioIds": ["REPAIR-1"],
        }
        if provider:
            verification["provider"] = provider
        return {
            "verification": {
                **verification,
            }
        }

    def test_accepts_pass_for_current_head_and_registered_runtime(self):
        receipt = _verification(self.manifest(), self.state, self.worktree)
        self.assertEqual(receipt["verifiedCommit"], self.head)
        self.assertNotIn("provider", receipt)

    def test_accepts_browser_pass_for_browser_run(self):
        self.state["mode"] = {"name": "codex"}
        self.state["reviewer"] = {"method": "codex-browser"}

        receipt = _verification(
            self.manifest(provider="codex-browser"),
            self.state,
            self.worktree,
        )

        self.assertEqual(receipt["provider"], "codex-browser")

    def test_rejects_evidence_from_a_different_reviewer(self):
        self.state["mode"] = {"name": "codex"}
        self.state["reviewer"] = {"method": "codex-browser"}

        with self.assertRaisesRegex(OrchestrationError, "provider mismatch"):
            _verification(
                self.manifest(provider="cua-driver"),
                self.state,
                self.worktree,
            )

    def test_rejects_stale_pass_after_code_changes(self):
        stale = self.head
        (self.worktree / "file.txt").write_text("changed\n")
        git(self.worktree, "add", "file.txt")
        git(self.worktree, "commit", "-m", "repair after verification")
        with self.assertRaisesRegex(OrchestrationError, "stale"):
            _verification(self.manifest(stale), self.state, self.worktree)

    def test_rejects_unregistered_runtime(self):
        manifest = self.manifest()
        manifest["verification"]["runtimeId"] = "rt-other"
        with self.assertRaisesRegex(OrchestrationError, "unregistered"):
            _verification(manifest, self.state, self.worktree)

    def test_pr_body_uses_github_path_instead_of_private_linear_url(self):
        body = _pr_body(
            "<!-- marker -->",
            [
                {
                    "storyId": "REPAIR-1",
                    "title": "Fixed state",
                    "caption": "Verified",
                    "url": "https://uploads.linear.app/private/image",
                    "githubUrl": "../blob/codex-ui-evidence/path/image.png?raw=true",
                }
            ],
        )
        self.assertIn("../blob/codex-ui-evidence/path/image.png?raw=true", body)
        self.assertNotIn("uploads.linear.app", body)

    def test_pr_body_names_browser_provider(self):
        body = _pr_body(
            "<!-- marker -->",
            [
                {
                    "storyId": "US-1",
                    "title": "Browser state",
                    "caption": "Verified",
                    "githubUrl": "../blob/codex-ui-evidence/path/image.png?raw=true",
                }
            ],
            provider="codex-browser",
        )

        self.assertIn("Browser integrado de Codex", body)

    def test_evidence_target_is_content_addressed(self):
        screenshot = {
            "storyId": "REPAIR 1",
            "path": self.worktree / "file.txt",
        }
        state = {"issue": {"identifier": "SFW-1"}, "runId": "run-1"}
        target = _evidence_target_path(state, screenshot, 1)
        self.assertRegex(
            target,
            r"^\.issue-delivery-evidence/SFW-1/run-1/01-REPAIR-1-[a-f0-9]{12}\.png$",
        )

    def test_prepares_annotated_evidence_and_preserves_original(self):
        screenshot = self.worktree / "screen.png"
        original = encode_png(
            PngImage(100, 60, bytearray((245, 245, 245, 255) * 100 * 60))
        )
        screenshot.write_bytes(original)
        manifest_path = self.worktree / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "evidenceVersion": 2,
                    **self.manifest(),
                    "screenshots": [
                        {
                            "storyId": "US-1",
                            "title": "Final state",
                            "caption": "Verified",
                            "path": "screen.png",
                            "callouts": [
                                {
                                    "kind": "highlight",
                                    "caption": "Nuevo selector",
                                    "bounds": {
                                        "x": 0.2,
                                        "y": 0.2,
                                        "width": 0.4,
                                        "height": 0.4,
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        )
        state = {
            "worktree": str(self.worktree),
            "runtimes": [{"runtimeId": "rt-1"}],
        }

        prepared = prepare_evidence(state, manifest_path)

        annotated = self.worktree / prepared["screenshots"][0]["displayPath"]
        self.assertTrue(annotated.is_file())
        self.assertNotEqual(annotated.read_bytes(), original)
        self.assertEqual(screenshot.read_bytes(), original)
        self.assertEqual(
            read_json(manifest_path)["screenshots"][0]["annotatedPath"],
            "screen.annotated.png",
        )

    def test_evidence_v2_requires_callouts_or_reason(self):
        screenshot = self.worktree / "screen.png"
        screenshot.write_bytes(
            encode_png(PngImage(10, 10, bytearray((255, 255, 255, 255) * 100)))
        )
        manifest_path = self.worktree / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "evidenceVersion": 2,
                    **self.manifest(),
                    "screenshots": [
                        {
                            "storyId": "US-1",
                            "path": "screen.png",
                        }
                    ],
                }
            )
        )
        state = {
            "worktree": str(self.worktree),
            "runtimes": [{"runtimeId": "rt-1"}],
        }

        with self.assertRaisesRegex(OrchestrationError, "callouts or annotationReason"):
            prepare_evidence(state, manifest_path)

    def test_evidence_v2_accepts_global_annotation_reason(self):
        screenshot = self.worktree / "screen.png"
        screenshot.write_bytes(
            encode_png(PngImage(10, 10, bytearray((255, 255, 255, 255) * 100)))
        )
        manifest_path = self.worktree / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "evidenceVersion": 2,
                    **self.manifest(),
                    "screenshots": [
                        {
                            "storyId": "US-1",
                            "path": "screen.png",
                            "annotationReason": "El cambio afecta la composición completa.",
                        }
                    ],
                }
            )
        )
        state = {
            "worktree": str(self.worktree),
            "runtimes": [{"runtimeId": "rt-1"}],
        }

        prepared = prepare_evidence(state, manifest_path)

        self.assertEqual(prepared["screenshots"][0]["calloutCount"], 0)
        self.assertEqual(
            prepared["screenshots"][0]["displayPath"],
            "screen.png",
        )

    def test_pr_body_explains_callouts_and_links_original(self):
        body = _pr_body(
            "<!-- marker -->",
            [
                {
                    "storyId": "US-1",
                    "title": "Annotated state",
                    "caption": "Verified",
                    "callouts": [
                        {
                            "caption": "Nuevo selector",
                        }
                    ],
                    "githubUrl": "../annotated.png",
                    "githubOriginalUrl": "../original.png",
                }
            ],
        )

        self.assertIn("1. Nuevo selector", body)
        self.assertIn("[Ver captura original sin anotaciones](../original.png)", body)
        self.assertIn("no forman parte de la aplicación", body)

    def test_publication_uploads_annotated_and_original_pngs(self):
        screenshot = self.worktree / "screen.png"
        screenshot.write_bytes(
            encode_png(PngImage(100, 60, bytearray((245, 245, 245, 255) * 6000)))
        )
        manifest_path = self.worktree / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "evidenceVersion": 2,
                    **self.manifest(),
                    "screenshots": [
                        {
                            "storyId": "US-1",
                            "title": "Final state",
                            "caption": "Verified",
                            "path": "screen.png",
                            "callouts": [
                                {
                                    "kind": "circle",
                                    "caption": "Nuevo estado",
                                    "bounds": {
                                        "x": 0.2,
                                        "y": 0.2,
                                        "width": 0.4,
                                        "height": 0.4,
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        )

        class Linear:
            def __init__(self):
                self.uploads = []
                self.description = ""

            def upload_file(self, path):
                self.uploads.append(Path(path))
                return f"https://linear.example/{Path(path).name}"

            def issue(self, _identifier):
                return SimpleNamespace(id="linear-id", url="https://linear/US-1", description="")

            def update_description(self, _issue_id, description):
                self.description = description

            def post_comment(self, _issue_id, _body):
                return None

        linear = Linear()
        state = {
            "worktree": str(self.worktree),
            "runId": "run-1",
            "issue": {"identifier": "US-1"},
            "runtimes": [{"runtimeId": "rt-1"}],
            "artifacts": {},
            "pr": None,
        }

        receipt = publish_evidence(
            state,
            manifest_path,
            linear=linear,
            github=None,
        )

        self.assertEqual(len(linear.uploads), 2)
        self.assertTrue(linear.uploads[0].name.endswith(".annotated.png"))
        self.assertEqual(linear.uploads[1], screenshot.resolve())
        self.assertEqual(receipt["assets"][0]["originalPath"], "screen.png")
        self.assertIn("Ver captura original sin anotaciones", linear.description)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.review import (
    _is_relevant_bot,
    acknowledge_processed_blocker,
    assert_review_converged,
    publish_skip_summary,
    wait_for_quiet_review,
)
from issue_delivery_orchestrator.review_budget import (
    approve_review_extension,
    record_review_repair,
    request_review_extension,
    review_repair_budget,
)


class ReviewFilterTests(unittest.TestCase):
    def test_initializes_budget_for_a_legacy_run_without_counting_wait_snapshots(self):
        state = {}

        budget = review_repair_budget(state)

        self.assertEqual(budget["approvedRepairs"], 5)
        self.assertEqual(budget["usedRepairs"], 0)
        self.assertEqual(state["reviewRepairBudget"]["repairs"], [])

    def test_wait_snapshots_do_not_consume_or_cap_repair_budget(self):
        with tempfile.TemporaryDirectory() as raw:
            review_root = (
                Path(raw)
                / ".local-runtime/issue-delivery-orchestrator/run-1/review"
            )
            review_root.mkdir(parents=True)
            for number in range(1, 6):
                (review_root / f"round-{number:02d}.json").write_text("{}")
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
                "reviewRepairBudget": {
                    "batchSize": 5,
                    "approvedRepairs": 5,
                    "repairs": [],
                    "extensions": [],
                },
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(number=10)
            ticks = iter((0.0, 1.0, 1.0))

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value={"headSha": "abc", "botGeneralComments": []},
                ),
            ):
                result = wait_for_quiet_review(
                    state,
                    quiet_seconds=1,
                    max_seconds=1,
                    poll_seconds=1,
                    clock=lambda: next(ticks),
                )

            self.assertTrue((review_root / "round-06.json").is_file())
            self.assertEqual(result["repairBudget"]["remainingRepairs"], 5)

    def test_counts_distinct_pushed_fix_shas_and_renews_budget_after_approval(self):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "status": "active",
                "currentPhase": "review-convergence",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
                "reviewRepairBudget": {
                    "batchSize": 2,
                    "approvedRepairs": 2,
                    "repairs": [],
                    "extensions": [],
                },
            }
            client = Mock()

            with (
                patch(
                    "issue_delivery_orchestrator.review_budget.GitHubClient",
                    return_value=client,
                ),
                patch("issue_delivery_orchestrator.review_budget.run") as git_run,
            ):
                client.head_sha.return_value = "sha-1"
                git_run.return_value = SimpleNamespace(stdout="sha-1\n")
                first = record_review_repair(state, fixes=["blocker-1"])
                duplicate = record_review_repair(state, fixes=["blocker-1"])

                client.head_sha.return_value = "sha-2"
                git_run.return_value = SimpleNamespace(stdout="sha-2\n")
                second = record_review_repair(state, fixes=["blocker-2", "blocker-3"])

                client.head_sha.return_value = "sha-3"
                git_run.return_value = SimpleNamespace(stdout="sha-3\n")
                with self.assertRaisesRegex(RunBlocked, "budget is exhausted"):
                    record_review_repair(state, fixes=["blocker-4"])

            self.assertTrue(first["recorded"])
            self.assertFalse(duplicate["recorded"])
            self.assertTrue(second["recorded"])
            self.assertEqual(review_repair_budget(state)["usedRepairs"], 2)
            self.assertEqual(review_repair_budget(state)["remainingRepairs"], 0)

            request = request_review_extension(
                state,
                fixes=[
                    {
                        "title": "Public wiring",
                        "reason": "The formatter path lacks coverage.",
                    }
                ],
                artifact=(
                    ".local-runtime/issue-delivery-orchestrator/run-1/"
                    "review/extension-request-01.json"
                ),
            )
            self.assertEqual(request["status"], "needs_user_decision")
            self.assertEqual(request["blocker"]["requestedRepairs"], 2)

            renewed = approve_review_extension(state)

            self.assertEqual(state["status"], "active")
            self.assertIsNone(state["blocker"])
            self.assertEqual(renewed["approvedRepairs"], 4)
            self.assertEqual(renewed["remainingRepairs"], 2)
            self.assertEqual(renewed["extensionCount"], 1)

    def test_rejects_extension_request_while_repairs_remain(self):
        state = {
            "status": "active",
            "currentPhase": "review-convergence",
            "reviewRepairBudget": {
                "batchSize": 5,
                "approvedRepairs": 5,
                "repairs": [],
                "extensions": [],
            },
        }

        with self.assertRaisesRegex(RunBlocked, "5 repair\(s\) available"):
            request_review_extension(
                state,
                fixes=[{"title": "Fix", "reason": "Valid blocker"}],
                artifact="review/request.json",
            )

    def test_includes_coderabbit_and_only_hellonstone_blockers(self):
        self.assertTrue(
            _is_relevant_bot(
                {"user": {"login": "coderabbitai[bot]"}, "body": "Concrete issue"}
            )
        )
        self.assertTrue(
            _is_relevant_bot(
                {
                    "user": {"login": "Hellonston"},
                    "body": "🔴 BLOCKERS:\n\n- Broken\n\n🟡 SUGERENCIAS:",
                }
            )
        )
        self.assertFalse(
            _is_relevant_bot(
                {
                    "user": {"login": "Hellonston"},
                    "body": "🔴 BLOCKERS:\n\n- Ninguno.\n\n🟡 SUGERENCIAS:",
                }
            )
        )
        self.assertFalse(
            _is_relevant_bot(
                {
                    "user": {"login": "Hellonston"},
                    "body": (
                        "🔴 BLOCKERS:\n\n"
                        "- No encontré defectos funcionales ni regresiones que "
                        "bloqueen la aprobación.\n\n"
                        "🟡 SUGERENCIAS:"
                    ),
                }
            )
        )
        self.assertFalse(
            _is_relevant_bot(
                {"user": {"login": "Hellonston"}, "body": "Refactor suggestion"}
            )
        )
        self.assertFalse(
            _is_relevant_bot(
                {"user": {"login": "human-reviewer"}, "body": "Please change this"}
            )
        )

    def test_acknowledges_processed_blocker_and_records_decision(self):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "reviewAcknowledgements": [],
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(number=10)
            client.issue_comment.return_value = {
                "id": 123,
                "issue_url": "https://api.github.com/repos/example/repo/issues/10",
                "html_url": "https://github.com/example/repo/pull/10#issuecomment-123",
                "user": {"login": "Hellonston"},
                "body": "🔴 BLOCKERS:\n\n- Broken\n\n🟡 SUGERENCIAS:",
            }
            client.add_issue_comment_reaction.return_value = True

            with patch(
                "issue_delivery_orchestrator.review.GitHubClient",
                return_value=client,
            ):
                result = acknowledge_processed_blocker(
                    state,
                    comment_id=123,
                    decision="FIX",
                )
                client.add_issue_comment_reaction.return_value = False
                duplicate = acknowledge_processed_blocker(
                    state,
                    comment_id=123,
                    decision="FIX",
                )
                with self.assertRaises(RunBlocked):
                    acknowledge_processed_blocker(
                        state,
                        comment_id=123,
                        decision="SKIP",
                    )

            self.assertTrue(result["created"])
            self.assertFalse(duplicate["created"])
            self.assertEqual(state["reviewAcknowledgements"][0]["decision"], "FIX")
            self.assertTrue(
                state["reviewAcknowledgements"][0]["reactionCreatedInitially"]
            )
            self.assertTrue(state["reviewAcknowledgements"][0]["reactionPresent"])
            self.assertEqual(client.add_issue_comment_reaction.call_count, 2)
            self.assertTrue(
                (
                    Path(raw)
                    / ".local-runtime/issue-delivery-orchestrator/run-1/state.json"
                ).is_file()
            )

    def test_final_gate_rejects_unresolved_inline_and_unacknowledged_general_blockers(
        self,
    ):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(
                number=10,
                url=state["pr"]["url"],
            )
            client.review_threads.return_value = [
                {
                    "id": "thread-1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": 456,
                                "url": f"{state['pr']['url']}#discussion_r456",
                                "author": {"login": "coderabbitai[bot]"},
                            }
                        ]
                    },
                }
            ]
            client.has_issue_comment_reaction.return_value = False
            snapshot = {
                "headSha": "abc123",
                "botGeneralComments": [
                    {
                        "id": 123,
                        "html_url": f"{state['pr']['url']}#issuecomment-123",
                        "user": {"login": "Hellonston"},
                    }
                ],
            }

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value=snapshot,
                ),
            ):
                with self.assertRaisesRegex(
                    RunBlocked,
                    r"1 inline thread\(s\), 1 general blocker\(s\)",
                ):
                    assert_review_converged(state)

            receipt_path = (
                Path(raw)
                / ".local-runtime/issue-delivery-orchestrator/run-1/review/final-gate.json"
            )
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(
                state["artifacts"]["finalReviewGate"],
                ".local-runtime/issue-delivery-orchestrator/run-1/review/final-gate.json",
            )

    def test_final_gate_ignores_human_threads_and_accepts_acknowledged_general_blocker(
        self,
    ):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(
                number=10,
                url=state["pr"]["url"],
            )
            client.review_threads.return_value = [
                {
                    "id": "thread-human",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": 789,
                                "url": f"{state['pr']['url']}#discussion_r789",
                                "author": {"login": "human-reviewer"},
                            }
                        ]
                    },
                }
            ]
            client.has_issue_comment_reaction.return_value = True
            snapshot = {
                "headSha": "abc123",
                "botGeneralComments": [
                    {
                        "id": 123,
                        "html_url": f"{state['pr']['url']}#issuecomment-123",
                        "user": {"login": "Hellonston"},
                    }
                ],
            }

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value=snapshot,
                ),
            ):
                result = assert_review_converged(state)

            self.assertTrue(result["passed"])
            self.assertEqual(result["pendingInlineThreads"], [])
            self.assertEqual(result["pendingGeneralBlockers"], [])

    def test_publishes_summary_only_when_all_pending_feedback_is_skip(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "skips.json"
            input_path.write_text(
                json.dumps(
                    {
                        "skips": [
                            {
                                "commentId": 123,
                                "title": "Fallback innecesario",
                                "reason": "El flujo vigente ya cubre este caso.",
                            },
                            {
                                "commentId": 456,
                                "title": "Generalización fuera de alcance",
                                "reason": "No existe un requisito actual para soportarla.",
                            },
                        ]
                    }
                )
            )
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
                "reviewAcknowledgements": [],
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(
                number=10,
                url=state["pr"]["url"],
            )
            client.review_threads.return_value = [
                {
                    "id": "thread-1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": 456,
                                "url": f"{state['pr']['url']}#discussion_r456",
                                "author": {"login": "coderabbitai[bot]"},
                            }
                        ]
                    },
                }
            ]
            client.has_issue_comment_reaction.return_value = False
            client.upsert_comment.return_value = (
                f"{state['pr']['url']}#issuecomment-summary"
            )
            snapshot = {
                "headSha": "abc123",
                "botGeneralComments": [
                    {
                        "id": 123,
                        "html_url": f"{state['pr']['url']}#issuecomment-123",
                        "user": {"login": "Hellonston"},
                    }
                ],
            }

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value=snapshot,
                ),
            ):
                result = publish_skip_summary(state, input_path=input_path)
                client.review_threads.return_value = []
                snapshot["botGeneralComments"] = []
                repeated = publish_skip_summary(state, input_path=input_path)

            self.assertEqual(result["commentIds"], [123, 456])
            self.assertEqual(repeated["commentIds"], [123, 456])
            body = client.upsert_comment.call_args.args[2]
            self.assertIn("Fallback innecesario", body)
            self.assertIn("El flujo vigente ya cubre este caso.", body)
            self.assertIn("issue-delivery-skip-summary:run-1", body)
            self.assertEqual(state["skipSummary"]["commentIds"], [123, 456])
            self.assertEqual(client.upsert_comment.call_count, 2)

    def test_rejects_skip_summary_missing_a_pending_blocker(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "skips.json"
            input_path.write_text(
                json.dumps(
                    {
                        "skips": [
                            {
                                "commentId": 123,
                                "reason": "No corresponde al alcance.",
                            }
                        ]
                    }
                )
            )
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(
                number=10,
                url=state["pr"]["url"],
            )
            client.review_threads.return_value = [
                {
                    "id": "thread-1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": 456,
                                "url": f"{state['pr']['url']}#discussion_r456",
                                "author": {"login": "coderabbitai[bot]"},
                            }
                        ]
                    },
                }
            ]
            client.has_issue_comment_reaction.return_value = False
            snapshot = {
                "headSha": "abc123",
                "botGeneralComments": [
                    {
                        "id": 123,
                        "html_url": f"{state['pr']['url']}#issuecomment-123",
                        "user": {"login": "Hellonston"},
                    }
                ],
            }

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value=snapshot,
                ),
            ):
                with self.assertRaisesRegex(RunBlocked, r"missing=\[456\]"):
                    publish_skip_summary(state, input_path=input_path)

            client.upsert_comment.assert_not_called()

    def test_rejects_acknowledging_skip_before_public_summary(self):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "reviewAcknowledgements": [],
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(number=10)
            client.issue_comment.return_value = {
                "id": 123,
                "issue_url": "https://api.github.com/repos/example/repo/issues/10",
                "html_url": "https://github.com/example/repo/pull/10#issuecomment-123",
                "user": {"login": "Hellonston"},
                "body": "🔴 BLOCKERS:\n\n- Broken\n\n🟡 SUGERENCIAS:",
            }

            with patch(
                "issue_delivery_orchestrator.review.GitHubClient",
                return_value=client,
            ):
                with self.assertRaisesRegex(RunBlocked, "publish-skip-summary"):
                    acknowledge_processed_blocker(
                        state,
                        comment_id=123,
                        decision="SKIP",
                    )

            client.add_issue_comment_reaction.assert_not_called()

    def test_final_gate_rejects_legacy_skip_without_public_summary(self):
        with tempfile.TemporaryDirectory() as raw:
            state = {
                "worktree": raw,
                "runId": "run-1",
                "pr": {"url": "https://github.com/example/repo/pull/10"},
                "artifacts": {},
                "reviewAcknowledgements": [
                    {
                        "commentId": 123,
                        "commentUrl": (
                            "https://github.com/example/repo/pull/10#issuecomment-123"
                        ),
                        "decision": "SKIP",
                    }
                ],
            }
            client = Mock()
            client.view.return_value = SimpleNamespace(
                number=10,
                url=state["pr"]["url"],
            )
            client.review_threads.return_value = []
            snapshot = {"headSha": "abc123", "botGeneralComments": []}

            with (
                patch(
                    "issue_delivery_orchestrator.review.GitHubClient",
                    return_value=client,
                ),
                patch(
                    "issue_delivery_orchestrator.review.review_snapshot",
                    return_value=snapshot,
                ),
            ):
                with self.assertRaisesRegex(
                    RunBlocked,
                    r"1 unpublished SKIP acknowledgement\(s\)",
                ):
                    assert_review_converged(state)


if __name__ == "__main__":
    unittest.main()

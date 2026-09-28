import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.token_usage import attach_token_usage, collect_token_usage


def counts(value):
    return {
        "input_tokens": value * 9,
        "cached_input_tokens": value * 6,
        "output_tokens": value,
        "total_tokens": value * 10,
    }


class TokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.db = sqlite3.connect(self.home / "state_5.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, source TEXT)")
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "CODEX_THREAD_ID": "root"})
        env.start()
        self.addCleanup(env.stop)
        for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(key, None)
        self.state = {}
        self.thread("root")
        self.event("root", 100, 100)

    def thread(self, key, parent=None, created="2026-09-15T10:00:00Z"):
        source = json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": parent}}}) if parent else "vscode"
        self.db.execute("INSERT INTO threads VALUES (?, ?, ?)", (key, str(self.home / key), source))
        self.db.commit()
        self.write(key, {"type": "session_meta", "timestamp": created, "payload": {"id": key}})

    def write(self, key, event):
        with (self.home / key).open("a") as f:
            f.write(json.dumps(event) + "\n")

    def event(self, key, total, last, stamp="2026-09-15T10:01:00Z"):
        self.write(key, {"type": "event_msg", "timestamp": stamp, "payload": {
            "type": "token_count", "info": {"total_token_usage": counts(total), "last_token_usage": counts(last)},
        }})

    def test_state_creation_persists_baseline(self):
        from issue_delivery_orchestrator.state import create_state, load_state, run_root

        state = create_state(
            worktree=self.home / "worktree", run_id="test-run",
            issue={"identifier": "TS-1", "title": "Title"}, branch="feature", base="development",
            created_from="origin/development", adopted_head="abc", identities={},
        )
        persisted = load_state(run_root(self.home / "worktree", "test-run") / "state.json")
        self.assertEqual(persisted["tokenUsageTracking"]["roots"], ["root"])
        from issue_delivery_orchestrator.cli import _public_state

        measurement = _public_state(persisted)["tokenMeasurement"]
        self.assertEqual((measurement["status"], measurement["harness"]), ("ready", "codex"))
        self.event("root", 103, 3)
        self.assertEqual(collect_token_usage(persisted)["usage"], counts(3))
        self.assertEqual(state["status"], "active")

    def test_sums_only_run_usage_and_descendants_once(self):
        self.thread("old-child", "root")
        self.event("old-child", 20, 20)
        attach_token_usage(self.state, new_run=True)
        self.event("root", 110, 10)
        self.event("old-child", 23, 3)
        self.thread("child", "root")
        self.event("child", 5, 5)
        self.thread("grandchild", "child")
        self.event("grandchild", 2, 2)
        self.event("grandchild", 2, 2)
        self.thread("unrelated")
        self.event("unrelated", 999, 999)
        report = collect_token_usage(self.state)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["sessions"], 4)
        self.assertEqual(report["usage"], counts(20))
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(20))
        self.event("child", 8, 3)
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(23))

    def test_inherited_history_and_inherited_counters_are_not_added(self):
        attach_token_usage(self.state, new_run=True)
        self.thread("fork", "root", created="2026-09-15T11:00:00Z")
        self.event("fork", 100, 100)
        self.event("fork", 107, 7, stamp="2026-09-15T11:01:00Z")
        self.event("fork", 111, 4, stamp="2026-09-15T11:02:00Z")
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(11))

    def test_fork_with_fresh_counters_after_copied_history(self):
        attach_token_usage(self.state, new_run=True)
        self.thread("fork", "root", created="2026-09-15T11:00:00Z")
        self.event("fork", 100, 100)
        self.event("fork", 7, 7, stamp="2026-09-15T11:01:00Z")
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(7))

    def test_attach_is_idempotent_and_new_session_excludes_existing_history(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 110, 10)
        attach_token_usage(self.state)
        self.thread("continuation")
        self.event("continuation", 300, 300)
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "continuation"}):
            attach_token_usage(self.state)
        self.event("continuation", 304, 4)
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(14))

    def test_resume_after_handoff_excludes_intervening_conversation(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 110, 10)
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(10))
        self.event("root", 900, 790)
        attach_token_usage(self.state, resume=True)
        self.event("root", 907, 7)
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(17))

    def test_resume_in_different_session_freezes_previous_tree(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 110, 10)
        collect_token_usage(self.state)
        self.thread("continuation")
        self.event("continuation", 300, 300)
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "continuation"}):
            attach_token_usage(self.state, resume=True)
        self.event("root", 900, 790)
        self.thread("unrelated-later-child", "root")
        self.event("unrelated-later-child", 900, 900)
        self.event("continuation", 304, 4)
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(14))

    def test_missing_child_is_partial_and_missing_index_does_not_block(self):
        attach_token_usage(self.state, new_run=True)
        self.thread("child", "root")
        (self.home / "child").unlink()
        self.assertEqual(collect_token_usage(self.state)["status"], "partial")
        (self.home / "state_5.sqlite").unlink()
        report = collect_token_usage(self.state)
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["usage"])
        self.assertFalse((self.home / "state_5.sqlite").exists())

    def test_unavailable_baseline_is_never_replaced_with_lifetime_usage(self):
        (self.home / "root").unlink()
        attach_token_usage(self.state, new_run=True)
        self.write("root", {"type": "session_meta", "timestamp": "2026-09-15T10:00:00Z", "payload": {"id": "root"}})
        self.event("root", 900, 900)
        report = collect_token_usage(self.state)
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["usage"])

    def test_legacy_run_and_missing_environment_are_explicit(self):
        self.assertEqual(collect_token_usage({})["status"], "unavailable")
        attach_token_usage(self.state)
        self.event("root", 102, 2)
        self.assertEqual(collect_token_usage(self.state)["status"], "partial")
        with patch.dict(os.environ, {"CODEX_THREAD_ID": ""}):
            state = {}
            attach_token_usage(state, new_run=True)
            self.assertEqual(collect_token_usage(state)["status"], "unavailable")

    def test_partial_line_is_retried_and_malformed_log_is_partial(self):
        attach_token_usage(self.state, new_run=True)
        line = json.dumps({"type": "event_msg", "timestamp": "2026-09-15T11:00:00Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": counts(102), "last_token_usage": counts(2)},
        }})
        with (self.home / "root").open("a") as f:
            f.write(line[:30])
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(0))
        with (self.home / "root").open("a") as f:
            f.write(line[30:] + "\n")
        self.assertEqual(collect_token_usage(self.state)["usage"], counts(2))
        with (self.home / "root").open("a") as f:
            f.write("invalid json\n")
        self.assertEqual(collect_token_usage(self.state)["status"], "partial")

    def test_run_resumed_in_claude_code_sums_both_hosts(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 110, 10)
        collect_token_usage(self.state)
        project = self.home / "claude" / "projects" / "-repo"
        project.mkdir(parents=True)
        entry = {"type": "assistant", "timestamp": "2999-01-01T00:00:00Z", "message": {
            "id": "m1", "usage": {"input_tokens": 5, "cache_read_input_tokens": 3, "output_tokens": 2},
        }}
        (project / "claude-session.jsonl").write_text("")
        with patch.dict(os.environ, {
            "CODEX_THREAD_ID": "", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "claude-session",
            "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
        }):
            attach_token_usage(self.state, resume=True)
            self.assertEqual(self.state["tokenUsageTracking"]["startCheck"]["status"], "ready")
            (project / "claude-session.jsonl").write_text(json.dumps(entry) + "\n")
            self.event("root", 900, 790)
            report = collect_token_usage(self.state)
        self.assertEqual(report["scope"], "codex_session_tree+claude_session_tree")
        self.assertEqual(report["usage"]["input_tokens"], 90 + 8)
        self.assertEqual(report["usage"]["total_tokens"], 100 + 10)

    def test_counter_regression_is_not_silently_added(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 2, 2)
        self.assertEqual(collect_token_usage(self.state)["status"], "unavailable")


class ClaudeTokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.project = self.home / "projects" / "-repo"
        self.project.mkdir(parents=True)
        env = patch.dict(os.environ, {
            "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "main", "CLAUDE_CONFIG_DIR": str(self.home),
        })
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CODEX_THREAD_ID", None)
        self.state = {}
        self.message("main", "old", "2020-01-01T00:00:00Z", 1000)

    def message(self, session, key, stamp, output, *, subagent=None, blocks=1):
        path = self.project / f"{session}.jsonl"
        if subagent:
            path = self.project / session / "subagents" / f"agent-{subagent}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
        usage = {
            "input_tokens": 1, "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 100, "output_tokens": output,
        }
        with path.open("a") as f:
            f.write(json.dumps({"type": "user", "timestamp": stamp, "message": {"role": "user", "content": "x"}}) + "\n")
            for _ in range(blocks):
                f.write(json.dumps({"type": "assistant", "timestamp": stamp, "message": {"id": key, "usage": usage}}) + "\n")

    def usage(self, messages, output):
        return {
            "input_tokens": 111 * messages, "cached_input_tokens": 100 * messages,
            "output_tokens": output, "total_tokens": 111 * messages + output,
            "cache_creation_input_tokens": 10 * messages,
        }

    def test_start_check_is_ready_and_counts_run_messages_and_subagents_once(self):
        attach_token_usage(self.state, new_run=True)
        check = self.state["tokenUsageTracking"]["startCheck"]
        self.assertEqual((check["status"], check["harness"], check["sessionId"]), ("ready", "claude", "main"))
        self.message("main", "m1", "2999-01-01T00:00:00Z", 5, blocks=3)
        self.message("main", "m2", "2999-01-01T00:01:00Z", 7)
        self.message("main", "s1", "2999-01-01T00:02:00Z", 11, subagent="a")
        report = collect_token_usage(self.state)
        self.assertEqual((report["status"], report["scope"]), ("complete", "claude_session_tree"))
        self.assertEqual(report["usage"], self.usage(3, 23))

    def test_resume_excludes_conversation_between_handoff_and_resume(self):
        attach_token_usage(self.state, new_run=True)
        self.message("main", "m1", "2999-01-01T00:00:00Z", 5)
        collect_token_usage(self.state)
        self.state["tokenUsageTracking"]["claude"]["lastCollectedAt"] = "2999-01-01T00:00:30Z"
        self.message("main", "chat", "2999-01-01T00:01:00Z", 500)
        with patch("issue_delivery_orchestrator.token_usage._now", return_value="2999-01-01T00:02:00Z"):
            attach_token_usage(self.state, resume=True)
        self.message("main", "m2", "2999-01-01T00:03:00Z", 7)
        self.assertEqual(collect_token_usage(self.state)["usage"], self.usage(2, 12))

    def test_missing_log_is_reported_unavailable_at_start(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = "missing"
        attach_token_usage(self.state, new_run=True)
        check = self.state["tokenUsageTracking"]["startCheck"]
        self.assertEqual(check["status"], "unavailable")
        self.assertIn("Claude Code session log not found", check["issues"])
        self.assertEqual(collect_token_usage(self.state)["status"], "unavailable")

    def test_ambiguous_and_undetected_hosts_are_reported_at_start(self):
        for environment, issue in (
            ({"CODEX_THREAD_ID": "root"}, "Ambiguous session"),
            ({"CLAUDECODE": "", "CLAUDE_CODE_SESSION_ID": ""}, "No Codex or Claude Code session detected"),
        ):
            with self.subTest(issue=issue), patch.dict(os.environ, environment):
                state = {}
                attach_token_usage(state, new_run=True)
                check = state["tokenUsageTracking"]["startCheck"]
                self.assertEqual(check["status"], "unavailable")
                self.assertTrue(any(item.startswith(issue) for item in check["issues"]))

    def test_malformed_subagent_log_is_never_counted(self):
        attach_token_usage(self.state, new_run=True)
        self.message("main", "m1", "2999-01-01T00:00:00Z", 5)
        self.message("main", "s1", "2999-01-01T00:02:00Z", 11, subagent="a")
        with (self.project / "main" / "subagents" / "agent-a.jsonl").open("a") as f:
            f.write("invalid json\n")
        report = collect_token_usage(self.state)
        self.assertEqual(report["status"], "unavailable")
        attach_token_usage(self.state)
        self.assertEqual(self.state["tokenUsageTracking"]["startCheck"]["status"], "ready")

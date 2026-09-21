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
            issue={"identifier": "TS-1"}, branch="feature", base="development",
            created_from="origin/development", adopted_head="abc", identities={},
        )
        persisted = load_state(run_root(self.home / "worktree", "test-run") / "state.json")
        self.assertEqual(persisted["tokenUsageTracking"]["roots"], ["root"])
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

    def test_counter_regression_is_not_silently_added(self):
        attach_token_usage(self.state, new_run=True)
        self.event("root", 2, 2)
        self.assertEqual(collect_token_usage(self.state)["status"], "unavailable")

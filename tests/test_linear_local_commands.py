from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LINEAR_CLI_PATH = ROOT / "skills" / "linear-local" / "scripts" / "linear_cli.py"


def description(spec: str, tickets: str) -> str:
    return (
        "Contexto de la issue.\n\n"
        f"<!-- turboshop:spec:start -->\n{spec}\n<!-- turboshop:spec:end -->\n\n"
        f"<!-- turboshop:tickets:start -->\n{tickets}\n<!-- turboshop:tickets:end -->\n"
    )


class LinearLocalCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("issue_delivery_test_linear_commands", LINEAR_CLI_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load bundled codex-linear implementation")
        cls.cli = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.cli
        spec.loader.exec_module(cls.cli)
        cls.credential = cls.cli.Credential("token", "environment", "dev@example.com", "")

    def test_spec_digest_covers_spec_and_tickets_and_ignores_the_rest(self) -> None:
        base = self.cli.spec_digest(description("Spec ID: SPEC-1", "Ticket ID: TICKET-001"), "turboshop")
        self.assertTrue(base["specPresent"] and base["ticketsPresent"])
        self.assertRegex(base["specHash"], r"^[0-9a-f]{64}$")

        outside = self.cli.spec_digest(
            "Otro contexto.\n" + description("Spec ID: SPEC-1", "Ticket ID: TICKET-001"), "turboshop"
        )
        self.assertEqual(base["specHash"], outside["specHash"])

        changed = self.cli.spec_digest(description("Spec ID: SPEC-1", "Ticket ID: TICKET-002"), "turboshop")
        self.assertNotEqual(base["specHash"], changed["specHash"])

    def test_spec_digest_requires_published_tickets(self) -> None:
        pending = self.cli.spec_digest(
            description("Spec ID: SPEC-1", "<!-- Tickets pending. -->"), "turboshop"
        )
        self.assertEqual(
            {"specPresent": True, "ticketsPresent": False, "specHash": None}, pending
        )

    def test_spec_approval_matches_only_the_current_hash(self) -> None:
        current = "a" * 64
        previous = "b" * 64
        comments = [
            {"id": "old", "body": self.cli.spec_approval_marker("turboshop", previous)},
            {"id": "new", "url": "u", "createdAt": "t", "body": "ok\n" + self.cli.spec_approval_marker("turboshop", current)},
            {"id": "other-prefix", "body": self.cli.spec_approval_marker("other", current)},
        ]
        found = self.cli.find_spec_approval(comments, "turboshop", current)
        self.assertEqual("new", found["approval"]["id"])
        self.assertEqual([previous], found["otherApprovedHashes"])
        self.assertIsNone(self.cli.find_spec_approval(comments, "turboshop", None)["approval"])

    def test_project_reference_accepts_url_slug_and_name(self) -> None:
        project = {"id": "p", "slugId": "48556f3ac394", "name": "Parque"}
        calls = []

        def graphql(_credential, query, variables):
            calls.append((query, variables))
            if "projects(" in query:
                return {"projects": {"nodes": [project]}}
            return {"project": project}

        with patch.object(self.cli, "_graphql", side_effect=graphql):
            self.cli._project(
                self.credential,
                "https://linear.app/acme/project/parque-automotriz-48556f3ac394/overview",
            )
            self.cli._project(self.credential, "48556F3AC394")
            self.cli._project(self.credential, "Parque")

        self.assertEqual({"id": "48556f3ac394"}, calls[0][1])
        self.assertEqual({"id": "48556f3ac394"}, calls[1][1])
        self.assertEqual({"name": "Parque"}, calls[2][1])

    def test_issue_update_prefers_team_labels_and_verifies_the_result(self) -> None:
        issue = {
            "id": "issue-id",
            "identifier": "PRO-1",
            "team": {"id": "team-id", "key": "PRO", "name": "Productos"},
            "state": {"name": "Todo"},
            "labels": {"nodes": []},
        }
        updated = {**issue, "state": {"name": "In Progress"}, "labels": {"nodes": [{"name": "needs-decision"}]}}
        mutations = []

        def graphql(_credential, query, variables):
            if "CodexLinearViewer" in query:
                return {
                    "viewer": {"id": "u", "email": "dev@example.com"},
                    "organization": {"urlKey": "acme"},
                }
            if "CodexLinearIssue(" in query:
                return {"issue": updated if mutations else issue}
            if "CodexLinearTeams" in query:
                return {"teams": {"nodes": [{
                    "id": "team-id", "key": "PRO", "name": "Productos",
                    "states": {"nodes": [{"id": "progress", "name": "In Progress"}]},
                }]}}
            if "CodexLinearLabels" in query:
                return {"issueLabels": {"nodes": [
                    {"id": "workspace-label", "name": "needs-decision", "team": None},
                    {"id": "team-label", "name": "needs-decision", "team": {"id": "team-id"}},
                ]}}
            mutations.append(variables)
            return {"issueUpdate": {"success": True}}

        args = argparse.Namespace(
            issue="PRO-1", state="in progress", add_label=["needs-decision"],
            remove_label=[], project=None, milestone=None, parent=None, blocked_by=[],
        )
        with patch.object(self.cli, "_graphql", side_effect=graphql):
            result = self.cli._issue_update(args, self.credential)

        self.assertEqual("PRO-1", result["identifier"])
        self.assertEqual(
            {"stateId": "progress", "addedLabelIds": ["team-label"]}, mutations[0]["input"]
        )

        mutations.clear()
        updated = {**issue}
        with patch.object(self.cli, "_graphql", side_effect=graphql):
            with self.assertRaisesRegex(self.cli.LinearCliError, "did not move"):
                self.cli._issue_update(args, self.credential)

    def test_milestones_resolve_by_name_in_the_issue_project(self) -> None:
        issue = {
            "id": "issue-id",
            "identifier": "PRO-1",
            "team": {"id": "team-id", "key": "PRO", "name": "Productos"},
            "project": {"id": "project-id", "name": "Inventario"},
            "projectMilestone": None,
            "labels": {"nodes": []},
        }
        milestones = [
            {"id": "m2", "name": "Etapa 2 · Consumo", "sortOrder": 2},
            {"id": "m1", "name": "Etapa 1 · Bodega base", "sortOrder": 1},
        ]
        mutations = []

        def graphql(_credential, query, variables):
            if "CodexLinearViewer" in query:
                return {"viewer": {"id": "u", "email": "dev@example.com"}, "organization": {"urlKey": "acme"}}
            if "CodexLinearIssue(" in query:
                return {"issue": {**issue, "projectMilestone": {"name": "Etapa 1 · Bodega base"}} if mutations else issue}
            if "CodexLinearProjectMilestones" in query:
                return {"project": {"projectMilestones": {"nodes": milestones, "pageInfo": {}}}}
            if "CodexLinearProjectByName" in query:
                return {"projects": {"nodes": [{"id": "project-id", "slugId": "abc", "name": "Inventario", "url": "u"}]}}
            mutations.append(variables)
            return {"issueUpdate": {"success": True}}

        args = argparse.Namespace(
            issue="PRO-1", state=None, add_label=[], remove_label=[], project=None,
            milestone="etapa 1 · bodega base", parent=None, blocked_by=[],
        )
        with patch.object(self.cli, "_graphql", side_effect=graphql):
            self.cli._issue_update(args, self.credential)
            listed = self.cli._project_milestone_list(argparse.Namespace(project="Inventario"), self.credential)
            with self.assertRaisesRegex(self.cli.LinearCliError, "already has a milestone"):
                self.cli._project_milestone_create(
                    argparse.Namespace(project="Inventario", name="Etapa 2 · Consumo", description_file=None),
                    self.credential,
                )

        self.assertEqual({"projectMilestoneId": "m1"}, mutations[0]["input"])
        self.assertEqual(["m1", "m2"], [milestone["id"] for milestone in listed["milestones"]])


if __name__ == "__main__":
    unittest.main()

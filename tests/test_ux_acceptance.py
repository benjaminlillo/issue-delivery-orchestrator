import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.ux_acceptance import (
    assert_acceptance_verified,
    required_acceptance_ids,
)

SPEC = """Spec ID: SPEC-PRO-1

# Tarifas

## User Stories
- US-001: As a manager, I want rates, so that I can price work. Mentions UX-999 in prose.

## User Experience Acceptance

### Behavior
| ID | Story | Context | Action | Expected result |
| --- | --- | --- | --- | --- |
| UX-001 | US-001 | Sin tarifas | Abre Tarifas | Ve estado vacío |
| UX-002 | US-001 | Con tarifas | Guarda | Ve confirmación |

### Design
| ID | Screen | Decision | Design source |
| --- | --- | --- | --- |
| UXD-001 | Detalle | Pestaña Tarifas | Consistency: pestañas hermanas de Detalle |

## Implementation Decisions
| UX-777 | not part of the section |
"""


class UxAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worktree = Path(self.tmp.name)
        (self.worktree / "spec.md").write_text(SPEC)
        self.state = {"worktree": str(self.worktree), "artifacts": {"spec": "spec.md"}}

    def verification(self, **overrides):
        results = {key: {"id": key, "status": "PASS", "evidence": "US-1/final.png"}
                   for key in ("UX-001", "UX-002", "UXD-001")}
        results.update(overrides)
        return {"acceptance": list(results.values())}

    def test_reads_only_rows_of_the_acceptance_section(self):
        self.assertEqual(required_acceptance_ids(self.state), ["UX-001", "UX-002", "UXD-001"])

    def test_every_criterion_must_pass_with_evidence(self):
        assert_acceptance_verified(self.state, self.verification())
        for overrides, message in (
            ({"UX-002": {"id": "UX-002", "status": "FAIL", "evidence": "x"}}, "not PASS: UX-002"),
            ({"UXD-001": {"id": "UXD-001", "status": "PASS", "evidence": ""}}, "without evidence: UXD-001"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(RunBlocked, message):
                assert_acceptance_verified(self.state, self.verification(**overrides))
        with self.assertRaisesRegex(RunBlocked, "not verified: UX-001, UX-002, UXD-001"):
            assert_acceptance_verified(self.state, {})

    def test_specs_and_runs_without_the_section_keep_working(self):
        (self.worktree / "legacy.md").write_text("# Legacy\n\n## User Stories\n- US-001\n")
        assert_acceptance_verified({**self.state, "artifacts": {"spec": "legacy.md"}}, {})
        assert_acceptance_verified({**self.state, "artifacts": {}}, {})


if __name__ == "__main__":
    unittest.main()

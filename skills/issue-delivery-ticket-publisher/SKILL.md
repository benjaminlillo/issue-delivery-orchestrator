---
name: issue-delivery-ticket-publisher
description: Slice an approved Issue Delivery Orchestrator spec into implementation tickets, obtain approval, and publish them into the canonical Linear tickets block.
---

# Issue Delivery Ticket Publisher

Own ticket slicing, AFK/HITL classification, dependencies, approval and Linear publication. Use the
approved canonical spec as the only source of product scope.

## Required input

- Linear issue with a non-empty canonical spec block.
- Effective `linear_marker_prefix` from
  `python3 <plugin-root>/scripts/issue-delivery config`.
- Applicable repository instructions and existing validation conventions.

## Ticket format

Each ticket must use:

```md
Ticket ID: TICKET-001
Parent Spec: SPEC-...
Status: Pending
Type: AFK | HITL
UI Changes: Yes | No
Blocked by:
- None

# Ticket title

## What to build
...

## Current Value — YAGNI
...

## Public Surface Delta
...

## Deep Modules
...

## Coverage Delta
...

## Not Building — YAGNI
...

## Acceptance Criteria
- [ ] ...

## User Stories Covered
- US-...

## Validation
- Run: `...`

## Implementation Notes
...
```

For `Type: HITL`, insert `## HITL Justification` before Acceptance Criteria with the autonomy
blocker, why available computer use cannot complete it, and the minimum human action required.
Use HITL only for a real authority, credential, physical-world or unavailable-surface dependency,
not because implementation is difficult.

## Slicing and approval

1. Read the spec, repository instructions and existing validation seams.
2. Produce the smallest independently committable tickets that preserve dependency order.
3. Cover every `Now` requirement and user story exactly where it is implemented; do not turn the
   fixed final UI-review phase into an implementation ticket.
4. Preserve the spec's `Architecture Constraints`. Reference the constraints relevant to each
   ticket in `Implementation Notes`; do not reinterpret, weaken or duplicate them as new scope.
5. Use unique sequential IDs, valid dependency references and at least one focused validation
   command per AFK ticket.
6. Present the complete breakdown and obtain explicit approval before publishing.
7. Immediately call out every HITL ticket with ID, title, reason, required action, dependencies and
   approximate pause point.

## Publication contract

For prefix `<prefix>`, replace only:

```md
<!-- <prefix>:tickets:start -->
...
<!-- <prefix>:tickets:end -->
```

Preserve the spec block and all unrelated description content. Before operating with Linear:

1. Resolve `<plugin-root>` as the directory containing `.codex-plugin/plugin.json` and invoke the
   bundled `$linear-local` skill. If `codex-linear` is not already available, prepend
   `<plugin-root>/bin` to `PATH`. Fail explicitly if either the skill or command is unavailable;
   never continue with another identity or transport.
2. Run `codex-linear doctor` and read the issue exclusively with
   `codex-linear issue get <issue>`.
3. Write the complete candidate description to a file inside the ignored run directory and publish
   it exclusively with
   `codex-linear issue update-description <issue> --description-file <path>`.
4. Read the issue again with `codex-linear issue get <issue>` and verify that only the canonical
   tickets block changed, while the spec block and all unrelated content remained byte-for-byte
   unchanged.
5. Write the approved ticket publication note to a file inside the ignored run directory and post
   it exclusively with `codex-linear comment create <issue> --body-file <path>`, listing the
   published ticket IDs.

Do not use a Linear connector, Linear MCP, direct API call, or browser automation as a fallback.
Any `$linear-local`, `codex-linear doctor`, read, mutation, re-read, verification, or comment
failure is blocking. Do not alter `AGENTS.md` or create a repository copy.

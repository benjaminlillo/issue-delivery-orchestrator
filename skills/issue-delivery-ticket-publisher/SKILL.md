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
4. Use unique sequential IDs, valid dependency references and at least one focused validation
   command per AFK ticket.
5. Present the complete breakdown and obtain explicit approval before publishing.
6. Immediately call out every HITL ticket with ID, title, reason, required action, dependencies and
   approximate pause point.

## Publication contract

For prefix `<prefix>`, replace only:

```md
<!-- <prefix>:tickets:start -->
...
<!-- <prefix>:tickets:end -->
```

Preserve the spec block and all unrelated description content. Update Linear through the Linear
connector, read it back, verify the exact block and post a short comment listing published ticket
IDs. Do not alter `AGENTS.md` or create a repository copy.

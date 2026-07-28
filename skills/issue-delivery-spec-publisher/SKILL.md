---
name: issue-delivery-spec-publisher
description: Publish an approved Issue Delivery Orchestrator spec into its canonical Linear description block while preserving tickets and unrelated issue content.
---

# Issue Delivery Spec Publisher

Own only the Linear destination and format contract. The approved spec body must come from
`$issue-delivery-grill`; do not rewrite architecture or scope while publishing.

## Required input

- Linear issue ID, identifier, URL, or unambiguous current issue.
- The explicitly approved canonical spec body.
- The effective `linear_marker_prefix` from
  `python3 <plugin-root>/scripts/issue-delivery config`.

## Destination contract

For a prefix `<prefix>`, write the spec only between:

```md
<!-- <prefix>:spec:start -->
...
<!-- <prefix>:spec:end -->
```

Preserve all content outside the orchestrator blocks. If no tickets markers exist, initialize:

```md
<!-- <prefix>:tickets:start -->
<!-- Tickets pending. Run $issue-delivery-ticket-publisher after approving the breakdown. -->
<!-- <prefix>:tickets:end -->
```

## Validation

Before publishing, require a non-empty `Spec ID`, title, and exactly one occurrence of every
canonical heading in the order produced by `$issue-delivery-grill`. Require the exact
`Testing Decisions` table header. Reject placeholders and unresolved material decisions.

## Workflow

1. Read the Linear issue and preserve its current description.
2. Validate the already approved spec without changing its decisions.
3. Replace only the canonical spec block; initialize only a missing tickets block.
4. Update Linear through the Linear connector.
5. Read the issue again and verify markers, body, preserved tickets and unrelated content.
6. Post a short Linear comment identifying the published Spec ID.

Do not write a repository copy, alter `AGENTS.md`, expose secrets, or publish without explicit user
approval. Report the issue, Spec ID and which blocks were updated or initialized.

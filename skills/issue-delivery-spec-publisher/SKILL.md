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
`Architecture Constraints` and `Testing Decisions` table headers. Require every material
architecture row to name its source, applicability and Refactor verification. Reject placeholders,
unresolved material decisions and silent conflicts with an applicable repository source.

## Workflow

1. Resolve `<plugin-root>` as the directory containing `.codex-plugin/plugin.json`. Invoke the
   bundled `$linear-local` skill. If `codex-linear` is not already available, prepend
   `<plugin-root>/bin` to `PATH`. Fail explicitly if either the skill or command is unavailable;
   never continue with another identity or transport.
2. Run `codex-linear doctor`, then read the issue exclusively with
   `codex-linear issue get <issue>`. Preserve its current description.
3. Validate the already approved spec without changing its decisions.
4. Replace only the canonical spec block; initialize only a missing tickets block.
5. Write the complete candidate description to a file inside the ignored run directory and update
   Linear exclusively with
   `codex-linear issue update-description <issue> --description-file <path>`.
6. Read the issue again with `codex-linear issue get <issue>` and verify that only the canonical
   spec block changed, the tickets block was preserved or initialized as approved, and all
   unrelated content remained byte-for-byte unchanged.
7. Write the approved publication note to a file inside the ignored run directory and post it
   exclusively with `codex-linear comment create <issue> --body-file <path>`, identifying the
   published Spec ID.

Do not write a repository copy, alter `AGENTS.md`, expose secrets, or publish without explicit user
approval. Do not use a Linear connector, Linear MCP, direct API call, or browser automation as a
fallback. Any `$linear-local`, `codex-linear doctor`, read, mutation, re-read, verification, or
comment failure is blocking. Report the issue, Spec ID and which blocks were updated or initialized.

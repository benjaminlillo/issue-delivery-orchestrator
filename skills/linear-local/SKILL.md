---
name: linear-local
description: Access Linear through the local codex-linear CLI using LINEAR_API_KEY from the environment and the expected user and workspace. Use for every Linear read or mutation performed by a skill, including reading, creating, assigning, updating, or commenting on issues and generating reports from Linear data. Never use a Linear MCP or expose the API key.
---

# Linear Local

Use the local `codex-linear` command for every Linear operation. Do not use a
Linear MCP, browser automation, or direct HTTP calls. Do not read or handle
`LINEAR_API_KEY` yourself; only the bundled CLI may consume it.

This plugin bundles the command under `<plugin-root>/bin/codex-linear`. If no
`codex-linear` is already available, prepend `<plugin-root>/bin` to `PATH`
for the current task. Fail explicitly if the bundled skill or command cannot be
loaded; never substitute a connector, MCP, browser, direct API call, or another
identity.

## Safety contract

- Let the CLI read `LINEAR_API_KEY`, `LINEAR_EXPECTED_EMAIL` and the optional
  `LINEAR_EXPECTED_WORKSPACE` from the process environment. It may populate those variables from the user-owned
  `~/.config/issue-delivery-orchestrator/.env`; it must never load credentials
  from the product repository or worktree.
- Never print, log, persist, request, or pass the API key as an argument.
- Require the expected identity before every normal Linear read or mutation. The
  CLI checks automatically that the key's user has `LINEAR_EXPECTED_EMAIL` and,
  when configured, belongs to `LINEAR_EXPECTED_WORKSPACE`, and fails closed
  otherwise. Only `whoami` may inspect a credential without this check.
- Use the authenticated viewer ID explicitly for self-assignment.
- Treat GraphQL responses containing `errors` as failures even when HTTP is 200.
- Re-read mutated issues and verify their observable final state.

## Commands

```bash
codex-linear doctor
codex-linear whoami
codex-linear team get "Software"
codex-linear issue get SFW-123
codex-linear issue create \
  --team "Software" \
  --state "Triage" \
  --title "Título" \
  --description-file /absolute/path/description.md \
  --estimate 4 \
  --assign-viewer
codex-linear issue update-description SFW-123 \
  --description-file /absolute/path/description.md
codex-linear issue update SFW-123 --state "In Progress" \
  --add-label needs-decision --remove-label ready-for-agent \
  --project "<project>" --milestone "<milestone>" --parent SFW-100 --blocked-by SFW-120
codex-linear issue spec-approval SFW-123 --prefix turboshop
codex-linear comment create SFW-123 --body-file /absolute/path/comment.md
codex-linear comment list SFW-123
codex-linear project get "<project name, URL, slug ID or ID>"
codex-linear project issues "<project>"
codex-linear project update-content "<project>" \
  --content-file /absolute/path/content.md
codex-linear project milestones "<project>"
codex-linear project milestone-create "<project>" --name "<name>" \
  --description-file /absolute/path/milestone.md
codex-linear project milestone-update "<project>" "<milestone>" \
  --name "<new name>" --description-file /absolute/path/milestone.md
codex-linear request --file /absolute/path/graphql-request.json
```

`issue update` resolves the state in the issue's team and each label in the
issue's team first, then at workspace level, and re-reads the issue to verify
the result. `project issues` returns each issue with its state, labels,
`blocks` and `blockedBy`. `project update-content` replaces the long
description shown in the project overview; `description` in the JSON is the
short summary. Milestones are resolved by exact name, ignoring case, inside the
project; `issue update --milestone` uses `--project` when given and the issue's
own project otherwise. `project milestone-create` refuses a name the project
already has.

`issue spec-approval` hashes the text between the canonical `spec` and
`tickets` markers of the given prefix, exactly as Linear stores it, and looks
for a comment containing the matching `approvalMarker`. It returns
`approved: true` only when both blocks have content and an approval comment
carries the current hash. A changed spec or ticket breakdown needs a new
approval comment.

Use `request --file` only for operations not covered by a dedicated command. The
file must contain `{"query": "...", "variables": {...}}`. Mutations remain
identity-guarded.

## Workflow

1. Run `codex-linear doctor` before the first Linear operation in a task.
2. Resolve teams, states, issue IDs, and user IDs through reads; do not guess IDs.
3. Prefer dedicated commands for issue and comment operations.
4. For a mutation, inspect the returned JSON and then re-read the affected issue.
5. Stop on credential, identity, GraphQL, or verification failures. Do not fall
   back to another Linear integration.

## Resource

- `scripts/linear_cli.py`: environment-backed, identity-guarded Linear CLI.

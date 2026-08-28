---
name: linear-local
description: Access Linear through the local codex-linear CLI using LINEAR_API_KEY from the environment and a pinned user identity. Use for every Linear read or mutation performed by a skill, including reading, creating, assigning, updating, or commenting on issues and generating reports from Linear data. Never use a Linear MCP or expose the API key.
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

- Let the CLI read `LINEAR_API_KEY` and `LINEAR_EXPECTED_EMAIL` from the process
  environment. It may populate those variables from the user-owned
  `~/.config/issue-delivery-orchestrator/.env`; it must never load credentials
  from the product repository or worktree.
- Never print, log, persist, request, or pass the API key as an argument.
- Require a pinned identity before every normal Linear read or mutation. The CLI
  performs this check automatically and fails closed when the authenticated user
  changes. Only `whoami` and `identity` may inspect an unpinned credential.
- Use the authenticated viewer ID explicitly for self-assignment.
- Treat GraphQL responses containing `errors` as failures even when HTTP is 200.
- Re-read mutated issues and verify their observable final state.

## Commands

```bash
codex-linear doctor
codex-linear whoami
codex-linear identity status
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
codex-linear comment create SFW-123 --body-file /absolute/path/comment.md
codex-linear request --file /absolute/path/graphql-request.json
```

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

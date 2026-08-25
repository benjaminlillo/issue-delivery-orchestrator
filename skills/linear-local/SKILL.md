---
name: linear-local
description: Access Linear through the local codex-linear CLI using a personal API key stored in macOS Keychain and a pinned user identity. Use for every Linear read or mutation performed by a skill, including reading, creating, assigning, updating, or commenting on issues and generating reports from Linear data. Never use a Linear MCP or expose the API key.
---

# Linear Local

Use the local `codex-linear` command for every Linear operation. Do not use a
Linear MCP, browser automation, direct HTTP calls, or `LINEAR_API_KEY`.

This plugin bundles the command under `<plugin-root>/bin/codex-linear`. If no
`codex-linear` is already available, prepend `<plugin-root>/bin` to `PATH`
for the current task. Fail explicitly if the bundled skill or command cannot be
loaded; never substitute a connector, MCP, browser, direct API call, or another
identity.

## Safety contract

- Read the API key only through the CLI; never invoke `security` directly.
- Read `LINEAR_EXPECTED_EMAIL` and optional `LINEAR_KEYCHAIN_SERVICE` from
  the environment or `~/.config/issue-delivery-orchestrator/.env`. The CLI
  never reads `LINEAR_API_KEY`.
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

- `scripts/linear_cli.py`: Keychain-backed Linear CLI implementation.

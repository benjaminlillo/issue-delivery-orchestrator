# Issue Delivery Orchestrator

A Codex plugin for taking a Linear issue through specification, ticket slicing, implementation,
focused validation, manual UI review, pull request creation, and automated review convergence.

The plugin is self-contained: its orchestration engine and workflow skills live in this repository.
It supports two fixed workspace modes:

- `codex`: work in a Codex app worktree and review UI through the in-app Browser.
- `superset`: adopt a Superset worktree and review UI through Cua Driver in a dedicated browser.

## Included skills

- `$issue-delivery-orchestrator`
- `$issue-delivery-grill`
- `$issue-delivery-spec-publisher`
- `$issue-delivery-ticket-publisher`
- `$issue-delivery-implement`
- `$issue-delivery-blocker-triage`
- `$issue-delivery-cua-review`
- `$issue-delivery-browser-review`

The Browser skill, Linear connector, Figma connector, GitHub CLI, Cua Driver, and the target
repository's runtime commands remain environment capabilities. The orchestrator checks them only
when the selected flow needs them.

## Configure

Copy `.env.example` to:

```text
~/.config/issue-delivery-orchestrator/.env
```

At minimum, configure:

```dotenv
LINEAR_API_KEY=lin_api_...
LINEAR_EXPECTED_EMAIL=you@example.com
GITHUB_EXPECTED_LOGIN=your-github-login
ISSUE_DELIVERY_REPOSITORY=/absolute/path/to/repository
```

The `.env` is user-owned and must not be committed. On macOS, `LINEAR_API_KEY` can instead live in
Keychain under the configured service and `LINEAR_EXPECTED_EMAIL` account. Existing `gh`
authentication is used for GitHub, and its login must match `GITHUB_EXPECTED_LOGIN`.

Inspect the effective non-secret configuration:

```bash
python3 scripts/issue-delivery config
```

The default profile is [`profiles/turboshop.json`](profiles/turboshop.json). Point
`ISSUE_DELIVERY_PROFILE` at another JSON profile to adapt base/target branches, Local Runtime
commands, review bots, evidence branch, and Linear markers without changing the engine.

## Start a run

Install or load this repository as a Codex plugin, open a session in the intended worktree, and
invoke `$issue-delivery-orchestrator` with a Linear issue. The skill will select and preserve either
Codex or Superset mode for the complete run.

The deterministic engine can also be inspected directly:

```bash
python3 scripts/issue-delivery --help
```

All run memory, receipts, logs, screenshots, and browser profiles are written under the ignored
runtime directory inside the adopted worktree. Product commits contain only product changes.

## Development

```bash
corepack pnpm test
```

The project requires Python 3.9+ and has no runtime Python package dependencies.

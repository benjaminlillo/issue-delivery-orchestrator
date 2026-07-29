# Issue Delivery Orchestrator

A Codex plugin for taking a Linear issue through specification, ticket slicing, implementation,
focused validation, manual UI review, pull request creation, and automated review convergence.

The plugin is self-contained: its orchestration engine and workflow skills live in this repository.
It supports two fixed workspace modes:

- `codex`: work in a Codex app worktree and review UI through the in-app Browser.
- `superset`: adopt a Superset worktree and review UI through Cua Driver in a dedicated browser.

The orchestrator never creates a worktree. Start the chat in a worktree prepared by Codex or
Superset so that surface can run its local setup. A new run cleans tracked changes and untracked,
non-ignored files before adoption while preserving ignored `.env`, dependency, and runtime files.
Existing runs are never cleaned when resumed.

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

## Install

### Prerequisites

- Codex CLI with plugin support.
- Git and GitHub CLI (`gh`) authenticated with access to this private repository.
- Python 3.9 or newer.
- Node.js with Corepack/pnpm for the bundled test command and the default TurboShop runtime profile.

If HTTPS Git credentials are not already configured:

```bash
gh auth login
gh auth setup-git
```

### Install with Codex CLI

Add this repository as a marketplace and install the plugin from it:

```bash
codex plugin marketplace add benjaminlillo/issue-delivery-orchestrator --ref main
codex plugin add issue-delivery-orchestrator@issue-delivery-orchestrator
```

Confirm that Codex can see the installed entry:

```bash
codex plugin list
```

Then start a **new** Codex CLI session so its bundled skills are loaded:

```bash
codex
```

Inside Codex, run `/plugins` to inspect the installation and make sure
`issue-delivery-orchestrator` is enabled. The plugin is then available as
`$issue-delivery-orchestrator`.

### Install in the Codex desktop app

Run the marketplace command above once, restart the desktop app, select **Codex**, and open
**Plugins**. Choose the **Issue Delivery Orchestrator** marketplace, install the plugin with the
plus button, and start a new chat. Local and repository marketplaces are supported in Codex and
the ChatGPT desktop app, but not in the IDE extension.

### Update

Refresh the Git marketplace snapshot and reinstall the current plugin version:

```bash
codex plugin marketplace upgrade issue-delivery-orchestrator
codex plugin add issue-delivery-orchestrator@issue-delivery-orchestrator
```

Start a new CLI session or desktop chat after updating. Published plugin changes should increment
the version in `.codex-plugin/plugin.json` so Codex does not reuse an older cached bundle.

These steps follow the official
[Codex plugin packaging](https://developers.openai.com/plugins/build/plugins) and
[plugin usage](https://learn.chatgpt.com/docs/plugins) guidance.

## Configure

Create the per-user configuration file:

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

New runs detect their mode from `SUPERSET_WORKSPACE_PATH`, configured worktree roots, or
unambiguous path components such as `.codex` and `superset-worktrees`. Configure custom roots when
your tools use paths without those markers. Separate multiple roots with the operating system path
separator (`:` on macOS/Linux and `;` on Windows):

```dotenv
ISSUE_DELIVERY_CODEX_WORKTREE_ROOTS=/absolute/path/to/codex/worktrees
ISSUE_DELIVERY_SUPERSET_WORKTREE_ROOTS=/absolute/path/to/superset/worktrees
```

An explicit `modo codex` or `modo superset` instruction overrides detection. If detection is
missing or contradictory, the loop asks for a mode instead of choosing a default.

The `.env` is user-owned and must not be committed. On macOS, `LINEAR_API_KEY` can instead live in
Keychain under the configured service and `LINEAR_EXPECTED_EMAIL` account. Existing `gh`
authentication is used for GitHub, and its login must match `GITHUB_EXPECTED_LOGIN`.

From a clone of this repository, inspect the effective non-secret configuration:

```bash
python3 scripts/issue-delivery config
```

The default profile is [`profiles/turboshop.json`](profiles/turboshop.json). Point
`ISSUE_DELIVERY_PROFILE` at another JSON profile to adapt base/target branches, Local Runtime
commands, review bots, evidence branch, and Linear markers without changing the engine.

## Start a run

Open a new Codex session in the intended product worktree and invoke
`$issue-delivery-orchestrator` with a Linear issue. The skill will select and preserve either Codex
or Superset mode for the complete run.

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

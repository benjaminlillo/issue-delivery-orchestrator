# Issue Delivery Orchestrator

A Codex plugin for taking a Linear issue through specification, ticket slicing, implementation,
focused validation, manual UI review, pull request creation, and automated review convergence.

Grill extracts the applicable architectural constraints from repository instructions, accepted
ADRs, context maps, and domain documentation into the approved spec. Refactor begins with a
conformance gate against that contract, repairing branch-caused violations and pausing for a user
decision when the spec or sources conflict.

The default `full` delivery target runs that complete flow. An explicit `manual-runtime` target
stops after implementation, refactor, and target-branch integration so the user can review the UI
and prepare the PR manually. Both targets finish by stopping the runtime used during work or
Computer Use, replacing it with a fresh isolated Local Runtime, restarting the required apps, and
leaving their healthy URLs available for user testing.

The plugin is self-contained: its orchestration engine and workflow skills live in this repository.
It supports four fixed workspace modes:

- `codex`: work in a Codex app worktree and review UI through the in-app Browser, with headless
  Playwright assistance limited to demonstrated `file-upload` or `hover` capability gaps.
- `superset`: adopt a Superset worktree and review UI through Cua Driver in a dedicated browser.
- `vanilla`: adopt any user-prepared checkout or worktree from Codex CLI, without depending on a
  workspace host, and review UI through Cua Driver.
- `conductor-cloud`: adopt the workspace created by Conductor Cloud and review UI headlessly through
  the target repository's existing Playwright installation and the workspace's system Chrome.

The orchestrator never creates a worktree. Start the session in a worktree prepared by Codex,
Superset, Conductor Cloud, or the user's normal Git tooling. Unless the prompt explicitly requests
another source, prepare it from `development`. Vanilla users must run the repository's local setup
before starting the loop. A new run cleans tracked changes and untracked, non-ignored files before
adoption while preserving ignored `.env`, dependency, and runtime files. Existing runs are never
cleaned when resumed.

New runs use `development` as their base branch and `test` as their pull-request target. A different
base or target must be explicitly requested and is then persisted for the whole run; GitHub's
default branch is never used implicitly.

New pull requests are created as drafts and remain drafts through automated review convergence
and handoff. Existing pull requests retain their draft/ready state when reused. The user decides
when to mark a PR ready for review; all existing review and validation requirements still apply.

## Included skills

- `$issue-delivery-orchestrator`
- `$issue-delivery-grill`
- `$issue-delivery-spec-publisher`
- `$issue-delivery-ticket-publisher`
- `$issue-delivery-implement`
- `$issue-delivery-blocker-triage`
- `$issue-delivery-cua-review`
- `$issue-delivery-browser-review`
- `$issue-delivery-playwright-review`
- `$linear-local`

The Browser skill, Figma connector, GitHub CLI, Cua Driver, Playwright, and the target repository's
runtime commands remain environment capabilities. Linear publication uses only the bundled
`$linear-local` skill and `codex-linear` CLI. The orchestrator checks capabilities only when the
selected flow needs them. Playwright is required in the target repository only when a story hits a
supported primary-reviewer capability gap; the plugin does not install or add it to product code.

## Install

### Prerequisites

- Codex CLI with plugin support.
- Git and GitHub CLI (`gh`) authenticated with access to this private repository.
- Python 3.9 or newer.
- Node.js with Corepack/pnpm for the bundled test command and the default TurboShop runtime profile.
- Cua Driver and its operating-system permissions for Superset or Vanilla UI review.
- For Conductor Cloud full delivery, Google Chrome in the workspace and Playwright already present
  in the target repository. The plugin does not install either into product code.
- macOS `sips`, ImageMagick, or ffmpeg when a reviewer returns JPEG bytes under a `.png` filename.
- A personal Linear API key exposed as `LINEAR_API_KEY`. Linear publication fails closed if the
  variable is unavailable or the pinned identity does not match.

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

New runs first detect Conductor Cloud from its official `CONDUCTOR_IS_LOCAL=0`,
`CONDUCTOR_API_URL`, and matching `CONDUCTOR_WORKSPACE_PATH`/`CONDUCTOR_ROOT_PATH` variables. They
otherwise detect mode from `SUPERSET_WORKSPACE_PATH`, configured worktree roots, or unambiguous
path components such as `.codex` and `superset-worktrees`. Configure custom roots when
your tools use paths without those markers. Separate multiple roots with the operating system path
separator (`:` on macOS/Linux and `;` on Windows):

```dotenv
ISSUE_DELIVERY_CODEX_WORKTREE_ROOTS=/absolute/path/to/codex/worktrees
ISSUE_DELIVERY_SUPERSET_WORKTREE_ROOTS=/absolute/path/to/superset/worktrees
```

An explicit mode always overrides detection. If no Codex, Superset, or Conductor Cloud signal matches, the loop
selects Vanilla with `modeSource: vanilla-fallback`. A fallback Vanilla run requires a clean
checkout and blocks before discarding local changes; selecting `modo vanilla` explicitly retains
the normal new-run cleanup contract. Contradictory workspace signals still require an explicit
choice.

The `.env` is user-owned and must not be committed. Restrict it to the current user:

```bash
chmod 600 ~/.config/issue-delivery-orchestrator/.env
```

Both the deterministic engine and bundled `codex-linear` command consume `LINEAR_API_KEY` only
from their process environment. Locally, they load the personal file above into that environment;
they do not search the product repository or worktree for credentials. In a sandbox, CI runner, or
hosted environment such as Vercel, inject `LINEAR_API_KEY` and `LINEAR_EXPECTED_EMAIL` with that
platform's secret/environment configuration instead of creating a file. Existing `gh`
authentication is used for GitHub, and its login must match `GITHUB_EXPECTED_LOGIN`.

After exposing the variables, pin and verify the intended Linear identity once:

```bash
PATH="<installed-plugin-root>/bin:$PATH" codex-linear identity pin \
  --expected-email you@example.com
PATH="<installed-plugin-root>/bin:$PATH" codex-linear doctor
```

The plugin bundles both `$linear-local` and the CLI fallback under `bin/codex-linear`; no manual
edit inside the Codex plugin cache is required. The agent never reads, prints, or passes the token
as a command argument. During a run, publication stops explicitly if the skill, command,
credential, or pinned identity is unavailable. It never falls back to Linear MCP, a connector,
direct agent-side API calls, or browser automation.

From a clone of this repository, inspect the effective non-secret configuration:

```bash
python3 scripts/issue-delivery config
```

The default profile is [`profiles/turboshop.json`](profiles/turboshop.json). Point
`ISSUE_DELIVERY_PROFILE` at another JSON profile to adapt Local Runtime commands, review bots,
evidence branch, and Linear markers without changing the engine. New-run base and PR target are
selected from the prompt through `--base` and `--target`, with `development` and `test` as defaults.

Remote review observations do not consume a fixed round limit. The profile's
`review.repairBatchSize` controls how many distinct pushed FIX revisions are authorized at once
(five for TurboShop). When that budget is exhausted and valid automated blockers remain, the run
pauses for explicit user approval. Approval adds another equal-sized block and resumes the same
worktree, branch, PR, and run; repeated waits or checks on the same SHA do not consume repairs.

Profiles can declare multiple general-comment blocker authors with `review.blockerBots`; matching
is case-insensitive and accepts GitHub App logins such as `x100-production[bot]`. The legacy
singular `review.blockerBot` remains supported for existing profiles.

## Start a run

Open a new Codex session in the intended product worktree and invoke
`$issue-delivery-orchestrator` with a Linear issue. For a host-independent CLI run, start Codex CLI
in the prepared checkout; Vanilla will be selected automatically when no Codex, Superset, or
Conductor Cloud signal exists. The skill immediately states the chosen mode, decision source,
reviewer, and worktree in the chat, then preserves that mode for the complete run.

The deterministic engine can also be inspected directly:

```bash
python3 scripts/issue-delivery --help
```

To request the manual review handoff when starting a new run:

```bash
python3 scripts/issue-delivery TS-123 --worktree /absolute/product/worktree \
  --handoff manual-runtime
```

The equivalent full-delivery routing is explicit and defaults to:

```bash
python3 scripts/issue-delivery TS-123 --worktree /absolute/product/worktree \
  --base development --target test
```

The conversational skill first stops all registered runtime processes, cleans the previous runtime
resources, and creates a new Local Runtime. It starts only the required apps on that fresh runtime,
then records their healthy URLs, ports, exact commit, optional logs, and cleanup command in
`validation/final-runtime-handoff.json`. The run finishes as `awaiting_manual_review`; Computer
Use, screenshots, PR creation, pushes, and review convergence are deliberately not performed, and
only the fresh runtime processes remain active.

The default `full` flow performs the same reset and health-checked handoff after Computer Use, PR
creation, and remote review convergence. It reaches `completed_preserved` only after the fresh
runtime is ready. The reset does not repeat Computer Use because it preserves the already reviewed
commit; it only removes runtime/cache state before the user's own test.

After a correction, `resume` preserves this target and requires another fresh runtime receipt. To
continue the same run through automatic UI review and PR convergence instead, use:

```bash
python3 scripts/issue-delivery TS-123 resume --full-delivery
```

All run memory, receipts, logs, screenshots, and browser profiles are written under the ignored
runtime directory inside the adopted worktree. Product commits contain only product changes.

Final UI evidence uses deterministic numbered callouts to highlight the changed or relevant
regions. The annotated PNG is shown in Linear and GitHub while the untouched original remains
available through an audit link. Global changes can explicitly omit a localized callout.

In Codex mode, Browser remains the primary reviewer. If Browser demonstrably cannot operate a real
file input or activate a required CSS hover state, only the affected story may use the target
repository's existing Playwright installation in headless mode. Upload assistance drives the real
file input; hover assistance uses the real pointer path, verifies `:hover`, captures the accepted
state, moves away, and checks adjacent persistent state.

In Superset and Vanilla modes, Cua Driver remains the primary reviewer. The same bounded Playwright
assistance is available only after Cua demonstrates an equivalent capability gap. Scripts,
fixtures, screenshots, and receipts stay inside the ignored run directory and remain tied to the
same commit and Local Runtime. The evidence gate rejects unsupported kinds, missing primary
attempts, altered artifacts, or stale receipts. Version 0.3 `uploadAssistance` and version 0.4
Codex Browser receipts remain readable for preserved runs.

In Conductor Cloud mode, Playwright with system Chrome is the primary reviewer for complete
stories, including uploads and hover. It interacts with the real UI, saves traces and final PNGs
under the ignored run directory, and requires visual inspection of those PNGs before PASS. Browser
Preview and Agentation remain optional human feedback surfaces: they are not counted as automatic
verification and require no overlay or dependency in the product. Feedback sent back to the agent
starts a normal `REPAIR-<n>` cycle and invalidates the affected evidence.

## Development

```bash
corepack pnpm test
```

The project requires Python 3.9+ and has no runtime Python package dependencies.

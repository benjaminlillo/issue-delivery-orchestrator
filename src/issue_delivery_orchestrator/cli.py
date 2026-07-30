from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_HOME, Settings, settings
from .credentials import CredentialProvider
from .errors import IdentityMismatch, OrchestrationError, RunBlocked
from .evidence import prepare_evidence, publish_evidence, repair_github_evidence
from .git_workspace import GitWorkspace
from .github import GitHubClient
from .linear import LinearClient, normalize_issue_identifier
from .review import (
    acknowledge_processed_blocker,
    assert_review_converged,
    publish_skip_summary,
    wait_for_quiet_review,
)
from .runtime import (
    cleanup_runtimes,
    initialize_runtime,
    launch_browser,
    register_owned_process,
    stop_owned_processes,
)
from .state import (
    DEVELOPMENT_MODES,
    PHASES,
    REVIEW_METHODS,
    block_run,
    complete_phase,
    create_state,
    find_runs,
    new_run_id,
    resumable_run,
    review_method,
    resume_run,
    run_mode,
    run_root,
    save_state,
    select_review_method,
    now,
)
from .util import ensure_within, run


def parser() -> argparse.ArgumentParser:
    configuration = settings()
    result = argparse.ArgumentParser(
        description="Portable, resumable issue delivery orchestrator"
    )
    result.add_argument("issue", help="Linear issue ID or URL")
    result.add_argument(
        "--base",
        default=configuration.default_base_branch,
        help="Base branch for a new issue branch",
    )
    result.add_argument("--new-run", action="store_true", help="Create a distinct run")
    result.add_argument("--run-id", help="Select an existing run explicitly")
    result.add_argument(
        "--mode",
        choices=DEVELOPMENT_MODES,
        help="Development workspace mode for a new run",
    )
    result.add_argument(
        "--reviewer",
        choices=REVIEW_METHODS,
        help=argparse.SUPPRESS,
    )
    result.add_argument(
        "--worktree",
        type=Path,
        help="Existing checkout or worktree to adopt for this run",
    )
    actions = result.add_subparsers(dest="action")

    actions.add_parser("status")

    reviewer = actions.add_parser(
        "reviewer-select",
        help="Legacy runs only; new runs fix the reviewer through --mode",
    )
    reviewer.add_argument("--method", required=True, choices=REVIEW_METHODS)

    checkpoint = actions.add_parser("checkpoint")
    checkpoint.add_argument("--phase", required=True, choices=PHASES)
    checkpoint.add_argument("--artifact", action="append", default=[], metavar="KEY=PATH")

    blocked = actions.add_parser("block")
    blocked.add_argument("--reason", required=True)
    blocked.add_argument("--decision", action="store_true")

    resume = actions.add_parser("resume")
    resume.add_argument("--phase", choices=PHASES)

    runtime = actions.add_parser("runtime-init")
    runtime.add_argument("--fresh", action="store_true")

    process = actions.add_parser("register-process")
    process.add_argument("--pid", type=int, required=True)
    process.add_argument("--kind", required=True)
    process.add_argument("--command", default="")

    browser = actions.add_parser("launch-browser")
    browser.add_argument("--url", required=True)

    actions.add_parser("stop-processes")

    ensure_pr = actions.add_parser("ensure-pr")
    ensure_pr.add_argument("--body-file", type=Path, required=True)
    ensure_pr.add_argument("--title")

    evidence = actions.add_parser("publish-evidence")
    evidence.add_argument("--manifest", type=Path, required=True)

    prepare = actions.add_parser("prepare-evidence")
    prepare.add_argument("--manifest", type=Path, required=True)

    actions.add_parser("repair-evidence-links")

    review = actions.add_parser("wait-review")
    review.add_argument("--quiet-seconds", type=int, default=configuration.quiet_seconds)
    review.add_argument("--max-seconds", type=int, default=configuration.maximum_wait_seconds)
    review.add_argument("--poll-seconds", type=int, default=configuration.poll_seconds)

    acknowledgement = actions.add_parser("acknowledge-blocker")
    acknowledgement.add_argument("--comment-id", type=int, required=True)
    acknowledgement.add_argument("--decision", choices=("FIX", "SKIP"), required=True)

    skip_summary = actions.add_parser("publish-skip-summary")
    skip_summary.add_argument("--input", type=Path, required=True)

    actions.add_parser("review-gate")

    cleanup = actions.add_parser("cleanup")
    cleanup.add_argument("--force", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv == ["config"]:
        print(json.dumps(settings().public_dict(), indent=2, sort_keys=True))
        return 0
    args = parser().parse_args(raw_argv)
    try:
        payload = dispatch(args)
    except (IdentityMismatch, RunBlocked, OrchestrationError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    configuration = settings()
    repository = _repository(args.worktree, configuration.repository)
    worktrees = Path(
        os.environ.get(
            "ISSUE_DELIVERY_WORKTREES",
            str(DEFAULT_CONFIG_HOME / "worktrees"),
        )
    ).expanduser().resolve()
    workspace = GitWorkspace(repository)
    registered_worktrees = workspace.paths()
    if args.action is None:
        return bootstrap(
            args,
            repository,
            worktrees,
            workspace,
            registered_worktrees,
        )

    state = _select_state(
        args.issue,
        worktrees,
        args.run_id,
        registered_worktrees,
    )
    if args.action == "status":
        return _public_state(state)
    if args.action == "reviewer-select":
        selection = select_review_method(state, args.method)
        return {"reviewer": selection, "state": _public_state(state)}
    if args.action == "checkpoint":
        artifacts = _parse_artifacts(args.artifact, Path(state["worktree"]))
        if args.phase == "manual-revision":
            manifest = artifacts.get("ui-manifest")
            if not manifest:
                raise RunBlocked(
                    "Manual revision requires the ui-manifest artifact"
                )
            prepare_evidence(
                state,
                Path(state["worktree"]) / manifest,
            )
        if args.phase == "review-convergence":
            assert_review_converged(state)
        complete_phase(state, args.phase, artifacts)
        stopped: list[int] = []
        if state["status"] == "completed_preserved":
            stopped = stop_owned_processes(state)
        return {"state": _public_state(state), "stoppedPids": stopped}
    if args.action == "block":
        stopped = stop_owned_processes(state)
        block_run(state, args.reason, args.decision)
        return {"state": _public_state(state), "stoppedPids": stopped}
    if args.action == "resume":
        if args.phase:
            state["currentPhase"] = args.phase
        elif state.get("currentPhase") is None:
            state["currentPhase"] = "review-convergence"
        resume_run(state)
        return _public_state(state)
    if args.action == "runtime-init":
        return initialize_runtime(state, fresh=args.fresh)
    if args.action == "register-process":
        register_owned_process(
            state,
            args.pid,
            kind=args.kind,
            command=args.command,
        )
        return _public_state(state)
    if args.action == "launch-browser":
        if review_method(state) != "cua-driver":
            raise RunBlocked(
                "Dedicated Chrome is disabled in codex mode; "
                "resume manual revision in the Codex app with Browser available"
            )
        return launch_browser(state, args.url)
    if args.action == "stop-processes":
        return {"stoppedPids": stop_owned_processes(state), "state": _public_state(state)}
    if args.action == "ensure-pr":
        return ensure_pull_request(state, args.body_file, args.title)
    if args.action == "publish-evidence":
        linear, _ = _verified_linear()
        github = GitHubClient(Path(state["worktree"]))
        github.verify_identity()
        return publish_evidence(
            state,
            _resolve_in_worktree(args.manifest, Path(state["worktree"])),
            linear=linear,
            github=github if state.get("pr") else None,
        )
    if args.action == "prepare-evidence":
        return prepare_evidence(
            state,
            _resolve_in_worktree(args.manifest, Path(state["worktree"])),
        )
    if args.action == "repair-evidence-links":
        github = GitHubClient(Path(state["worktree"]))
        github.verify_identity()
        return repair_github_evidence(state, github=github)
    if args.action == "wait-review":
        if not state.get("pr"):
            raise RunBlocked("Cannot wait for review before a PR has been recorded")
        if not 0 < args.quiet_seconds <= args.max_seconds:
            raise OrchestrationError("quiet-seconds must be positive and no greater than max-seconds")
        return wait_for_quiet_review(
            state,
            quiet_seconds=args.quiet_seconds,
            max_seconds=args.max_seconds,
            poll_seconds=args.poll_seconds,
        )
    if args.action == "acknowledge-blocker":
        if not state.get("pr"):
            raise RunBlocked("Cannot acknowledge a blocker before a PR has been recorded")
        return acknowledge_processed_blocker(
            state,
            comment_id=args.comment_id,
            decision=args.decision,
        )
    if args.action == "publish-skip-summary":
        return publish_skip_summary(
            state,
            input_path=_resolve_in_worktree(args.input, Path(state["worktree"])),
        )
    if args.action == "review-gate":
        return assert_review_converged(state)
    if args.action == "cleanup":
        return final_cleanup(state, force=args.force)
    raise OrchestrationError(f"Unknown action: {args.action}")


def bootstrap(
    args: argparse.Namespace,
    repository: Path,
    worktrees: Path,
    workspace: GitWorkspace,
    registered_worktrees: tuple[Path, ...],
) -> dict[str, Any]:
    linear, credential_source = _verified_linear()
    issue = linear.issue(args.issue)
    configuration = settings()
    github = GitHubClient(repository)
    github_login = github.verify_identity()

    requested_worktree = _requested_worktree(args.worktree, args.mode)
    previous = resumable_run(worktrees, issue.identifier, registered_worktrees)
    if previous and not args.new_run:
        if args.mode and args.mode != run_mode(previous):
            raise RunBlocked(
                f"Run {previous['runId']} already uses {run_mode(previous)} mode; "
                "development mode cannot change after worktree creation"
            )
        if args.reviewer and args.reviewer != review_method(previous):
            raise RunBlocked(
                f"Run {previous['runId']} already uses {review_method(previous)}; "
                "use reviewer-select before its first manual revision to change it"
            )
        return {
            "resumed": True,
            "credentialSource": credential_source,
            "modeSource": "persisted-run",
            "state": _public_state(previous),
            "nextAction": _next_action(previous),
        }
    if (
        previous
        and requested_worktree
        and Path(previous["worktree"]).resolve() == requested_worktree.expanduser().resolve()
    ):
        raise RunBlocked(
            f"Worktree {requested_worktree} already contains resumable run "
            f"{previous['runId']}; resume it instead of using --new-run"
        )

    if args.reviewer:
        raise RunBlocked(
            "New runs select their UI reviewer through --mode; "
            "codex uses codex-browser; superset and vanilla use cua-driver"
        )
    if not requested_worktree:
        mode_hint = (
            f"{args.mode} mode"
            if args.mode
            else "Automatic mode detection"
        )
        raise RunBlocked(
            f"{mode_hint} requires --worktree with the checkout or worktree "
            "that the loop must adopt"
        )
    mode, mode_source = _new_run_mode(
        args.mode,
        requested_worktree,
        configuration,
    )

    run_id = new_run_id()
    workspace.fetch(args.base)
    if mode == "codex":
        worktree = workspace.adopt_codex(
            requested_worktree,
            issue.branch_name,
            args.base,
            issue.identifier,
        )
    elif mode == "vanilla":
        worktree = workspace.adopt_vanilla(
            requested_worktree,
            issue.branch_name,
            args.base,
            issue.identifier,
        )
    else:
        worktree = workspace.adopt(
            requested_worktree,
            issue.branch_name,
            issue.identifier,
        )
    state = create_state(
        worktree=worktree.path,
        run_id=run_id,
        issue=asdict(issue),
        branch=issue.branch_name,
        base=args.base,
        created_from=worktree.created_from,
        adopted_head=worktree.adopted_head,
        adopted_status=worktree.adopted_status,
        discarded_status=worktree.discarded_status,
        identities={
            "linear": configuration.linear_expected_email,
            "github": github_login,
        },
        mode=mode,
        profile=configuration.public_dict(),
    )
    return {
        "resumed": False,
        "credentialSource": credential_source,
        "modeSource": mode_source,
        "state": _public_state(state),
        "nextAction": _next_action(state),
    }


def ensure_pull_request(
    state: dict[str, Any],
    body_file: Path,
    title: str | None,
) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    body_file = _resolve_in_worktree(body_file, worktree)
    if not body_file.is_file():
        raise OrchestrationError(f"PR body file not found: {body_file}")
    linear, _ = _verified_linear()
    github = GitHubClient(worktree)
    github.verify_identity()
    branch = run(["git", "branch", "--show-current"], cwd=worktree).stdout.strip()
    if branch != state["branch"]:
        raise RunBlocked(f"Expected branch {state['branch']}, got {branch}")

    run(["git", "push", "-u", "origin", branch], cwd=worktree)
    target = github.pr_target
    open_prs = github.find(branch, target, "open")
    created = False
    if open_prs:
        pr = open_prs[0]
    else:
        previous = github.find(branch, target, "all")
        closed = [item for item in previous if item.state != "OPEN"]
        merged = next((item for item in closed if item.merged_at), None)
        if merged:
            block_run(
                state,
                f"PR {merged.url} is already merged; use a follow-up issue and branch",
                decision=False,
            )
            raise RunBlocked(state["blocker"]["reason"])
        if closed:
            block_run(
                state,
                f"PR {closed[0].url} is closed without merge and requires a user decision",
                decision=True,
            )
            raise RunBlocked(state["blocker"]["reason"])
        pr = github.create(
            branch,
            title or f"{state['issue']['identifier']}: {state['issue']['title']}",
            body_file,
        )
        created = True

    if pr.is_draft:
        run(["gh", "pr", "ready", pr.url], cwd=worktree)
        pr = github.view(pr.url)
    if pr.base != target or pr.head != branch:
        raise RunBlocked(
            f"PR routing mismatch: expected {branch} -> {target}, "
            f"got {pr.head} -> {pr.base}"
        )
    state["pr"] = asdict(pr)
    save_state(state)
    if created:
        linear.post_comment(
            state["issue"]["id"],
            f"Pull request lista hacia `{target}`: {pr.url}",
        )
    return {"created": created, "pr": asdict(pr), "state": _public_state(state)}


def final_cleanup(state: dict[str, Any], *, force: bool) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    github = GitHubClient(worktree)
    github.verify_identity()
    if not force:
        if not state.get("pr"):
            raise RunBlocked("Final cleanup requires a recorded merged PR; use --force to override")
        pr = github.view(state["pr"]["url"])
        if not pr.merged_at:
            raise RunBlocked(f"PR {pr.url} is not merged; refusing final cleanup")
    stopped = stop_owned_processes(state)
    cleaned = cleanup_runtimes(state)
    profile = run_root(worktree, state["runId"]) / "browser-profile"
    if profile.exists():
        shutil.rmtree(profile)
    state["status"] = "cleaned"
    state["cleanedAt"] = now()
    save_state(state)
    return {
        "stoppedPids": stopped,
        "cleanedRuntimes": cleaned,
        "worktreePreserved": str(worktree),
        "branchPreserved": state["branch"],
    }


def _verified_linear() -> tuple[LinearClient, str]:
    expected_email = settings().linear_expected_email
    if not expected_email:
        raise IdentityMismatch(
            "LINEAR_EXPECTED_EMAIL must be configured before Linear mutations"
        )
    secret = CredentialProvider().linear_api_key()
    client = LinearClient(secret.value)
    viewer = client.viewer()
    if viewer.email != expected_email:
        raise IdentityMismatch(
            f"Linear identity mismatch: expected {expected_email}, "
            f"got {viewer.email or '<empty>'}"
        )
    return client, secret.source


def _repository(explicit_worktree: Path | None, configured: Path | None) -> Path:
    candidates = [
        explicit_worktree,
        Path(os.environ["SUPERSET_WORKSPACE_PATH"])
        if os.environ.get("SUPERSET_WORKSPACE_PATH")
        else None,
        configured,
        Path.cwd(),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        path = candidate.expanduser().resolve()
        if not path.is_dir():
            continue
        result = run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    raise RunBlocked(
        "Could not locate the target Git repository. Run from a repository worktree "
        "or set ISSUE_DELIVERY_REPOSITORY."
    )


def _select_state(
    issue: str,
    worktrees: Path,
    run_id: str | None,
    registered_worktrees: tuple[Path, ...] = (),
) -> dict[str, Any]:
    identifier = normalize_issue_identifier(issue)
    candidates = find_runs(worktrees, identifier, registered_worktrees)
    if run_id:
        candidates = [state for state in candidates if state.get("runId") == run_id]
    if not candidates:
        raise RunBlocked(f"No orchestration run found for {identifier}")
    return candidates[0]


def _requested_worktree(explicit: Path | None, mode: str | None) -> Path | None:
    if explicit:
        return explicit
    if mode in {"codex", "vanilla"}:
        return None
    raw = os.environ.get("SUPERSET_WORKSPACE_PATH")
    return Path(raw) if raw else None


def _new_run_mode(
    explicit: str | None,
    worktree: Path,
    configuration: Settings,
) -> tuple[str, str]:
    if explicit:
        return explicit, "explicit"

    candidate = worktree.expanduser().resolve()
    superset_workspace = os.environ.get("SUPERSET_WORKSPACE_PATH", "").strip()
    if superset_workspace and candidate == Path(superset_workspace).expanduser().resolve():
        return "superset", "superset-environment"

    configured_matches = _configured_mode_matches(candidate, configuration)
    if len(configured_matches) > 1:
        raise RunBlocked(
            "Worktree matches both configured Codex and Superset roots. "
            "Fix ISSUE_DELIVERY_*_WORKTREE_ROOTS or pass --mode explicitly."
        )
    if configured_matches:
        return configured_matches.pop(), "configured-root"

    marker_matches = _path_mode_markers(candidate)
    if len(marker_matches) > 1:
        raise RunBlocked(
            f"Worktree path contains both Codex and Superset markers: {candidate}. "
            "Pass --mode explicitly."
        )
    if marker_matches:
        return marker_matches.pop(), "path-marker"

    raise RunBlocked(
        f"Could not detect a development mode from worktree {candidate}. "
        "Pass --mode codex|superset|vanilla or configure "
        "ISSUE_DELIVERY_CODEX_WORKTREE_ROOTS / "
        "ISSUE_DELIVERY_SUPERSET_WORKTREE_ROOTS."
    )


def _configured_mode_matches(
    worktree: Path,
    configuration: Settings,
) -> set[str]:
    matches: set[str] = set()
    roots = {
        "codex": configuration.codex_worktree_roots,
        "superset": configuration.superset_worktree_roots,
    }
    for mode, configured_roots in roots.items():
        for raw_root in configured_roots:
            root = Path(raw_root).expanduser().resolve()
            if worktree == root or root in worktree.parents:
                matches.add(mode)
    return matches


def _path_mode_markers(path: Path) -> set[str]:
    matches: set[str] = set()
    for part in path.parts:
        tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", part.casefold())
            if token
        }
        if "codex" in tokens:
            matches.add("codex")
        if "superset" in tokens:
            matches.add("superset")
    return matches


def _resolve_in_worktree(path: Path, worktree: Path) -> Path:
    candidate = path if path.is_absolute() else worktree / path
    return ensure_within(candidate, worktree)


def _parse_artifacts(items: list[str], worktree: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for item in items:
        key, separator, raw_path = item.partition("=")
        if not separator or not key.strip() or not raw_path.strip():
            raise OrchestrationError(f"Expected artifact KEY=PATH, got: {item}")
        path = _resolve_in_worktree(Path(raw_path), worktree)
        if not path.exists():
            raise OrchestrationError(f"Artifact does not exist: {path}")
        artifacts[key.strip()] = str(path.relative_to(worktree))
    return artifacts


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": state["runId"],
        "issue": state["issue"]["identifier"],
        "title": state["issue"]["title"],
        "branch": state["branch"],
        "base": state["base"],
        "worktree": state["worktree"],
        "workspaceMode": (
            "adopted"
            if str(state.get("createdFrom", "")).startswith(
                ("adopted:", "codex:", "vanilla:")
            )
            else "private"
        ),
        "developmentMode": run_mode(state),
        "adoptedStatus": state.get("adoptedStatus", []),
        "discardedInitialStatus": state.get("discardedInitialStatus", []),
        "status": state["status"],
        "currentPhase": state.get("currentPhase"),
        "reviewerMethod": review_method(state),
        "pr": state.get("pr"),
        "blocker": state.get("blocker"),
        "runtimes": [item["runtimeId"] for item in state.get("runtimes", [])],
    }


def _next_action(state: dict[str, Any]) -> str:
    if state["status"] == "needs_user_decision":
        return "Ask the user to resolve the recorded decision gate."
    if state["status"] == "blocked":
        return "Resolve the recorded blocker, then run the resume action."
    if state["status"] == "completed_preserved":
        return "Wait for explicit human-review work or final cleanup after merge."
    if (
        state.get("currentPhase") == "manual-revision"
        and run_mode(state) == "codex"
    ):
        return (
            "Resume this worktree and run in the Codex app with the Browser plugin; "
            "do not launch dedicated Chrome."
        )
    if (
        state.get("currentPhase") == "manual-revision"
        and run_mode(state) == "vanilla"
    ):
        return (
            "Launch the run-owned dedicated browser and verify the UI with "
            "Cua Driver from this checkout."
        )
    return f"Execute phase {state.get('currentPhase')} from the worktree."


if __name__ == "__main__":
    raise SystemExit(main())

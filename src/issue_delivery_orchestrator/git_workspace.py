from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .errors import RunBlocked
from .util import run


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    created_from: str
    adopted_head: str
    adopted_status: tuple[str, ...] = ()


class GitWorkspace:
    def __init__(self, repository: Path, worktrees_root: Path):
        self.repository = repository.resolve()
        self.worktrees_root = worktrees_root.resolve()

    def fetch(self, base: str) -> None:
        run(["git", "fetch", "origin", "--prune"], cwd=self.repository)

    def create(self, branch: str, base: str, issue: str, run_id: str) -> Worktree:
        occupied = self._branch_worktree(branch)
        if occupied:
            raise RunBlocked(f"Branch {branch} is already attached to worktree {occupied}")
        directory = f"{_slug(issue)}-{run_id}"
        destination = self.worktrees_root / directory
        if destination.exists():
            raise RunBlocked(f"Worktree destination already exists: {destination}")
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

        local = self._ref_exists(f"refs/heads/{branch}")
        remote = self._ref_exists(f"refs/remotes/origin/{branch}")
        if local:
            run(["git", "worktree", "add", str(destination), branch], cwd=self.repository)
            created_from = branch
        elif remote:
            run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--track",
                    "-b",
                    branch,
                    str(destination),
                    f"origin/{branch}",
                ],
                cwd=self.repository,
            )
            created_from = f"origin/{branch}"
        else:
            if not self._ref_exists(f"refs/remotes/origin/{base}"):
                raise RunBlocked(f"Base branch origin/{base} does not exist")
            run(
                [
                    "git",
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(destination),
                    f"origin/{base}",
                ],
                cwd=self.repository,
            )
            created_from = f"origin/{base}"
        head = run(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()
        return Worktree(destination, branch, created_from, head)

    def adopt(self, path: Path, expected_branch: str, issue: str) -> Worktree:
        candidate = self._validated_worktree(path)
        branch = run(["git", "branch", "--show-current"], cwd=candidate).stdout.strip()
        if not branch:
            raise RunBlocked(f"Requested worktree is in detached HEAD state: {candidate}")
        if not _matches_issue_branch(branch, expected_branch, issue):
            raise RunBlocked(
                f"Worktree branch {branch} does not match Linear branch {expected_branch}"
            )
        self._require_ignored_runtime(candidate)
        head, status = self._snapshot(candidate)
        return Worktree(candidate, branch, f"adopted:{branch}", head, status)

    def adopt_codex(
        self,
        path: Path,
        expected_branch: str,
        base: str,
        issue: str,
    ) -> Worktree:
        candidate = self._validated_worktree(path)
        branch = run(["git", "branch", "--show-current"], cwd=candidate).stdout.strip()
        if branch:
            if not _matches_issue_branch(branch, expected_branch, issue):
                raise RunBlocked(
                    f"Codex worktree branch {branch} does not match Linear branch "
                    f"{expected_branch}; start the run from a detached Codex worktree"
                )
            self._require_ignored_runtime(candidate)
            head, status = self._snapshot(candidate)
            return Worktree(candidate, branch, f"codex:{branch}", head, status)

        occupied = self._branch_worktree(expected_branch)
        if occupied:
            raise RunBlocked(
                f"Branch {expected_branch} is already attached to worktree {occupied}"
            )

        local = self._ref_exists(f"refs/heads/{expected_branch}")
        remote = self._ref_exists(f"refs/remotes/origin/{expected_branch}")
        if local:
            target = expected_branch
            switch = ["git", "switch", expected_branch]
        elif remote:
            target = f"origin/{expected_branch}"
            switch = ["git", "switch", "--track", "-c", expected_branch, target]
        else:
            target = f"origin/{base}"
            if not self._ref_exists(f"refs/remotes/{target}"):
                raise RunBlocked(f"Base branch {target} does not exist")
            switch = ["git", "switch", "-c", expected_branch, target]

        self._require_safe_codex_switch(candidate, target, base)
        run(switch, cwd=candidate)
        self._require_ignored_runtime(candidate)
        head, status = self._snapshot(candidate)
        return Worktree(candidate, expected_branch, f"codex:{target}", head, status)

    def paths(self) -> tuple[Path, ...]:
        output = run(["git", "worktree", "list", "--porcelain"], cwd=self.repository).stdout
        return tuple(
            Path(line.removeprefix("worktree ")).resolve()
            for line in output.splitlines()
            if line.startswith("worktree ")
        )

    def _ref_exists(self, ref: str) -> bool:
        return (
            run(
                ["git", "show-ref", "--verify", "--quiet", ref],
                cwd=self.repository,
                check=False,
            ).returncode
            == 0
        )

    def _branch_worktree(self, branch: str) -> Path | None:
        output = run(["git", "worktree", "list", "--porcelain"], cwd=self.repository).stdout
        current_path: Path | None = None
        for line in output.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line.removeprefix("worktree "))
            elif line == f"branch refs/heads/{branch}" and current_path:
                return current_path
        return None

    def _validated_worktree(self, path: Path) -> Path:
        candidate = path.expanduser().resolve()
        if not candidate.is_dir():
            raise RunBlocked(f"Requested worktree does not exist: {candidate}")
        top_level = Path(
            run(["git", "rev-parse", "--show-toplevel"], cwd=candidate).stdout.strip()
        ).resolve()
        if top_level != candidate:
            raise RunBlocked(f"Requested path is not a worktree root: {candidate}")
        if self._git_common_dir(candidate) != self._git_common_dir(self.repository):
            raise RunBlocked(f"Requested worktree belongs to a different repository: {candidate}")
        if candidate not in self.paths():
            raise RunBlocked(f"Requested path is not a registered Git worktree: {candidate}")
        return candidate

    @staticmethod
    def _require_ignored_runtime(path: Path) -> None:
        configuration = settings()
        ignored_probe = str(
            Path(configuration.runtime_root)
            / configuration.runtime_namespace
            / ".ignore-probe"
        )
        ignored = run(
            ["git", "check-ignore", "--quiet", "--no-index", ignored_probe],
            cwd=path,
            check=False,
        )
        if ignored.returncode != 0:
            raise RunBlocked(
                f"The adopted worktree must ignore {configuration.runtime_root} before "
                "orchestration state can be stored safely"
            )

    @staticmethod
    def _snapshot(path: Path) -> tuple[str, tuple[str, ...]]:
        head = run(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()
        status = tuple(
            line
            for line in run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=path,
            ).stdout.splitlines()
            if line
        )
        return head, status

    def _require_safe_codex_switch(self, path: Path, target: str, base: str) -> None:
        head = run(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()
        target_head = run(["git", "rev-parse", target], cwd=path).stdout.strip()
        status = self._snapshot(path)[1]
        if head != target_head and status:
            raise RunBlocked(
                f"Codex worktree has local changes and is not based on {target}; "
                "start a fresh Codex worktree from the requested base"
            )
        safe_refs = [target]
        remote_base = f"origin/{base}"
        if self._ref_exists(f"refs/remotes/{remote_base}"):
            safe_refs.append(remote_base)
        head_is_preserved = any(
            run(
                ["git", "merge-base", "--is-ancestor", "HEAD", ref],
                cwd=path,
                check=False,
            ).returncode
            == 0
            for ref in safe_refs
        )
        if not head_is_preserved:
            raise RunBlocked(
                f"Codex worktree has commits not contained in {target} or {remote_base}; "
                "preserve them before starting a new run"
            )

    @staticmethod
    def _git_common_dir(path: Path) -> Path:
        raw = Path(run(["git", "rev-parse", "--git-common-dir"], cwd=path).stdout.strip())
        return (path / raw).resolve() if not raw.is_absolute() else raw.resolve()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _matches_issue_branch(actual: str, expected: str, issue: str) -> bool:
    if actual == expected:
        return True
    issue_marker = issue.lower()
    actual_lower = actual.lower()
    carries_issue = actual_lower == issue_marker or f"/{issue_marker}" in actual_lower
    return carries_issue and expected.startswith(actual)

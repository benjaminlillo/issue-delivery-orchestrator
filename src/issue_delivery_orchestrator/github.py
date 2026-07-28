from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import settings
from .errors import IdentityMismatch, OrchestrationError
from .util import run


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    state: str
    merged_at: str | None
    is_draft: bool
    head: str
    base: str


class GitHubClient:
    def __init__(
        self,
        cwd: Path,
        *,
        expected_login: str | None = None,
        evidence_branch: str | None = None,
        pr_target: str | None = None,
    ):
        configuration = settings()
        self.cwd = cwd
        self.expected_login = (
            expected_login
            if expected_login is not None
            else configuration.github_expected_login
        )
        self.evidence_branch = evidence_branch or configuration.evidence_branch
        self.pr_target = pr_target or configuration.pr_target_branch

    def verify_identity(self) -> str:
        if not self.expected_login:
            raise IdentityMismatch(
                "GITHUB_EXPECTED_LOGIN must be configured before GitHub mutations"
            )
        result = run(["gh", "api", "user", "--jq", ".login"], cwd=self.cwd)
        login = result.stdout.strip()
        if login != self.expected_login:
            raise IdentityMismatch(
                f"GitHub identity mismatch: expected {self.expected_login}, "
                f"got {login or '<empty>'}"
            )
        return login

    def find(self, head: str, base: str, state: str = "open") -> list[PullRequest]:
        result = run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                head,
                "--base",
                base,
                "--state",
                state,
                "--json",
                "number,url,state,mergedAt,isDraft,headRefName,baseRefName",
            ],
            cwd=self.cwd,
        )
        return [_pull_request(item) for item in json.loads(result.stdout or "[]")]

    def view(self, reference: str) -> PullRequest:
        result = run(
            [
                "gh",
                "pr",
                "view",
                reference,
                "--json",
                "number,url,state,mergedAt,isDraft,headRefName,baseRefName",
            ],
            cwd=self.cwd,
        )
        return _pull_request(json.loads(result.stdout))

    def create(self, head: str, title: str, body_file: Path) -> PullRequest:
        result = run(
            [
                "gh",
                "pr",
                "create",
                "--head",
                head,
                "--base",
                self.pr_target,
                "--title",
                title,
                "--body-file",
                str(body_file),
            ],
            cwd=self.cwd,
        )
        url = result.stdout.strip().splitlines()[-1]
        return self.view(url)

    def upsert_comment(self, pr_number: int, marker: str, body: str) -> str:
        result = run(
            [
                "gh",
                "api",
                "repos/:owner/:repo/issues/{}/comments".format(pr_number),
                "--paginate",
                "--slurp",
            ],
            cwd=self.cwd,
        )
        pages = json.loads(result.stdout or "[]")
        comments = [comment for page in pages for comment in page]
        existing = next(
            (comment for comment in comments if marker in str(comment.get("body") or "")),
            None,
        )
        if existing:
            run(
                [
                    "gh",
                    "api",
                    f"repos/:owner/:repo/issues/comments/{existing['id']}",
                    "-X",
                    "PATCH",
                    "-f",
                    f"body={body}",
                ],
                cwd=self.cwd,
            )
            return str(existing["id"])
        result = run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            cwd=self.cwd,
        )
        return result.stdout.strip()

    def issue_comment(self, comment_id: int) -> dict[str, Any]:
        return self._api_json(f"repos/:owner/:repo/issues/comments/{comment_id}")

    def issue_comment_reactions(self, comment_id: int) -> list[dict[str, Any]]:
        result = run(
            [
                "gh",
                "api",
                f"repos/:owner/:repo/issues/comments/{comment_id}/reactions",
                "--paginate",
                "--slurp",
            ],
            cwd=self.cwd,
        )
        pages = json.loads(result.stdout or "[]")
        return [
            reaction
            for page in pages
            if isinstance(page, list)
            for reaction in page
            if isinstance(reaction, dict)
        ]

    def has_issue_comment_reaction(
        self,
        comment_id: int,
        *,
        content: str,
        login: str | None = None,
    ) -> bool:
        expected_login = login if login is not None else self.expected_login
        if not expected_login:
            raise IdentityMismatch(
                "GITHUB_EXPECTED_LOGIN must be configured before checking reactions"
            )
        return any(
            reaction.get("content") == content
            and str((reaction.get("user") or {}).get("login") or "") == expected_login
            for reaction in self.issue_comment_reactions(comment_id)
        )

    def add_issue_comment_reaction(
        self,
        comment_id: int,
        *,
        content: str,
    ) -> bool:
        if self.has_issue_comment_reaction(comment_id, content=content):
            return False
        self._api_json(
            f"repos/:owner/:repo/issues/comments/{comment_id}/reactions",
            method="POST",
            payload={"content": content},
        )
        return True

    def review_threads(self, pr_number: int) -> list[dict[str, Any]]:
        repository_result = run(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            cwd=self.cwd,
        )
        name_with_owner = str(
            json.loads(repository_result.stdout or "{}").get("nameWithOwner") or ""
        )
        owner, separator, name = name_with_owner.partition("/")
        if not separator or not owner or not name:
            raise OrchestrationError(
                f"Could not resolve GitHub repository from {name_with_owner or '<empty>'}"
            )
        query = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          id
          isResolved
          comments(first: 100) {
            pageInfo { hasNextPage }
            nodes {
              databaseId
              url
              body
              author { login }
            }
          }
        }
      }
    }
  }
}
"""
        result = run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr_number}",
            ],
            cwd=self.cwd,
        )
        data = json.loads(result.stdout or "{}")
        threads = (
            ((data.get("data") or {}).get("repository") or {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
        )
        if threads.get("pageInfo", {}).get("hasNextPage"):
            raise OrchestrationError(
                f"PR #{pr_number} has more than 100 review threads; "
                "refusing to validate an incomplete result"
            )
        nodes = threads.get("nodes") or []
        if any(
            ((thread.get("comments") or {}).get("pageInfo") or {}).get("hasNextPage")
            for thread in nodes
            if isinstance(thread, dict)
        ):
            raise OrchestrationError(
                f"PR #{pr_number} has a review thread with more than 100 comments; "
                "refusing to validate an incomplete result"
            )
        return [thread for thread in nodes if isinstance(thread, dict)]

    def publish_evidence_files(
        self,
        files: list[tuple[Path, str]],
        *,
        message: str,
    ) -> dict[str, str]:
        if not files:
            return {}
        tree_entries = []
        for source, target in files:
            if not source.is_file():
                raise OrchestrationError(f"Evidence file not found: {source}")
            if source.stat().st_size > 10 * 1024 * 1024:
                raise OrchestrationError(f"Evidence file exceeds 10 MB: {source.name}")
            if not target.startswith(".issue-delivery-evidence/") or ".." in Path(target).parts:
                raise OrchestrationError(f"Unsafe evidence target path: {target}")
            blob = self._api_json(
                "repos/:owner/:repo/git/blobs",
                method="POST",
                payload={
                    "content": base64.b64encode(source.read_bytes()).decode(),
                    "encoding": "base64",
                },
            )
            tree_entries.append(
                {
                    "path": target,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            )

        self._ensure_evidence_branch()
        last_error = ""
        for _attempt in range(3):
            reference = self._api_json(
                f"repos/:owner/:repo/git/ref/heads/{self.evidence_branch}"
            )
            parent_sha = reference["object"]["sha"]
            parent = self._api_json(f"repos/:owner/:repo/git/commits/{parent_sha}")
            tree = self._api_json(
                "repos/:owner/:repo/git/trees",
                method="POST",
                payload={"base_tree": parent["tree"]["sha"], "tree": tree_entries},
            )
            commit = self._api_json(
                "repos/:owner/:repo/git/commits",
                method="POST",
                payload={
                    "message": message,
                    "tree": tree["sha"],
                    "parents": [parent_sha],
                },
            )
            update_result, _ = self._api_json_result(
                f"repos/:owner/:repo/git/refs/heads/{self.evidence_branch}",
                method="PATCH",
                payload={"sha": commit["sha"], "force": False},
                check=False,
            )
            if update_result.returncode == 0:
                return {
                    target: f"../blob/{self.evidence_branch}/{target}?raw=true"
                    for _source, target in files
                }
            last_error = update_result.stderr.strip() or update_result.stdout.strip()
        raise OrchestrationError(
            f"Could not update {self.evidence_branch} after concurrent retries: {last_error}"
        )

    def _ensure_evidence_branch(self) -> None:
        result, _ = self._api_json_result(
            f"repos/:owner/:repo/git/ref/heads/{self.evidence_branch}",
            check=False,
        )
        if result.returncode == 0:
            return
        target_ref = self._api_json(
            f"repos/:owner/:repo/git/ref/heads/{self.pr_target}"
        )
        create_result, _ = self._api_json_result(
            "repos/:owner/:repo/git/refs",
            method="POST",
            payload={
                "ref": f"refs/heads/{self.evidence_branch}",
                "sha": target_ref["object"]["sha"],
            },
            check=False,
        )
        if create_result.returncode != 0:
            retry, _ = self._api_json_result(
                f"repos/:owner/:repo/git/ref/heads/{self.evidence_branch}",
                check=False,
            )
            if retry.returncode != 0:
                detail = create_result.stderr.strip() or create_result.stdout.strip()
                raise OrchestrationError(f"Could not create evidence branch: {detail}")

    def _api_json(
        self,
        endpoint: str,
        *,
        method: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result, data = self._api_json_result(
            endpoint,
            method=method,
            payload=payload,
            check=True,
        )
        if not isinstance(data, dict):
            raise OrchestrationError(f"GitHub API returned invalid JSON for {endpoint}")
        return data

    def _api_json_result(
        self,
        endpoint: str,
        *,
        method: str | None = None,
        payload: dict[str, Any] | None = None,
        check: bool,
    ):
        args = ["gh", "api", endpoint]
        if method:
            args.extend(["--method", method])
        input_text = None
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload)
        result = run(
            args,
            cwd=self.cwd,
            check=check,
            input_text=input_text,
        )
        try:
            data = json.loads(result.stdout or "null")
        except json.JSONDecodeError:
            data = None
        return result, data


def _pull_request(data: dict) -> PullRequest:
    return PullRequest(
        number=int(data["number"]),
        url=data["url"],
        state=data["state"],
        merged_at=data.get("mergedAt"),
        is_draft=bool(data.get("isDraft")),
        head=data.get("headRefName") or "",
        base=data.get("baseRefName") or "",
    )

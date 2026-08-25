#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


API_URL = "https://api.linear.app/graphql"
CONFIG_DIR = Path.home() / ".config" / "codex-linear"
IDENTITY_FILE = CONFIG_DIR / "identity.json"
ORCHESTRATOR_CONFIG_DIR = Path.home() / ".config" / "issue-delivery-orchestrator"
DEFAULT_KEYCHAIN_SERVICE = "issue-delivery-orchestrator-linear"

VIEWER_QUERY = """
query CodexLinearViewer {
  viewer { id name displayName email }
}
"""

ISSUE_FIELDS = """
id
identifier
title
description
url
estimate
priority
branchName
team { id key name }
state { id name type }
assignee { id name displayName email }
creator { id name displayName email }
project { id name }
cycle { id number name startsAt endsAt }
labels { nodes { id name } }
"""


class LinearCliError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credential:
    value: str
    service: str
    account: str


def _load_orchestrator_environment() -> None:
    explicit = os.environ.get("ISSUE_DELIVERY_ENV_FILE", "").strip()
    candidate = (
        Path(explicit).expanduser()
        if explicit
        else ORCHESTRATOR_CONFIG_DIR / ".env"
    )
    if not candidate.is_file():
        return
    for number, raw_line in enumerate(candidate.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise LinearCliError(f"Invalid .env entry at {candidate}:{number}")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key in {"LINEAR_EXPECTED_EMAIL", "LINEAR_KEYCHAIN_SERVICE"}:
            os.environ.setdefault(key, value)


def _keychain_target() -> tuple[str, str]:
    _load_orchestrator_environment()
    service = (
        os.environ.get("LINEAR_KEYCHAIN_SERVICE", "").strip()
        or DEFAULT_KEYCHAIN_SERVICE
    )
    account = os.environ.get("LINEAR_EXPECTED_EMAIL", "").strip().lower()
    if not account:
        raise LinearCliError(
            "LINEAR_EXPECTED_EMAIL is required in the environment or "
            "~/.config/issue-delivery-orchestrator/.env"
        )
    return service, account


def _json_dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _read_keychain() -> Credential:
    if sys.platform != "darwin":
        raise LinearCliError("macOS Keychain is required")
    service, account = _keychain_target()
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode == 0 and value:
        return Credential(value=value, service=service, account=account)
    raise LinearCliError(
        "Linear credential not found in Keychain; expected "
        f"{service}/{account}"
    )


def _graphql(credential: Credential, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={"Authorization": credential.value, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise LinearCliError(f"Linear HTTP request failed with status {error.code}") from error
    except urllib.error.URLError as error:
        raise LinearCliError(f"Linear request failed: {error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LinearCliError("Linear returned an invalid JSON response") from error
    if payload.get("errors"):
        messages = [str(item.get("message") or "GraphQL error") for item in payload["errors"]]
        raise LinearCliError("Linear GraphQL error: " + "; ".join(messages))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LinearCliError("Linear response did not contain a data object")
    return data


def _viewer(credential: Credential) -> dict[str, Any]:
    viewer = _graphql(credential, VIEWER_QUERY, {}).get("viewer")
    if not isinstance(viewer, dict) or not viewer.get("id") or not viewer.get("email"):
        raise LinearCliError("Linear viewer response is incomplete")
    viewer["email"] = str(viewer["email"]).lower()
    return viewer


def _read_identity() -> dict[str, Any] | None:
    if not IDENTITY_FILE.exists():
        return None
    try:
        value = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LinearCliError(f"Pinned identity is invalid: {IDENTITY_FILE}") from error
    if not isinstance(value, dict) or not value.get("id") or not value.get("email"):
        raise LinearCliError(f"Pinned identity is incomplete: {IDENTITY_FILE}")
    return value


def _pin_identity(credential: Credential, expected_email: str) -> dict[str, Any]:
    viewer = _viewer(credential)
    normalized = expected_email.strip().lower()
    if viewer["email"] != normalized:
        raise LinearCliError(
            f"Linear identity mismatch: expected {normalized}, got {viewer['email']}"
        )
    identity = {
        "id": viewer["id"],
        "email": viewer["email"],
        "name": viewer.get("name") or "",
        "displayName": viewer.get("displayName") or "",
    }
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    temporary = IDENTITY_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(IDENTITY_FILE)
    os.chmod(IDENTITY_FILE, 0o600)
    return identity


def _verify_identity(credential: Credential) -> dict[str, Any]:
    expected = _read_identity()
    if expected is None:
        raise LinearCliError(
            "Linear identity is not pinned; run codex-linear identity pin --expected-email <email>"
        )
    actual = _viewer(credential)
    if actual["id"] != expected["id"] or actual["email"] != expected["email"]:
        raise LinearCliError(
            "Linear identity mismatch: "
            f"expected {expected['email']} ({expected['id']}), "
            f"got {actual['email']} ({actual['id']})"
        )
    return actual


def _is_mutation(query: str) -> bool:
    without_comments = re.sub(r"(?m)#.*$", "", query)
    return re.search(r"(?i)(?:^|[\s}])mutation\b", without_comments) is not None


def _issue(credential: Credential, identifier: str) -> dict[str, Any]:
    query = f"""
    query CodexLinearIssue($id: String!) {{
      issue(id: $id) {{ {ISSUE_FIELDS} }}
    }}
    """
    issue = _graphql(credential, query, {"id": identifier}).get("issue")
    if not isinstance(issue, dict):
        raise LinearCliError(f"Linear issue not found: {identifier}")
    return issue


def _teams(credential: Credential) -> list[dict[str, Any]]:
    query = """
    query CodexLinearTeams {
      teams {
        nodes {
          id
          key
          name
          states { nodes { id name type } }
        }
      }
    }
    """
    return _graphql(credential, query, {}).get("teams", {}).get("nodes", [])


def _team(credential: Credential, name_or_key: str) -> dict[str, Any]:
    wanted = name_or_key.strip().casefold()
    matches = [
        item
        for item in _teams(credential)
        if str(item.get("name") or "").casefold() == wanted
        or str(item.get("key") or "").casefold() == wanted
    ]
    if len(matches) != 1:
        raise LinearCliError(f"Expected one Linear team matching {name_or_key!r}, found {len(matches)}")
    return matches[0]


def _read_text(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise LinearCliError(f"File not found: {candidate}")
    return candidate.read_text(encoding="utf-8")


def _issue_create(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    viewer = _verify_identity(credential)
    team = _team(credential, args.team)
    states = team.get("states", {}).get("nodes", [])
    wanted_state = args.state.strip().casefold()
    matching_states = [state for state in states if str(state.get("name") or "").casefold() == wanted_state]
    if len(matching_states) != 1:
        raise LinearCliError(
            f"Expected one state named {args.state!r} in team {team['name']}, found {len(matching_states)}"
        )
    issue_input: dict[str, Any] = {
        "teamId": team["id"],
        "stateId": matching_states[0]["id"],
        "title": args.title,
        "description": _read_text(args.description_file),
        "estimate": args.estimate,
    }
    if args.assign_viewer:
        issue_input["assigneeId"] = viewer["id"]
    query = f"""
    mutation CodexLinearIssueCreate($input: IssueCreateInput!) {{
      issueCreate(input: $input) {{
        success
        issue {{ {ISSUE_FIELDS} }}
      }}
    }}
    """
    payload = _graphql(credential, query, {"input": issue_input}).get("issueCreate", {})
    issue = payload.get("issue")
    if not payload.get("success") or not isinstance(issue, dict):
        raise LinearCliError("Linear issueCreate did not succeed")
    return _issue(credential, issue["id"])


def _update_description(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    issue = _issue(credential, args.issue)
    query = """
    mutation CodexLinearIssueUpdate($id: String!, $description: String!) {
      issueUpdate(id: $id, input: { description: $description }) { success }
    }
    """
    payload = _graphql(
        credential,
        query,
        {"id": issue["id"], "description": _read_text(args.description_file)},
    ).get("issueUpdate", {})
    if not payload.get("success"):
        raise LinearCliError("Linear issueUpdate did not succeed")
    return _issue(credential, issue["id"])


def _comment_create(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    issue = _issue(credential, args.issue)
    query = """
    mutation CodexLinearCommentCreate($issueId: String!, $body: String!) {
      commentCreate(input: { issueId: $issueId, body: $body }) {
        success
        comment { id body url user { id name displayName email } }
      }
    }
    """
    payload = _graphql(
        credential,
        query,
        {"issueId": issue["id"], "body": _read_text(args.body_file)},
    ).get("commentCreate", {})
    if not payload.get("success") or not isinstance(payload.get("comment"), dict):
        raise LinearCliError("Linear commentCreate did not succeed")
    return {"issue": issue["identifier"], "comment": payload["comment"]}


def _request(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    try:
        payload = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LinearCliError(f"Invalid GraphQL request file: {args.file}") from error
    query = payload.get("query") if isinstance(payload, dict) else None
    variables = payload.get("variables", {}) if isinstance(payload, dict) else None
    if not isinstance(query, str) or not isinstance(variables, dict):
        raise LinearCliError("Request file must contain a string query and an object variables value")
    if _is_mutation(query):
        _verify_identity(credential)
    return _graphql(credential, query, variables)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-linear")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("whoami")
    commands.add_parser("doctor")

    identity = commands.add_parser("identity")
    identity_commands = identity.add_subparsers(dest="identity_command", required=True)
    identity_commands.add_parser("status")
    pin = identity_commands.add_parser("pin")
    pin.add_argument("--expected-email", required=True)

    team = commands.add_parser("team")
    team_commands = team.add_subparsers(dest="team_command", required=True)
    team_get = team_commands.add_parser("get")
    team_get.add_argument("team")

    issue = commands.add_parser("issue")
    issue_commands = issue.add_subparsers(dest="issue_command", required=True)
    issue_get = issue_commands.add_parser("get")
    issue_get.add_argument("issue")
    issue_create = issue_commands.add_parser("create")
    issue_create.add_argument("--team", required=True)
    issue_create.add_argument("--state", required=True)
    issue_create.add_argument("--title", required=True)
    issue_create.add_argument("--description-file", required=True)
    issue_create.add_argument("--estimate", required=True, type=int, choices=(1, 2, 4, 8, 16))
    issue_create.add_argument("--assign-viewer", action="store_true")
    issue_update = issue_commands.add_parser("update-description")
    issue_update.add_argument("issue")
    issue_update.add_argument("--description-file", required=True)

    comment = commands.add_parser("comment")
    comment_commands = comment.add_subparsers(dest="comment_command", required=True)
    comment_create = comment_commands.add_parser("create")
    comment_create.add_argument("issue")
    comment_create.add_argument("--body-file", required=True)

    request = commands.add_parser("request")
    request.add_argument("--file", required=True)
    return parser


def _run(args: argparse.Namespace) -> Any:
    credential = _read_keychain()
    if args.command == "whoami":
        return {
            "viewer": _viewer(credential),
            "credential": {"service": credential.service, "account": credential.account},
        }
    if args.command == "doctor":
        viewer = _verify_identity(credential)
        return {
            "ok": True,
            "credential": {"service": credential.service, "account": credential.account},
            "viewer": viewer,
            "identityPinned": True,
            "identityMatches": True,
        }
    if args.command == "identity":
        if args.identity_command == "pin":
            return {"pinned": _pin_identity(credential, args.expected_email)}
        expected = _read_identity()
        actual = _viewer(credential)
        return {
            "pinned": expected,
            "actual": actual,
            "matches": bool(
                expected
                and expected.get("id") == actual.get("id")
                and expected.get("email") == actual.get("email")
            ),
        }
    if args.command == "team":
        _verify_identity(credential)
        return _team(credential, args.team)
    if args.command == "issue":
        if args.issue_command == "get":
            _verify_identity(credential)
            return _issue(credential, args.issue)
        if args.issue_command == "create":
            return _issue_create(args, credential)
        return _update_description(args, credential)
    if args.command == "comment":
        return _comment_create(args, credential)
    if args.command == "request":
        _verify_identity(credential)
        return _request(args, credential)
    raise LinearCliError("Unsupported command")


def main() -> int:
    try:
        _json_dump(_run(_parser().parse_args()))
        return 0
    except LinearCliError as error:
        print(f"codex-linear: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("codex-linear: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

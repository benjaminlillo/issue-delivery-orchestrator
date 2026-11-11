#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


API_URL = "https://api.linear.app/graphql"
ORCHESTRATOR_CONFIG_DIR = Path.home() / ".config" / "issue-delivery-orchestrator"

VIEWER_QUERY = """
query CodexLinearViewer {
  viewer { id name displayName email }
  organization { id name urlKey }
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
projectMilestone { id name }
parent { identifier }
cycle { id number name startsAt endsAt }
labels { nodes { id name } }
"""


PROJECT_FIELDS = """
id
slugId
name
url
description
content
state
lead { id name displayName email }
teams { nodes { id key name } }
"""

MILESTONE_FIELDS = "id name description status progress sortOrder targetDate"

PROJECT_ISSUE_FIELDS = """
identifier
title
url
branchName
updatedAt
estimate
priority
state { name type }
projectMilestone { name }
assignee { email }
labels(first: 20) { nodes { name } }
relations(first: 20) { nodes { type relatedIssue { identifier } } }
inverseRelations(first: 20) { nodes { type issue { identifier } } }
"""

PROJECT_SLUG_PATTERN = re.compile(r"^[0-9a-f]{12}$")
PROJECT_URL_PATTERN = re.compile(r"/project/[^/?#]*?-?([0-9a-f]{12})(?:[/?#]|$)")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


class LinearCliError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credential:
    value: str
    source: str
    account: str
    workspace: str


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
        if key in {"LINEAR_API_KEY", "LINEAR_EXPECTED_EMAIL", "LINEAR_EXPECTED_WORKSPACE"}:
            os.environ.setdefault(key, value)


def _read_environment_credential() -> Credential:
    _load_orchestrator_environment()
    value = os.environ.get("LINEAR_API_KEY", "").strip()
    if not value:
        raise LinearCliError(
            "LINEAR_API_KEY is required in the environment or "
            "~/.config/issue-delivery-orchestrator/.env"
        )
    account = os.environ.get("LINEAR_EXPECTED_EMAIL", "").strip().lower()
    if not account:
        raise LinearCliError(
            "LINEAR_EXPECTED_EMAIL is required in the environment or "
            "~/.config/issue-delivery-orchestrator/.env"
        )
    workspace = os.environ.get("LINEAR_EXPECTED_WORKSPACE", "").strip().lower()
    return Credential(value=value, source="environment", account=account, workspace=workspace)


def _json_dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


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
        try:
            messages = [str(item.get("message")) for item in json.loads(error.read()).get("errors", [])]
        except (ValueError, AttributeError):
            messages = []
        detail = f": {'; '.join(messages)}" if messages else ""
        raise LinearCliError(f"Linear HTTP request failed with status {error.code}{detail}") from error
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
    data = _graphql(credential, VIEWER_QUERY, {})
    viewer = data.get("viewer")
    organization = data.get("organization")
    if not isinstance(viewer, dict) or not viewer.get("id") or not viewer.get("email"):
        raise LinearCliError("Linear viewer response is incomplete")
    if not isinstance(organization, dict) or not organization.get("urlKey"):
        raise LinearCliError("Linear organization response is incomplete")
    viewer["email"] = str(viewer["email"]).lower()
    viewer["organization"] = organization
    return viewer


def _verify_identity(credential: Credential) -> dict[str, Any]:
    """Require the expected user and, when configured, the expected Linear workspace."""
    actual = _viewer(credential)
    workspace = str(actual["organization"]["urlKey"]).lower()
    if actual["email"] != credential.account:
        raise LinearCliError(
            f"Linear identity mismatch: expected {credential.account}, got {actual['email']}"
        )
    if credential.workspace and workspace != credential.workspace:
        raise LinearCliError(
            f"Linear workspace mismatch: expected {credential.workspace}, got {workspace}"
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


def _paginate(
    credential: Credential, query: str, variables: dict[str, Any], path: tuple[str, ...]
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    after = None
    while True:
        connection: Any = _graphql(credential, query, {**variables, "after": after})
        for key in path:
            connection = connection.get(key) if isinstance(connection, dict) else None
        if not isinstance(connection, dict):
            raise LinearCliError(f"Linear response is missing {'.'.join(path)}")
        nodes.extend(connection.get("nodes") or [])
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return nodes
        after = page.get("endCursor")


def _project(credential: Credential, reference: str) -> dict[str, Any]:
    """Resolve a project by UUID, slug ID, Linear URL or exact name."""
    wanted = reference.strip()
    url_match = PROJECT_URL_PATTERN.search(wanted)
    if url_match:
        wanted = url_match.group(1)
    if UUID_PATTERN.match(wanted.lower()) or PROJECT_SLUG_PATTERN.match(wanted.lower()):
        query = f"""
        query CodexLinearProject($id: String!) {{
          project(id: $id) {{ {PROJECT_FIELDS} }}
        }}
        """
        project = _graphql(credential, query, {"id": wanted.lower()}).get("project")
        if not isinstance(project, dict):
            raise LinearCliError(f"Linear project not found: {reference}")
        return project
    query = f"""
    query CodexLinearProjectByName($name: String!) {{
      projects(first: 2, filter: {{ name: {{ eqIgnoreCase: $name }} }}) {{
        nodes {{ {PROJECT_FIELDS} }}
      }}
    }}
    """
    matches = _graphql(credential, query, {"name": wanted}).get("projects", {}).get("nodes", [])
    if len(matches) != 1:
        raise LinearCliError(f"Expected one Linear project named {reference!r}, found {len(matches)}")
    return matches[0]


def _project_issues(credential: Credential, reference: str) -> dict[str, Any]:
    project = _project(credential, reference)
    query = f"""
    query CodexLinearProjectIssues($id: String!, $after: String) {{
      project(id: $id) {{
        issues(first: 25, after: $after) {{
          nodes {{ {PROJECT_ISSUE_FIELDS} }}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    }}
    """
    issues = []
    for node in _paginate(credential, query, {"id": project["id"]}, ("project", "issues")):
        relations = node.pop("relations", {}).get("nodes", [])
        inverse = node.pop("inverseRelations", {}).get("nodes", [])
        node["labels"] = [label["name"] for label in node.get("labels", {}).get("nodes", [])]
        node["blocks"] = sorted(
            item["relatedIssue"]["identifier"] for item in relations if item.get("type") == "blocks"
        )
        node["blockedBy"] = sorted(
            item["issue"]["identifier"] for item in inverse if item.get("type") == "blocks"
        )
        issues.append(node)
    return {"project": {key: project[key] for key in ("id", "slugId", "name", "url")}, "issues": issues}


def _project_update_content(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    project = _project(credential, args.project)
    query = """
    mutation CodexLinearProjectUpdate($id: String!, $content: String!) {
      projectUpdate(id: $id, input: { content: $content }) { success }
    }
    """
    payload = _graphql(
        credential, query, {"id": project["id"], "content": _read_text(args.content_file)}
    ).get("projectUpdate", {})
    if not payload.get("success"):
        raise LinearCliError("Linear projectUpdate did not succeed")
    return _project(credential, project["id"])


def _project_milestones(credential: Credential, project_id: str) -> list[dict[str, Any]]:
    query = f"""
    query CodexLinearProjectMilestones($id: String!, $after: String) {{
      project(id: $id) {{
        projectMilestones(first: 50, after: $after) {{
          nodes {{ {MILESTONE_FIELDS} }}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    }}
    """
    milestones = _paginate(credential, query, {"id": project_id}, ("project", "projectMilestones"))
    return sorted(milestones, key=lambda milestone: milestone.get("sortOrder") or 0)


def _milestone(credential: Credential, project: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        milestone
        for milestone in _project_milestones(credential, project["id"])
        if str(milestone.get("name") or "").casefold() == name.strip().casefold()
    ]
    if len(matches) != 1:
        raise LinearCliError(
            f"Expected one milestone named {name!r} in project {project['name']}, found {len(matches)}"
        )
    return matches[0]


def _project_milestone_list(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    project = _project(credential, args.project)
    return {
        "project": {key: project[key] for key in ("id", "slugId", "name", "url")},
        "milestones": _project_milestones(credential, project["id"]),
    }


def _project_milestone_create(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    project = _project(credential, args.project)
    name = args.name.strip()
    existing = [
        milestone
        for milestone in _project_milestones(credential, project["id"])
        if str(milestone.get("name") or "").casefold() == name.casefold()
    ]
    if existing:
        raise LinearCliError(f"Project {project['name']} already has a milestone named {name!r}")
    milestone_input: dict[str, Any] = {"projectId": project["id"], "name": name}
    if args.description_file:
        milestone_input["description"] = _read_text(args.description_file)
    query = f"""
    mutation CodexLinearMilestoneCreate($input: ProjectMilestoneCreateInput!) {{
      projectMilestoneCreate(input: $input) {{ success projectMilestone {{ {MILESTONE_FIELDS} }} }}
    }}
    """
    payload = _graphql(credential, query, {"input": milestone_input}).get("projectMilestoneCreate", {})
    if not payload.get("success") or not isinstance(payload.get("projectMilestone"), dict):
        raise LinearCliError("Linear projectMilestoneCreate did not succeed")
    return payload["projectMilestone"]


def _project_milestone_update(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    project = _project(credential, args.project)
    milestone = _milestone(credential, project, args.milestone)
    milestone_input: dict[str, Any] = {}
    if args.name:
        milestone_input["name"] = args.name.strip()
    if args.description_file:
        milestone_input["description"] = _read_text(args.description_file)
    if not milestone_input:
        raise LinearCliError("Nothing to update: pass --name or --description-file")
    query = f"""
    mutation CodexLinearMilestoneUpdate($id: String!, $input: ProjectMilestoneUpdateInput!) {{
      projectMilestoneUpdate(id: $id, input: $input) {{ success projectMilestone {{ {MILESTONE_FIELDS} }} }}
    }}
    """
    payload = _graphql(
        credential, query, {"id": milestone["id"], "input": milestone_input}
    ).get("projectMilestoneUpdate", {})
    if not payload.get("success") or not isinstance(payload.get("projectMilestone"), dict):
        raise LinearCliError("Linear projectMilestoneUpdate did not succeed")
    return payload["projectMilestone"]


def _label_id(credential: Credential, name: str, team_id: str) -> str:
    query = """
    query CodexLinearLabels($name: String!) {
      issueLabels(first: 50, filter: { name: { eqIgnoreCase: $name } }) {
        nodes { id name team { id } }
      }
    }
    """
    nodes = _graphql(credential, query, {"name": name}).get("issueLabels", {}).get("nodes", [])
    team_labels = [node for node in nodes if (node.get("team") or {}).get("id") == team_id]
    workspace_labels = [node for node in nodes if not node.get("team")]
    candidates = team_labels or workspace_labels
    if len(candidates) != 1:
        raise LinearCliError(
            f"Expected one label named {name!r} in the issue team or workspace, found {len(candidates)}"
        )
    return candidates[0]["id"]


def _issue_update(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    issue = _issue(credential, args.issue)
    team_id = issue["team"]["id"]
    issue_input: dict[str, Any] = {}
    if args.state:
        states = [
            state
            for state in _team(credential, issue["team"]["key"]).get("states", {}).get("nodes", [])
            if str(state.get("name") or "").casefold() == args.state.strip().casefold()
        ]
        if len(states) != 1:
            raise LinearCliError(
                f"Expected one state named {args.state!r} in team {issue['team']['name']}, found {len(states)}"
            )
        issue_input["stateId"] = states[0]["id"]
    if args.add_label:
        issue_input["addedLabelIds"] = [_label_id(credential, name, team_id) for name in args.add_label]
    if args.remove_label:
        issue_input["removedLabelIds"] = [_label_id(credential, name, team_id) for name in args.remove_label]
    project = _project(credential, args.project) if args.project else None
    if project:
        issue_input["projectId"] = project["id"]
    if args.milestone:
        project = project or issue.get("project")
        if not project:
            raise LinearCliError(f"{issue['identifier']} has no project; pass --project with --milestone")
        issue_input["projectMilestoneId"] = _milestone(credential, project, args.milestone)["id"]
    if args.parent:
        issue_input["parentId"] = _issue(credential, args.parent)["id"]
    if not issue_input and not args.blocked_by:
        raise LinearCliError(
            "Nothing to update: pass --state, --add-label, --remove-label, --project, --milestone, "
            "--parent or --blocked-by"
        )
    if issue_input:
        query = """
        mutation CodexLinearIssueFieldsUpdate($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) { success }
        }
        """
        payload = _graphql(credential, query, {"id": issue["id"], "input": issue_input}).get("issueUpdate", {})
        if not payload.get("success"):
            raise LinearCliError("Linear issueUpdate did not succeed")
    for blocker in args.blocked_by:
        query = """
        mutation CodexLinearIssueRelation($input: IssueRelationCreateInput!) {
          issueRelationCreate(input: $input) { success }
        }
        """
        relation = {"issueId": _issue(credential, blocker)["id"], "relatedIssueId": issue["id"], "type": "blocks"}
        payload = _graphql(credential, query, {"input": relation}).get("issueRelationCreate", {})
        if not payload.get("success"):
            raise LinearCliError(f"Linear could not record that {blocker} blocks {issue['identifier']}")
    updated = _issue(credential, issue["id"])
    labels = {str(label["name"]).casefold() for label in updated.get("labels", {}).get("nodes", [])}
    if args.state and str(updated["state"]["name"]).casefold() != args.state.strip().casefold():
        raise LinearCliError(f"{updated['identifier']} did not move to state {args.state!r}")
    if any(name.casefold() not in labels for name in args.add_label):
        raise LinearCliError(f"{updated['identifier']} is missing an added label")
    if any(name.casefold() in labels for name in args.remove_label):
        raise LinearCliError(f"{updated['identifier']} still has a removed label")
    milestone = (updated.get("projectMilestone") or {}).get("name")
    if args.milestone and str(milestone or "").casefold() != args.milestone.strip().casefold():
        raise LinearCliError(f"{updated['identifier']} is not in milestone {args.milestone!r}")
    return updated


def _comment_list(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    issue = _issue(credential, args.issue)
    query = """
    query CodexLinearComments($id: String!, $after: String) {
      issue(id: $id) {
        comments(first: 100, after: $after) {
          nodes { id body url createdAt user { name displayName email } parent { id } }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    comments = _paginate(credential, query, {"id": issue["id"]}, ("issue", "comments"))
    comments.sort(key=lambda comment: str(comment.get("createdAt") or ""))
    return {"issue": issue["identifier"], "comments": comments}


def _canonical_block(description: str, prefix: str, name: str) -> str | None:
    start = f"<!-- {prefix}:{name}:start -->"
    end = f"<!-- {prefix}:{name}:end -->"
    if description.count(start) != 1 or description.count(end) != 1:
        return None
    begin = description.index(start) + len(start)
    finish = description.index(end)
    if finish < begin:
        return None
    return description[begin:finish].strip()


def spec_approval_marker(prefix: str, digest: str) -> str:
    return f"<!-- {prefix}:spec-approval sha256={digest} -->"


def spec_digest(description: str, prefix: str) -> dict[str, Any]:
    """Hash the canonical spec and tickets blocks exactly as Linear stores them."""
    spec = _canonical_block(description, prefix, "spec")
    tickets = _canonical_block(description, prefix, "tickets")
    spec_present = bool(spec and HTML_COMMENT_PATTERN.sub("", spec).strip())
    tickets_present = bool(tickets and HTML_COMMENT_PATTERN.sub("", tickets).strip())
    if not spec_present or not tickets_present:
        return {"specPresent": spec_present, "ticketsPresent": tickets_present, "specHash": None}
    digest = hashlib.sha256(f"{spec}\n<!-- tickets -->\n{tickets}".encode("utf-8")).hexdigest()
    return {"specPresent": True, "ticketsPresent": True, "specHash": digest}


def find_spec_approval(
    comments: list[dict[str, Any]], prefix: str, digest: str | None
) -> dict[str, Any]:
    marker = re.compile(rf"<!-- {re.escape(prefix)}:spec-approval sha256=([0-9a-f]{{64}}) -->")
    matching = None
    other_hashes = []
    for comment in comments:
        for found in marker.findall(str(comment.get("body") or "")):
            if digest and found == digest:
                matching = {key: comment.get(key) for key in ("id", "url", "createdAt", "body")}
            elif found not in other_hashes:
                other_hashes.append(found)
    return {"approval": matching, "otherApprovedHashes": other_hashes}


def _spec_approval(args: argparse.Namespace, credential: Credential) -> dict[str, Any]:
    _verify_identity(credential)
    issue = _issue(credential, args.issue)
    digest = spec_digest(str(issue.get("description") or ""), args.prefix)
    comments = _comment_list(args, credential)["comments"]
    found = find_spec_approval(comments, args.prefix, digest["specHash"])
    return {
        "issue": issue["identifier"],
        **digest,
        "approvalMarker": spec_approval_marker(args.prefix, digest["specHash"]) if digest["specHash"] else None,
        "approved": found["approval"] is not None,
        **found,
    }


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
    issue_fields = issue_commands.add_parser("update")
    issue_fields.add_argument("issue")
    issue_fields.add_argument("--state")
    issue_fields.add_argument("--add-label", action="append", default=[])
    issue_fields.add_argument("--remove-label", action="append", default=[])
    issue_fields.add_argument("--project")
    issue_fields.add_argument("--milestone")
    issue_fields.add_argument("--parent")
    issue_fields.add_argument("--blocked-by", action="append", default=[])
    issue_approval = issue_commands.add_parser("spec-approval")
    issue_approval.add_argument("issue")
    issue_approval.add_argument("--prefix", required=True)

    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_get = project_commands.add_parser("get")
    project_get.add_argument("project")
    project_issues = project_commands.add_parser("issues")
    project_issues.add_argument("project")
    project_content = project_commands.add_parser("update-content")
    project_content.add_argument("project")
    project_content.add_argument("--content-file", required=True)
    project_milestones = project_commands.add_parser("milestones")
    project_milestones.add_argument("project")
    milestone_create = project_commands.add_parser("milestone-create")
    milestone_create.add_argument("project")
    milestone_create.add_argument("--name", required=True)
    milestone_create.add_argument("--description-file")
    milestone_update = project_commands.add_parser("milestone-update")
    milestone_update.add_argument("project")
    milestone_update.add_argument("milestone")
    milestone_update.add_argument("--name")
    milestone_update.add_argument("--description-file")

    comment = commands.add_parser("comment")
    comment_commands = comment.add_subparsers(dest="comment_command", required=True)
    comment_create = comment_commands.add_parser("create")
    comment_create.add_argument("issue")
    comment_create.add_argument("--body-file", required=True)
    comment_list = comment_commands.add_parser("list")
    comment_list.add_argument("issue")

    request = commands.add_parser("request")
    request.add_argument("--file", required=True)
    return parser


def _run(args: argparse.Namespace) -> Any:
    credential = _read_environment_credential()
    if args.command == "whoami":
        return {
            "viewer": _viewer(credential),
            "credential": {"source": credential.source, "account": credential.account},
        }
    if args.command == "doctor":
        viewer = _verify_identity(credential)
        return {
            "ok": True,
            "credential": {"source": credential.source, "account": credential.account},
            "expectedWorkspace": credential.workspace or None,
            "viewer": viewer,
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
        if args.issue_command == "update":
            return _issue_update(args, credential)
        if args.issue_command == "spec-approval":
            return _spec_approval(args, credential)
        return _update_description(args, credential)
    if args.command == "project":
        if args.project_command == "get":
            _verify_identity(credential)
            return _project(credential, args.project)
        if args.project_command == "issues":
            _verify_identity(credential)
            return _project_issues(credential, args.project)
        if args.project_command == "milestones":
            return _project_milestone_list(args, credential)
        if args.project_command == "milestone-create":
            return _project_milestone_create(args, credential)
        if args.project_command == "milestone-update":
            return _project_milestone_update(args, credential)
        return _project_update_content(args, credential)
    if args.command == "comment":
        if args.comment_command == "list":
            return _comment_list(args, credential)
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

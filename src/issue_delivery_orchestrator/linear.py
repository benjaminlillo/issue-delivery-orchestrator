from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import OrchestrationError


@dataclass(frozen=True)
class LinearViewer:
    id: str
    name: str
    display_name: str
    email: str


@dataclass(frozen=True)
class LinearIssue:
    id: str
    identifier: str
    title: str
    branch_name: str
    description: str
    url: str


class LinearClient:
    API_URL = "https://api.linear.app/graphql"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def viewer(self) -> LinearViewer:
        data = self._graphql(
            "query OrchestrationViewer { viewer { id name displayName email } }",
            {},
        )["viewer"]
        return LinearViewer(
            id=data["id"],
            name=data.get("name") or "",
            display_name=data.get("displayName") or "",
            email=(data.get("email") or "").lower(),
        )

    def issue(self, identifier_or_url: str) -> LinearIssue:
        identifier = normalize_issue_identifier(identifier_or_url)
        query = """
        query OrchestrationIssue($id: String!) {
          issue(id: $id) {
            id
            identifier
            title
            branchName
            description
            url
          }
        }
        """
        data = self._graphql(query, {"id": identifier}).get("issue")
        if not data:
            raise OrchestrationError(f"Linear issue not found: {identifier_or_url}")
        branch_name = (data.get("branchName") or "").strip()
        if not branch_name:
            raise OrchestrationError(f"Linear issue {data['identifier']} has no git branch name")
        return LinearIssue(
            id=data["id"],
            identifier=data["identifier"],
            title=data["title"],
            branch_name=branch_name,
            description=data.get("description") or "",
            url=data.get("url") or "",
        )

    def post_comment(self, issue_id: str, body: str) -> None:
        query = """
        mutation OrchestrationComment($issueId: String!, $body: String!) {
          commentCreate(input: { issueId: $issueId, body: $body }) { success }
        }
        """
        data = self._graphql(query, {"issueId": issue_id, "body": body})
        if not data.get("commentCreate", {}).get("success"):
            raise OrchestrationError("Linear commentCreate did not succeed")

    def update_description(self, issue_id: str, description: str) -> None:
        query = """
        mutation OrchestrationIssueUpdate($id: String!, $description: String!) {
          issueUpdate(id: $id, input: { description: $description }) { success }
        }
        """
        data = self._graphql(query, {"id": issue_id, "description": description})
        if not data.get("issueUpdate", {}).get("success"):
            raise OrchestrationError("Linear issueUpdate did not succeed")

    def upload_file(self, path: Path) -> str:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        query = """
        mutation OrchestrationFileUpload($contentType: String!, $filename: String!, $size: Int!) {
          fileUpload(contentType: $contentType, filename: $filename, size: $size) {
            success
            uploadFile { uploadUrl assetUrl headers { key value } }
          }
        }
        """
        data = self._graphql(
            query,
            {"contentType": content_type, "filename": path.name, "size": path.stat().st_size},
        )
        payload = data.get("fileUpload", {})
        upload = payload.get("uploadFile") or {}
        if not payload.get("success") or not upload.get("uploadUrl") or not upload.get("assetUrl"):
            raise OrchestrationError(f"Linear fileUpload failed for {path.name}")
        headers = {item["key"]: item["value"] for item in upload.get("headers", [])}
        headers.setdefault("Content-Type", content_type)
        headers.setdefault("Cache-Control", "public, max-age=31536000")
        request = urllib.request.Request(
            upload["uploadUrl"],
            data=path.read_bytes(),
            headers=headers,
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=60):
                pass
        except urllib.error.URLError as error:
            raise OrchestrationError(f"Linear upload failed for {path.name}: {error}") from error
        return upload["assetUrl"]

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(
            self.API_URL,
            data=body,
            headers={"Authorization": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.URLError as error:
            raise OrchestrationError(f"Linear request failed: {error}") from error
        if payload.get("errors"):
            raise OrchestrationError(json.dumps(payload["errors"], sort_keys=True))
        return payload.get("data") or {}


def normalize_issue_identifier(value: str) -> str:
    candidate = value.strip().rstrip("/")
    direct = re.fullmatch(r"([A-Za-z][A-Za-z0-9]+-\d+)", candidate)
    match = direct or re.search(
        r"/issue/([A-Za-z][A-Za-z0-9]+-\d+)(?:/|$)",
        candidate,
        re.IGNORECASE,
    )
    if not match:
        raise OrchestrationError(f"Expected a Linear issue ID or URL, got: {value}")
    return match.group(1).upper()


def upsert_markdown_section(document: str, heading: str, body: str) -> str:
    heading_pattern = re.compile(rf"(?im)^## {re.escape(heading)}\s*$")
    match = heading_pattern.search(document)
    replacement = f"## {heading}\n\n{body.rstrip()}\n"
    if not match:
        return f"{document.rstrip()}\n\n{replacement}" if document.strip() else replacement
    following = re.search(r"(?m)^## .+$", document[match.end() :])
    end = match.end() + (following.start() if following else len(document[match.end() :]))
    return document[: match.start()] + replacement + document[end:].lstrip("\n")

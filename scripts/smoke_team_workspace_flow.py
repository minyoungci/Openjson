from __future__ import annotations

import argparse
import json
import time
from typing import Any

import httpx


class SmokeFailure(RuntimeError):
    pass


def _response_json(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception as exc:  # pragma: no cover - defensive for real HTTP failures
        raise SmokeFailure(f"{response.request.method} {response.request.url} returned non-JSON: {response.text}") from exc
    if not isinstance(body, dict):
        raise SmokeFailure(f"{response.request.method} {response.request.url} returned non-object JSON: {body!r}")
    return body


def _request(
    client: Any,
    method: str,
    path: str,
    *,
    token: str | None = None,
    expected_status: int = 200,
    **kwargs: Any,
) -> dict[str, Any]:
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
    if response.status_code != expected_status:
        raise SmokeFailure(f"{method} {path} -> {response.status_code}: {response.text}")
    return _response_json(response)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _password() -> str:
    return "local-password-123"


def run_team_workspace_smoke(client: Any, *, suffix: str | None = None) -> dict[str, Any]:
    suffix = suffix or str(int(time.time()))

    owner = _request(
        client,
        "POST",
        "/auth/signup",
        json={
            "email": f"team-owner-{suffix}@example.com",
            "display_name": "Team Smoke Owner",
            "password": _password(),
        },
    )
    teammate = _request(
        client,
        "POST",
        "/auth/signup",
        json={
            "email": f"team-editor-{suffix}@example.com",
            "display_name": "Team Smoke Editor",
            "password": _password(),
        },
    )

    owner_token = owner["token"]
    teammate_token = teammate["token"]
    workspace = _request(
        client,
        "POST",
        "/workspaces",
        token=owner_token,
        json={"name": f"Team Smoke Workspace {suffix}"},
    )
    project = _request(
        client,
        "POST",
        f"/workspaces/{workspace['id']}/projects",
        token=owner_token,
        json={"name": "Team Smoke Project", "description": "End-to-end team workflow smoke"},
    )
    invitation = _request(
        client,
        "POST",
        f"/projects/{project['id']}/invitations",
        token=owner_token,
        json={"email": teammate["user"]["email"], "role": "editor"},
    )
    accepted = _request(
        client,
        "POST",
        "/invitations/accept",
        token=teammate_token,
        json={"token": invitation["token"]},
    )
    _assert(accepted["member"]["role"] == "editor", f"Unexpected accepted role: {accepted}")

    members = _request(client, "GET", f"/projects/{project['id']}/members", token=owner_token)
    member_roles = {member["email"]: member["role"] for member in members["members"]}
    expected_roles = {
        owner["user"]["email"]: "owner",
        teammate["user"]["email"]: "editor",
    }
    _assert(member_roles == expected_roles, f"Unexpected member roles: {member_roles}")

    document = _request(
        client,
        "POST",
        f"/projects/{project['id']}/documents",
        token=owner_token,
        json={
            "full_path": f"team-smoke/config-{suffix}.json",
            "content": {
                "model": {"name": "baseline", "learning_rate": 0.001},
                "owner_reviewed": False,
            },
        },
    )
    _assert(document["current_version"] == 1, f"Document create did not return version 1: {document}")

    owner_state = _request(client, "GET", f"/documents/{document['id']}/editor-state", token=owner_token)
    teammate_state = _request(client, "GET", f"/documents/{document['id']}/editor-state", token=teammate_token)
    _assert(owner_state["editor"]["capabilities"]["can_patch"], "Owner cannot patch in editor state.")
    _assert(teammate_state["editor"]["capabilities"]["can_patch"], "Teammate cannot patch in editor state.")
    _assert(teammate_state["document"]["current_version"] == 1, f"Unexpected teammate base: {teammate_state}")

    edited_content = {
        "model": {"name": "baseline", "learning_rate": 0.0005},
        "owner_reviewed": False,
    }
    teammate_save = _request(
        client,
        "PUT",
        f"/documents/{document['id']}/content",
        token=teammate_token,
        json={
            "base_version": teammate_state["editor"]["required_base_version"],
            "content": edited_content,
            "reason": "Team smoke teammate save",
        },
    )
    _assert(teammate_save["current_version"] == 2, f"Unexpected teammate save result: {teammate_save}")
    event_id = teammate_save["event_id"]

    collaboration = _request(
        client,
        "GET",
        f"/documents/{document['id']}/collaboration-state",
        token=owner_token,
        params={"since_version": 1},
    )
    checkpoints = collaboration["checkpoints"]
    _assert(checkpoints, f"Collaboration state did not report checkpoint: {collaboration}")
    _assert(checkpoints[0]["event_id"] == event_id, f"Checkpoint did not match save event: {collaboration}")
    _assert(checkpoints[0]["display_name"] == teammate["user"]["display_name"], f"Checkpoint actor name missing: {checkpoints[0]}")

    before_note = _request(client, "GET", f"/documents/{document['id']}", token=owner_token)
    note = _request(
        client,
        "POST",
        f"/documents/{document['id']}/comment-threads",
        token=owner_token,
        json={
            "anchor_type": "path",
            "path": "/model/learning_rate",
            "body": "Please confirm the training value.",
        },
    )
    reply = _request(
        client,
        "POST",
        f"/comment-threads/{note['id']}/comments",
        token=teammate_token,
        json={"body": "Confirmed in the team smoke flow."},
    )
    resolved = _request(client, "POST", f"/comment-threads/{note['id']}/resolve", token=owner_token)
    reopened = _request(client, "POST", f"/comment-threads/{note['id']}/reopen", token=owner_token)
    _assert(reply["thread_id"] == note["id"], f"Reply attached to wrong thread: {reply}")
    _assert(resolved["status"] == "resolved", f"Resolve failed: {resolved}")
    _assert(reopened["status"] == "open", f"Reopen failed: {reopened}")
    _assert(len(reopened["comments"]) == 2, f"Unexpected note comment count: {reopened}")

    after_note = _request(client, "GET", f"/documents/{document['id']}", token=owner_token)
    _assert(after_note["current_version"] == before_note["current_version"], "Notes changed the document version.")
    _assert(after_note["content"] == before_note["content"], "Notes changed the document snapshot.")

    listed_notes = _request(client, "GET", f"/documents/{document['id']}/comment-threads", token=teammate_token)
    _assert(len(listed_notes["threads"]) == 1, f"Unexpected listed note count: {listed_notes}")
    _assert(listed_notes["threads"][0]["path"] == "/model/learning_rate", f"Unexpected note anchor: {listed_notes}")

    diff = _request(
        client,
        "GET",
        f"/documents/{document['id']}/diff",
        token=owner_token,
        params={"from_version": 1, "to_version": 2},
    )
    diff_paths = {change["path"] for change in diff["changes"]}
    _assert("/model/learning_rate" in diff_paths, f"Diff missing learning_rate path: {diff}")

    replay = _request(client, "GET", f"/documents/{document['id']}/integrity/replay", token=owner_token)
    _assert(replay["status"] == "ok", f"Replay consistency failed: {replay}")

    return {
        "status": "ok",
        "owner_id": owner["user"]["id"],
        "teammate_id": teammate["user"]["id"],
        "workspace_id": workspace["id"],
        "project_id": project["id"],
        "document_id": document["id"],
        "member_roles": member_roles,
        "versions": {
            "created": document["current_version"],
            "teammate_save": teammate_save["current_version"],
            "after_notes": after_note["current_version"],
        },
        "checkpoint_event_id": checkpoints[0]["event_id"],
        "note_thread_id": note["id"],
        "note_status_after_reopen": reopened["status"],
        "note_comment_count": len(reopened["comments"]),
        "diff_paths": sorted(diff_paths),
        "replay_status": replay["status"],
    }


def run_smoke(base_url: str, *, suffix: str | None = None) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15) as client:
        return run_team_workspace_smoke(client, suffix=suffix)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test OpenJson team workspace onboarding, editing, notes, diff, and replay.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--suffix", default=None)
    args = parser.parse_args()

    print(json.dumps(run_smoke(args.base_url, suffix=args.suffix), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

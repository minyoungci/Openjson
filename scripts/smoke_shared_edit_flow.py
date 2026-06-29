from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class SmokeFailure(AssertionError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    body: Any


class UrllibJsonClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> HttpResult:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        data = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if json_body is not None:
            data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return HttpResult(response.status, _decode_body(response.read()))
        except error.HTTPError as exc:
            return HttpResult(exc.code, _decode_body(exc.read()))


def _decode_body(raw: bytes) -> Any:
    text = raw.decode("utf-8")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _expect_status(result: HttpResult, expected_status: int, step: str) -> Any:
    if result.status_code != expected_status:
        raise SmokeFailure(
            f"{step}: expected HTTP {expected_status}, got {result.status_code}: "
            f"{json.dumps(result.body, ensure_ascii=False, sort_keys=True)}"
        )
    return result.body


def _expect_error_code(result: HttpResult, expected_status: int, expected_code: str, step: str) -> dict[str, Any]:
    body = _expect_status(result, expected_status, step)
    code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    if code != expected_code:
        raise SmokeFailure(f"{step}: expected error code {expected_code}, got {code}: {body}")
    return body


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _request(
    client: Any,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    params: dict[str, Any] | None = None,
) -> HttpResult:
    return client.request_json(method, path, headers=headers, json_body=json_body, params=params)


def run_shared_edit_smoke(client: Any, *, suffix: str | None = None) -> dict[str, Any]:
    suffix = suffix or uuid.uuid4().hex[:12]

    _expect_status(_request(client, "GET", "/health"), 200, "health")

    owner = _expect_status(
        _request(
            client,
            "POST",
            "/users",
            json_body={
                "email": f"owner-{suffix}@example.com",
                "display_name": f"Owner {suffix}",
            },
        ),
        200,
        "create owner",
    )
    editor = _expect_status(
        _request(
            client,
            "POST",
            "/users",
            json_body={
                "email": f"editor-{suffix}@example.com",
                "display_name": f"Editor {suffix}",
            },
        ),
        200,
        "create editor",
    )
    owner_headers = {"X-Actor-Id": owner["id"]}
    editor_headers = {"X-Actor-Id": editor["id"]}

    workspace = _expect_status(
        _request(
            client,
            "POST",
            "/workspaces",
            headers=owner_headers,
            json_body={"name": f"Shared Edit Smoke {suffix}"},
        ),
        200,
        "create workspace",
    )
    project = _expect_status(
        _request(
            client,
            "POST",
            f"/workspaces/{workspace['id']}/projects",
            headers=owner_headers,
            json_body={"name": f"Shared Edit Project {suffix}"},
        ),
        200,
        "create project",
    )
    _expect_status(
        _request(
            client,
            "POST",
            f"/projects/{project['id']}/members",
            headers=owner_headers,
            json_body={"user_id": editor["id"], "role": "editor"},
        ),
        200,
        "add editor member",
    )

    document = _expect_status(
        _request(
            client,
            "POST",
            f"/projects/{project['id']}/documents",
            headers=owner_headers,
            json_body={
                "full_path": f"config/shared-edit-{suffix}.json",
                "content": {"value": 1, "label": "initial"},
            },
        ),
        200,
        "create document",
    )
    document_id = document["id"]
    _require(document["event_type"] == "create", "create response must expose event_type=create")

    owner_state = _expect_status(
        _request(client, "GET", f"/documents/{document_id}/editor-state", headers=owner_headers),
        200,
        "owner editor-state",
    )
    editor_state = _expect_status(
        _request(client, "GET", f"/documents/{document_id}/editor-state", headers=editor_headers),
        200,
        "editor editor-state",
    )
    _require(owner_state["editor"]["required_base_version"] == 1, "owner initial base version must be 1")
    _require(editor_state["editor"]["required_base_version"] == 1, "editor initial base version must be 1")
    _require(owner_state["workflow"]["mode"] == "non_realtime_versioned_edit", "editor-state must expose workflow mode")
    _require(owner_state["workflow"]["required_base_version"] == 1, "workflow must expose required base version")
    _require(owner_state["workflow"]["actions"]["save_content"]["endpoint"] == f"/documents/{document_id}/content", "workflow must expose content save endpoint")
    _require(owner_state["workflow"]["actions"]["save_content"]["creates_document_event"] is True, "workflow content save must create document events")
    _require(
        owner_state["workflow"]["actions"]["preview_content_conflict"]["endpoint"]
        == f"/documents/{document_id}/content-conflict-preview",
        "workflow must expose content conflict preview endpoint",
    )
    _require(
        owner_state["workflow"]["actions"]["preview_content_conflict"]["read_only"] is True,
        "workflow content conflict preview must be read-only",
    )
    _require(
        "POST /documents/{document_id}/content-conflict-preview"
        in owner_state["workflow"]["save_contract"]["recovery"],
        "workflow save contract must include conflict preview recovery",
    )
    _require(
        owner_state["workflow"]["state_machine"]["initial_state"] == "clean",
        "workflow state machine must start writable actors in clean state",
    )
    _require(
        "save_content" in owner_state["workflow"]["state_machine"]["states"]["preview_ready"]["allowed_actions"],
        "workflow preview_ready state must allow content save for writable actors",
    )
    _require(
        owner_state["workflow"]["state_machine"]["event_creation"]["only_on"] == ["save_success"],
        "workflow state machine must limit event creation to accepted saves",
    )

    bootstrap = _expect_status(
        _request(
            client,
            "GET",
            f"/projects/{project['id']}/editor-bootstrap",
            headers=owner_headers,
            params={"selected_document_id": document_id, "path_prefix": "config", "q": "shared", "recent_events_limit": 1},
        ),
        200,
        "project editor bootstrap",
    )
    _require(bootstrap["bootstrap"]["mode"] == "project_editor_bootstrap", "bootstrap must expose project editor mode")
    _require(bootstrap["bootstrap"]["read_only"] is True, "bootstrap must be read-only")
    _require(
        bootstrap["bootstrap"]["event_creation"]["creates_document_event"] is False,
        "bootstrap must not create document events",
    )
    _require(bootstrap["project"]["id"] == project["id"], "bootstrap must identify project")
    _require(bootstrap["actor"]["id"] == owner["id"], "bootstrap must identify actor")
    _require(
        [item["id"] for item in bootstrap["documents"]["documents"]] == [document_id],
        "bootstrap document list must include the created document",
    )
    _require(
        bootstrap["document_tree"]["root"]["path"] == "config",
        "bootstrap document tree must respect path_prefix",
    )
    _require(
        bootstrap["selected_document_editor_state"]["document"]["id"] == document_id,
        "bootstrap selected editor-state must identify selected document",
    )
    _require(
        bootstrap["selected_document_editor_state"]["editor"]["required_base_version"] == 1,
        "bootstrap selected editor-state must expose current base version",
    )

    owner_save = _expect_status(
        _request(
            client,
            "PATCH",
            f"/documents/{document_id}",
            headers=owner_headers,
            json_body={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "shared edit smoke owner save",
            },
        ),
        200,
        "owner save",
    )
    _require(owner_save["current_version"] == 2, "owner save must advance document to version 2")
    _require(owner_save["event_type"] == "update", "owner save must create an update event")

    stale_preview = _request(
        client,
        "POST",
        f"/documents/{document_id}/patch-preview",
        headers=editor_headers,
        json_body={"base_version": 1, "patch": [{"op": "replace", "path": "/label", "value": "editor"}]},
    )
    stale_save = _request(
        client,
        "PATCH",
        f"/documents/{document_id}",
        headers=editor_headers,
        json_body={
            "base_version": 1,
            "patch": [{"op": "replace", "path": "/label", "value": "editor"}],
            "reason": "shared edit smoke stale editor save",
        },
    )
    stale_conflict_preview = _request(
        client,
        "POST",
        f"/documents/{document_id}/content-conflict-preview",
        headers=editor_headers,
        json_body={"base_version": 1, "content": {"value": 1, "label": "editor"}},
    )
    stale_preview_body = _expect_error_code(stale_preview, 409, "VERSION_CONFLICT", "stale editor preview")
    stale_save_body = _expect_error_code(stale_save, 409, "VERSION_CONFLICT", "stale editor save")
    stale_conflict_body = _expect_status(stale_conflict_preview, 200, "stale editor content conflict preview")
    stale_preview_details = stale_preview_body["error"]["details"]
    stale_save_details = stale_save_body["error"]["details"]
    expected_reload = {"method": "GET", "endpoint": f"/documents/{document_id}/editor-state"}
    _require(
        stale_save_details["client_base_version"] == 1 and stale_save_details["server_current_version"] == 2,
        "stale save conflict details must identify client and server versions",
    )
    _require(stale_save_details["document_id"] == document_id, "stale save conflict details must identify document")
    _require(stale_save_details["project_id"] == project["id"], "stale save conflict details must identify project")
    _require(stale_save_details["full_path"] == document["full_path"], "stale save conflict details must identify path")
    _require(stale_save_details["reload"] == expected_reload, "stale save conflict details must include reload hint")
    _require(
        stale_save_details["latest_event"]["id"] == owner_save["event_id"],
        "stale save conflict details must identify latest accepted event",
    )
    _require(
        stale_save_details["latest_event"]["event_type"] == "update",
        "stale save conflict details must identify latest event type",
    )
    _require(
        stale_preview_details["latest_event"]["id"] == owner_save["event_id"],
        "stale preview conflict details must identify latest accepted event",
    )
    _require(stale_conflict_body["persisted"] is False, "content conflict preview must be read-only")
    _require(stale_conflict_body["base_version"] == 1, "content conflict preview must keep stale base version")
    _require(stale_conflict_body["current_version"] == 2, "content conflict preview must report latest version")
    _require(stale_conflict_body["has_conflicts"] is False, "label-only stale candidate must not conflict with value-only server change")
    _require(
        stale_conflict_body["client_changes"] == [
            {"path": "/label", "change_type": "modified", "before": "initial", "after": "editor"}
        ],
        "content conflict preview must report client-side candidate changes from base",
    )
    _require(
        stale_conflict_body["server_changes"] == [
            {"path": "/value", "change_type": "modified", "before": 1, "after": 2}
        ],
        "content conflict preview must report accepted server changes from base",
    )

    reloaded = _expect_status(
        _request(
            client,
            "GET",
            f"/documents/{document_id}/editor-state",
            headers=editor_headers,
            params={"recent_events_limit": 1},
        ),
        200,
        "editor reload editor-state",
    )
    _require(reloaded["editor"]["required_base_version"] == 2, "editor reload must expose base version 2")
    _require(reloaded["recent_events"][0]["id"] == owner_save["event_id"], "recent event must be owner save event")

    preview = _expect_status(
        _request(
            client,
            "POST",
            f"/documents/{document_id}/patch-preview",
            headers=editor_headers,
            json_body={"base_version": 2, "patch": [{"op": "replace", "path": "/label", "value": "editor"}]},
        ),
        200,
        "editor preview after reload",
    )
    _require(preview["persisted"] is False, "patch preview must be read-only")
    _require(preview["candidate_content"] == {"value": 2, "label": "editor"}, "preview candidate must match expected content")

    editor_save = _expect_status(
        _request(
            client,
            "PATCH",
            f"/documents/{document_id}",
            headers=editor_headers,
            json_body={
                "base_version": 2,
                "patch": [{"op": "replace", "path": "/label", "value": "editor"}],
                "reason": "shared edit smoke editor save after reload",
            },
        ),
        200,
        "editor save after reload",
    )
    _require(editor_save["current_version"] == 3, "editor save must advance document to version 3")
    _require(editor_save["content"] == {"value": 2, "label": "editor"}, "final document content must match expected content")

    history = _expect_status(
        _request(client, "GET", f"/documents/{document_id}/history", headers=owner_headers),
        200,
        "history",
    )
    events = history["events"]
    _require([event["event_type"] for event in events] == ["create", "update", "update"], "history must contain create/update/update")
    _require(events[1]["id"] == owner_save["event_id"], "owner save event id must match history")
    _require(events[2]["id"] == editor_save["event_id"], "editor save event id must match history")

    replay = _expect_status(
        _request(client, "GET", f"/documents/{document_id}/integrity/replay", headers=owner_headers),
        200,
        "replay integrity",
    )
    _require(replay["status"] == "ok", "replay integrity must be ok")
    _require(replay["document"]["replay_matches_latest"] is True, "replay must match latest snapshot")

    return {
        "status": "ok",
        "owner_actor_id": owner["id"],
        "editor_actor_id": editor["id"],
        "workspace_id": workspace["id"],
        "project_id": project["id"],
        "document_id": document_id,
        "final_version": editor_save["current_version"],
        "owner_event_id": owner_save["event_id"],
        "editor_event_id": editor_save["event_id"],
        "workflow_mode": owner_state["workflow"]["mode"],
        "workflow_save_content_endpoint": owner_state["workflow"]["actions"]["save_content"]["endpoint"],
        "workflow_conflict_preview_endpoint": owner_state["workflow"]["actions"]["preview_content_conflict"]["endpoint"],
        "workflow_initial_state": owner_state["workflow"]["state_machine"]["initial_state"],
        "workflow_event_creation_only_on": owner_state["workflow"]["state_machine"]["event_creation"]["only_on"],
        "bootstrap_mode": bootstrap["bootstrap"]["mode"],
        "bootstrap_selected_document_id": bootstrap["selected_document_editor_state"]["document"]["id"],
        "bootstrap_document_count": bootstrap["documents"]["pagination"]["total"],
        "bootstrap_tree_root": bootstrap["document_tree"]["root"]["path"],
        "bootstrap_creates_document_event": bootstrap["bootstrap"]["event_creation"]["creates_document_event"],
        "stale_preview_error_code": stale_preview_body["error"]["code"],
        "stale_save_error_code": stale_save_body["error"]["code"],
        "stale_conflict_preview_has_conflicts": stale_conflict_body["has_conflicts"],
        "stale_conflict_preview_client_paths": [change["path"] for change in stale_conflict_body["client_changes"]],
        "stale_conflict_preview_server_paths": [change["path"] for change in stale_conflict_body["server_changes"]],
        "stale_save_latest_event_id": stale_save_details["latest_event"]["id"],
        "stale_save_reload_endpoint": stale_save_details["reload"]["endpoint"],
        "history_event_types": [event["event_type"] for event in events],
        "replay_status": replay["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the non-realtime shared JSON edit HTTP smoke flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL for a running OpenJson API server.")
    parser.add_argument("--suffix", default=None, help="Optional unique suffix for generated users and paths.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="HTTP timeout in seconds.")
    args = parser.parse_args(argv)

    client = UrllibJsonClient(args.base_url, timeout_seconds=args.timeout_seconds)
    try:
        result = run_shared_edit_smoke(client, suffix=args.suffix)
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

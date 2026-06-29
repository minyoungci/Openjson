from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any
from urllib.parse import quote

import httpx
import websockets


def _require(response: httpx.Response, expected_status: int = 200) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}")
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _websocket_smoke(base_url: str, document_id: str, token: str) -> dict[str, Any]:
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
    ws_url = f"{ws_base}/ws/documents/{quote(document_id)}/collaboration?token={quote(token)}"
    async with websockets.connect(ws_url) as websocket:
        initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        if initial.get("type") != "collaboration_state":
            raise RuntimeError(f"Unexpected websocket initial payload: {initial}")
        await websocket.send(json.dumps({"type": "ping"}))
        for _ in range(5):
            payload = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
            if payload.get("type") == "pong":
                return initial
        raise RuntimeError("WebSocket pong not received.")


def run_smoke(base_url: str) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    suffix = str(int(time.time()))
    with httpx.Client(base_url=base_url, timeout=10) as client:
        owner = _require(
            client.post(
                "/auth/signup",
                json={
                    "email": f"task103-owner-{suffix}@example.com",
                    "display_name": "Task103 Owner",
                    "password": "local-password-123",
                },
            )
        )
        editor = _require(
            client.post(
                "/auth/signup",
                json={
                    "email": f"task103-editor-{suffix}@example.com",
                    "display_name": "Task103 Editor",
                    "password": "local-password-123",
                },
            )
        )
        owner_headers = _headers(owner["token"])
        editor_headers = _headers(editor["token"])

        workspace = _require(client.post("/workspaces", headers=owner_headers, json={"name": f"TASK103 Smoke {suffix}"}))
        project = _require(
            client.post(
                f"/workspaces/{workspace['id']}/projects",
                headers=owner_headers,
                json={"name": "Realtime Ready Project"},
            )
        )
        invitation = _require(
            client.post(
                f"/projects/{project['id']}/invitations",
                headers=owner_headers,
                json={"email": editor["user"]["email"], "role": "editor"},
            )
        )
        accepted = _require(
            client.post(
                "/invitations/accept",
                headers=editor_headers,
                json={"token": invitation["token"]},
            )
        )

        document = _require(
            client.post(
                f"/projects/{project['id']}/documents",
                headers=owner_headers,
                json={
                    "full_path": f"smoke/task103-{suffix}.json",
                    "content": {"a": 1, "b": 1, "items": [{"value": 1}]},
                },
            )
        )
        loaded = _require(client.get(f"/documents/{document['id']}", headers=owner_headers))
        if loaded["current_version"] != 1:
            raise RuntimeError(f"Expected initial version 1, got {loaded['current_version']}")

        server_update = _require(
            client.put(
                f"/documents/{document['id']}/content",
                headers=editor_headers,
                json={
                    "base_version": 1,
                    "content": {"a": 1, "b": 2, "items": [{"value": 1}]},
                    "reason": "server side edit",
                },
            )
        )
        merged = _require(
            client.put(
                f"/documents/{document['id']}/content",
                headers=owner_headers,
                json={
                    "base_version": 1,
                    "content": {"a": 2, "b": 1, "items": [{"value": 1}]},
                    "merge_strategy": "auto",
                    "reason": "safe smoke auto merge",
                },
            )
        )
        if not merged.get("auto_merged") or merged["current_version"] != 3:
            raise RuntimeError(f"Auto-merge failed: {merged}")

        latest = _require(client.get(f"/documents/{document['id']}", headers=owner_headers))
        expected_latest = {"a": 2, "b": 2, "items": [{"value": 1}]}
        if latest["content"] != expected_latest:
            raise RuntimeError(f"Unexpected latest content: {latest['content']}")

        history = _require(client.get(f"/documents/{document['id']}/history", headers=owner_headers))
        diff = _require(
            client.get(
                f"/documents/{document['id']}/diff",
                headers=owner_headers,
                params={"from_version": 1, "to_version": 3},
            )
        )
        diff_paths = {change["path"] for change in diff["changes"]}
        if not {"/a", "/b"}.issubset(diff_paths):
            raise RuntimeError(f"Diff missing expected paths: {diff}")

        websocket_initial = asyncio.run(_websocket_smoke(base_url, document["id"], owner["token"]))

        rollback = _require(
            client.post(
                f"/documents/{document['id']}/rollback",
                headers=owner_headers,
                json={"base_version": 3, "target_version": 2, "reason": "smoke rollback"},
            )
        )
        after_rollback = _require(client.get(f"/documents/{document['id']}", headers=owner_headers))
        expected_rollback = {"a": 1, "b": 2, "items": [{"value": 1}]}
        if after_rollback["current_version"] != 4 or after_rollback["content"] != expected_rollback:
            raise RuntimeError(f"Unexpected rollback result: {after_rollback}")

        replay = _require(client.get(f"/documents/{document['id']}/integrity/replay", headers=owner_headers))
        if replay["status"] != "ok":
            raise RuntimeError(f"Replay failed: {replay}")

    return {
        "status": "ok",
        "owner_id": owner["user"]["id"],
        "editor_id": editor["user"]["id"],
        "workspace_id": workspace["id"],
        "project_id": project["id"],
        "document_id": document["id"],
        "accepted_member_role": accepted["member"]["role"],
        "versions": {
            "created": document["current_version"],
            "server_update": server_update["current_version"],
            "auto_merge": merged["current_version"],
            "rollback": rollback["current_version"],
        },
        "history_events": len(history["events"]),
        "diff_paths": sorted(diff_paths),
        "websocket_initial_type": websocket_initial["type"],
        "replay_status": replay["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test TASK_103 session, invitation, auto-merge, websocket, and replay flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    result = run_smoke(args.base_url)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import json
import time
from urllib.parse import quote

import httpx
import websockets


def _require(response: httpx.Response, expected_status: int = 200) -> dict:
    if response.status_code != expected_status:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}")
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _text_session_commit(base_url: str, document_id: str, token: str) -> dict:
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
    async with websockets.connect(f"{ws_base}/ws/documents/{quote(document_id)}/collaboration?token={quote(token)}") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "text_session.join"}))
        state = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        index = state["content_text"].index("1")
        await ws.send(
            json.dumps(
                {
                    "type": "text_session.op",
                    "client_id": "smoke-task104",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "replace", "index": index, "length": 1, "text": "2"},
                }
            )
        )
        accepted = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        await ws.send(json.dumps({"type": "text_session.commit", "text_revision": accepted["server_text_revision"]}))
        for _ in range(5):
            payload = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if payload.get("type") == "text_session.committed":
                return payload
        raise RuntimeError("text_session.committed was not received")


def run_smoke(base_url: str) -> dict:
    base_url = base_url.rstrip("/")
    suffix = str(int(time.time()))
    with httpx.Client(base_url=base_url, timeout=10) as client:
        owner = _require(
            client.post(
                "/auth/signup",
                json={
                    "email": f"task104-owner-{suffix}@example.com",
                    "display_name": "Task104 Owner",
                    "password": "local-password-123",
                },
            )
        )
        refreshed = _require(client.post("/auth/refresh", json={"refresh_token": owner["refresh_token"]}))
        owner = refreshed
        headers = _headers(owner["token"])
        workspace = _require(client.post("/workspaces", headers=headers, json={"name": f"TASK104 Smoke {suffix}"}))
        project = _require(client.post(f"/workspaces/{workspace['id']}/projects", headers=headers, json={"name": "Project"}))
        invitation = _require(
            client.post(
                f"/projects/{project['id']}/invitations",
                headers=headers,
                json={"email": f"task104-editor-{suffix}@example.com", "role": "editor", "send_email": True},
            )
        )
        document = _require(
            client.post(
                f"/projects/{project['id']}/documents",
                headers=headers,
                json={"full_path": f"task104/live-{suffix}.json", "content": {"value": 1, "offline": False}},
            )
        )
        committed = asyncio.run(_text_session_commit(base_url, document["id"], owner["token"]))
        offline = _require(
            client.post(
                f"/projects/{project['id']}/offline-sync",
                headers=headers,
                json={
                    "items": [
                        {
                            "client_operation_id": f"offline-{suffix}",
                            "document_id": document["id"],
                            "base_version": committed["result_version"],
                            "content_text": "{\"offline\":true,\"value\":2}",
                        }
                    ]
                },
            )
        )
        replay = _require(client.get(f"/documents/{document['id']}/integrity/replay", headers=headers))
    return {
        "status": "ok",
        "project_id": project["id"],
        "document_id": document["id"],
        "refresh_session_id": owner["session"]["id"],
        "invitation_email_status": invitation["email_delivery"]["status"],
        "text_commit_version": committed["result_version"],
        "offline_summary": offline["summary"],
        "replay_status": replay["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke TASK_104 collaboration/auth/offline flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.base_url), indent=2))


if __name__ == "__main__":
    main()

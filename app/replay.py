from __future__ import annotations

from typing import Any

from app.errors import AppError, ErrorCode
from app.json_patch import PatchApplyError, apply_patch
from app.json_pointer import join_pointer


def replay_events(events: list[dict[str, Any]], target_version: int | None = None) -> Any:
    state: Any = None
    seen_create = False
    for event in sorted(events, key=lambda item: item["result_version"]):
        if target_version is not None and event["result_version"] > target_version:
            break
        patch = event["patch"]
        if not patch:
            continue
        try:
            state = apply_patch(state if seen_create else None, patch).document
        except PatchApplyError as exc:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Stored document event replay failed.",
                {"event_id": event["id"], "message": str(exc)},
            ) from exc
        seen_create = True
    if target_version is not None:
        matching_versions = {event["result_version"] for event in events}
        if target_version not in matching_versions:
            raise AppError(
                ErrorCode.DOCUMENT_VERSION_NOT_FOUND,
                "Document version not found.",
                {"target_version": target_version},
            )
    return state


def diff_json(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(before.keys() | after.keys()):
            child_path = join_pointer(path, str(key))
            if key not in before:
                changes.append(
                    {
                        "path": child_path,
                        "change_type": "added",
                        "before": None,
                        "after": after[key],
                    }
                )
            elif key not in after:
                changes.append(
                    {
                        "path": child_path,
                        "change_type": "removed",
                        "before": before[key],
                        "after": None,
                    }
                )
            else:
                changes.extend(diff_json(before[key], after[key], child_path))
        return changes

    if isinstance(before, list) and isinstance(after, list):
        changes = []
        common_length = min(len(before), len(after))
        for index in range(common_length):
            changes.extend(diff_json(before[index], after[index], join_pointer(path, str(index))))
        for index in range(common_length, len(after)):
            changes.append(
                {
                    "path": join_pointer(path, str(index)),
                    "change_type": "added",
                    "before": None,
                    "after": after[index],
                }
            )
        for index in range(common_length, len(before)):
            changes.append(
                {
                    "path": join_pointer(path, str(index)),
                    "change_type": "removed",
                    "before": before[index],
                    "after": None,
                }
            )
        return changes

    if before != after:
        return [
            {
                "path": path,
                "change_type": "modified",
                "before": before,
                "after": after,
            }
        ]
    return []

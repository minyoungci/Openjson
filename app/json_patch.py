from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.json_pointer import JsonPointerError, MISSING, escape_segment, get_value, parse_pointer


class PatchApplyError(ValueError):
    pass


class UnsupportedPatchOperationError(PatchApplyError):
    pass


@dataclass(frozen=True)
class PatchResult:
    document: Any
    inverse_patch: list[dict[str, Any]]
    changed_paths: list[str]
    before_values: list[dict[str, Any]]
    after_values: list[dict[str, Any]]


def _tracked_value(path: str, exists: bool, value: Any = None) -> dict[str, Any]:
    return {"path": path, "exists": exists, "value": deepcopy(value) if exists else None}


def _parent_and_token(document: Any, path: str) -> tuple[Any, str]:
    tokens = parse_pointer(path)
    if not tokens:
        return MISSING, ""
    parent = document
    for token in tokens[:-1]:
        if isinstance(parent, dict):
            if token not in parent:
                raise PatchApplyError(f"Object key not found: {token}")
            parent = parent[token]
            continue
        if isinstance(parent, list):
            parent = parent[_array_index_for_patch(token, len(parent))]
            continue
        raise PatchApplyError("Cannot traverse into scalar JSON value.")
    return parent, tokens[-1]


def _array_index_for_patch(token: str, length: int, allow_end: bool = False) -> int:
    if token == "-" and allow_end:
        return length
    if token == "":
        raise PatchApplyError("Array index cannot be empty.")
    try:
        index = int(token)
    except ValueError as exc:
        raise PatchApplyError(f"Invalid array index: {token}") from exc
    upper_bound = length if allow_end else length - 1
    if index < 0 or index > upper_bound:
        raise PatchApplyError(f"Array index out of range: {token}")
    return index


def _value_at_path(document: Any, path: str) -> tuple[bool, Any]:
    try:
        return True, get_value(document, path)
    except JsonPointerError:
        return False, None


def _concrete_array_path(path: str, index: int) -> str:
    tokens = parse_pointer(path)
    tokens[-1] = str(index)
    return "/" + "/".join(escape_segment(token) for token in tokens)


def _apply_single(document: Any, operation: dict[str, Any]) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    op = operation.get("op")
    path = operation.get("path")
    if op not in {"add", "replace", "remove"}:
        raise UnsupportedPatchOperationError(f"Unsupported patch operation: {op}")
    if not isinstance(path, str):
        raise PatchApplyError("Patch operation requires a JSON Pointer path.")

    before_exists, before_value = _value_at_path(document, path)
    before_record = _tracked_value(path, before_exists, before_value)

    if path == "":
        if op == "remove":
            raise PatchApplyError("Removing the document root is not allowed for canonical snapshots.")
        if op == "replace" and not before_exists:
            raise PatchApplyError("Cannot replace a missing document root.")
        if "value" not in operation:
            raise PatchApplyError(f"{op} operation requires a value.")
        new_document = deepcopy(operation["value"])
        inverse = {"op": "replace" if before_exists else "remove", "path": path}
        if before_exists:
            inverse["value"] = before_value
        after_record = _tracked_value(path, True, new_document)
        return new_document, inverse, before_record, after_record

    parent, token = _parent_and_token(document, path)
    if parent is MISSING:
        raise PatchApplyError("Invalid patch parent.")

    if isinstance(parent, dict):
        new_document = document
        if op == "remove":
            if token not in parent:
                raise PatchApplyError(f"Object key not found: {token}")
            old_value = deepcopy(parent.pop(token))
            inverse = {"op": "add", "path": path, "value": old_value}
        elif op == "replace":
            if token not in parent:
                raise PatchApplyError(f"Object key not found: {token}")
            if "value" not in operation:
                raise PatchApplyError("replace operation requires a value.")
            old_value = deepcopy(parent[token])
            parent[token] = deepcopy(operation["value"])
            inverse = {"op": "replace", "path": path, "value": old_value}
        else:
            if "value" not in operation:
                raise PatchApplyError("add operation requires a value.")
            old_exists = token in parent
            old_value = deepcopy(parent[token]) if old_exists else None
            parent[token] = deepcopy(operation["value"])
            inverse = {"op": "replace", "path": path, "value": old_value} if old_exists else {"op": "remove", "path": path}
        after_exists, after_value = _value_at_path(new_document, path)
        return new_document, inverse, before_record, _tracked_value(path, after_exists, after_value)

    if isinstance(parent, list):
        new_document = document
        if op == "remove":
            index = _array_index_for_patch(token, len(parent))
            old_value = deepcopy(parent.pop(index))
            inverse = {"op": "add", "path": path, "value": old_value}
        elif op == "replace":
            index = _array_index_for_patch(token, len(parent))
            if "value" not in operation:
                raise PatchApplyError("replace operation requires a value.")
            old_value = deepcopy(parent[index])
            parent[index] = deepcopy(operation["value"])
            inverse = {"op": "replace", "path": path, "value": old_value}
        else:
            if "value" not in operation:
                raise PatchApplyError("add operation requires a value.")
            index = _array_index_for_patch(token, len(parent), allow_end=True)
            concrete_path = path if token != "-" else _concrete_array_path(path, index)
            if token == "-":
                before_record = _tracked_value(concrete_path, False)
            parent.insert(index, deepcopy(operation["value"]))
            inverse = {"op": "remove", "path": concrete_path}
            after_exists, after_value = _value_at_path(new_document, concrete_path)
            return new_document, inverse, before_record, _tracked_value(concrete_path, after_exists, after_value)
        after_exists, after_value = _value_at_path(new_document, path)
        return new_document, inverse, before_record, _tracked_value(path, after_exists, after_value)

    raise PatchApplyError("Cannot apply patch to scalar parent value.")


def apply_patch(document: Any, patch: list[dict[str, Any]]) -> PatchResult:
    if not isinstance(patch, list):
        raise PatchApplyError("Patch must be a list of operations.")
    if not patch:
        raise PatchApplyError("Patch must contain at least one operation.")

    working = deepcopy(document)
    inverse_operations: list[dict[str, Any]] = []
    changed_paths: list[str] = []
    before_values: list[dict[str, Any]] = []
    after_values: list[dict[str, Any]] = []

    for operation in patch:
        if not isinstance(operation, dict):
            raise PatchApplyError("Patch operation must be an object.")
        try:
            working, inverse, before_record, after_record = _apply_single(working, operation)
        except UnsupportedPatchOperationError:
            raise
        except JsonPointerError as exc:
            raise PatchApplyError(str(exc)) from exc
        inverse_operations.insert(0, inverse)
        changed_paths.append(after_record["path"])
        before_values.append(before_record)
        after_values.append(after_record)

    return PatchResult(
        document=working,
        inverse_patch=inverse_operations,
        changed_paths=changed_paths,
        before_values=before_values,
        after_values=after_values,
    )

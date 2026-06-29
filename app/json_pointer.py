from __future__ import annotations

from copy import deepcopy
from typing import Any


MISSING = object()


class JsonPointerError(ValueError):
    pass


def escape_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _unescape_segment(segment: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char != "~":
            chars.append(char)
            index += 1
            continue
        if index + 1 >= len(segment):
            raise JsonPointerError("JSON Pointer escape sequence '~' must be followed by '0' or '1'.")
        escape_code = segment[index + 1]
        if escape_code == "0":
            chars.append("~")
        elif escape_code == "1":
            chars.append("/")
        else:
            raise JsonPointerError(f"Invalid JSON Pointer escape sequence: ~{escape_code}")
        index += 2
    return "".join(chars)


def parse_pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not isinstance(path, str) or not path.startswith("/"):
        raise JsonPointerError("JSON Pointer path must be empty or start with '/'.")
    return [_unescape_segment(part) for part in path[1:].split("/")]


def join_pointer(parent: str, segment: str) -> str:
    escaped = escape_segment(segment)
    if parent == "":
        return f"/{escaped}"
    return f"{parent}/{escaped}"


def _array_index(token: str, length: int, allow_end: bool = False) -> int:
    if token == "-" and allow_end:
        return length
    if token == "":
        raise JsonPointerError("Array index cannot be empty.")
    try:
        index = int(token)
    except ValueError as exc:
        raise JsonPointerError(f"Invalid array index: {token}") from exc
    upper_bound = length if allow_end else length - 1
    if index < 0 or index > upper_bound:
        raise JsonPointerError(f"Array index out of range: {token}")
    return index


def get_value(document: Any, path: str) -> Any:
    current = document
    for token in parse_pointer(path):
        if isinstance(current, dict):
            if token not in current:
                raise JsonPointerError(f"Object key not found: {token}")
            current = current[token]
            continue
        if isinstance(current, list):
            current = current[_array_index(token, len(current))]
            continue
        raise JsonPointerError("Cannot traverse into scalar JSON value.")
    return deepcopy(current)


def value_exists(document: Any, path: str) -> bool:
    try:
        get_value(document, path)
    except JsonPointerError:
        return False
    return True

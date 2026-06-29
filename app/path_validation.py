from __future__ import annotations

from typing import Any

from app.errors import AppError


def ensure_relative_document_path(
    full_path: Any,
    *,
    error_code: str,
    subject: str = "Document full_path",
) -> str:
    if not isinstance(full_path, str) or not full_path.strip():
        raise AppError(
            error_code,
            f"{subject} is required.",
            {"full_path": full_path},
        )
    if full_path != full_path.strip():
        raise AppError(
            error_code,
            f"{subject} must not contain leading or trailing whitespace.",
            {"full_path": full_path},
        )
    if "\\" in full_path:
        raise AppError(
            error_code,
            f"{subject} must use POSIX-style '/' separators.",
            {"full_path": full_path},
        )
    if full_path.startswith("/"):
        raise AppError(
            error_code,
            f"{subject} must be relative.",
            {"full_path": full_path},
        )
    if full_path.endswith("/"):
        raise AppError(
            error_code,
            f"{subject} must not end with '/'.",
            {"full_path": full_path},
        )
    segments = full_path.split("/")
    if any(segment == "" for segment in segments):
        raise AppError(
            error_code,
            f"{subject} must not contain empty path segments.",
            {"full_path": full_path},
        )
    if any(segment in {".", ".."} for segment in segments):
        raise AppError(
            error_code,
            f"{subject} must not contain '.' or '..' path segments.",
            {"full_path": full_path},
        )
    return full_path


def ensure_relative_path_prefix(
    path_prefix: Any,
    *,
    error_code: str,
    subject: str = "path_prefix",
) -> str | None:
    if path_prefix is None:
        return None
    if not isinstance(path_prefix, str):
        raise AppError(
            error_code,
            f"{subject} must be a string.",
            {subject: path_prefix},
        )
    if not path_prefix.strip():
        return None
    if path_prefix != path_prefix.strip():
        raise AppError(
            error_code,
            f"{subject} must not contain leading or trailing whitespace.",
            {subject: path_prefix},
        )
    if path_prefix.endswith("//"):
        raise AppError(
            error_code,
            f"{subject} must not contain empty path segments.",
            {subject: path_prefix},
        )
    normalized = path_prefix[:-1] if path_prefix.endswith("/") else path_prefix
    ensure_relative_document_path(
        normalized,
        error_code=error_code,
        subject=subject,
    )
    return normalized


def ensure_relative_glob_pattern(
    file_pattern: Any,
    *,
    error_code: str,
    subject: str = "Schema file_pattern",
) -> str | None:
    if file_pattern is None:
        return None
    if not isinstance(file_pattern, str) or not file_pattern.strip():
        raise AppError(
            error_code,
            f"{subject} is required when provided.",
            {"file_pattern": file_pattern},
        )
    if file_pattern != file_pattern.strip():
        raise AppError(
            error_code,
            f"{subject} must not contain leading or trailing whitespace.",
            {"file_pattern": file_pattern},
        )
    if "\\" in file_pattern:
        raise AppError(
            error_code,
            f"{subject} must use POSIX-style '/' separators.",
            {"file_pattern": file_pattern},
        )
    if file_pattern.startswith("/"):
        raise AppError(
            error_code,
            f"{subject} must be relative.",
            {"file_pattern": file_pattern},
        )
    if file_pattern.endswith("/"):
        raise AppError(
            error_code,
            f"{subject} must not end with '/'.",
            {"file_pattern": file_pattern},
        )
    segments = file_pattern.split("/")
    if any(segment == "" for segment in segments):
        raise AppError(
            error_code,
            f"{subject} must not contain empty path segments.",
            {"file_pattern": file_pattern},
        )
    if any(segment in {".", ".."} for segment in segments):
        raise AppError(
            error_code,
            f"{subject} must not contain '.' or '..' path segments.",
            {"file_pattern": file_pattern},
        )
    return file_pattern

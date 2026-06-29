from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from app.errors import AppError, ErrorCode
from app.json_pointer import escape_segment


def json_pointer_from_path(path: object) -> str:
    parts = [escape_segment(str(part)) for part in path]
    if not parts:
        return ""
    return "/" + "/".join(parts)


def check_json_schema(schema_json: Any) -> None:
    try:
        Draft202012Validator.check_schema(schema_json)
    except SchemaError as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SCHEMA,
            "Schema document is not a valid JSON Schema.",
            {"message": exc.message},
        ) from exc


def _validation_error_to_dict(error: ValidationError) -> dict[str, Any]:
    return {
        "path": json_pointer_from_path(error.absolute_path),
        "message": error.message,
        "validator": error.validator,
        "expected": error.validator_value,
        "actual": error.instance,
    }


def validate_instance(schema_json: Any, instance: Any) -> dict[str, Any]:
    check_json_schema(schema_json)
    validator = Draft202012Validator(schema_json)
    errors = sorted(
        (_validation_error_to_dict(error) for error in validator.iter_errors(instance)),
        key=lambda item: (item["path"], item["validator"], item["message"]),
    )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": [],
    }


def ensure_schema_validates(schema_json: Any, instance: Any) -> dict[str, Any]:
    result = validate_instance(schema_json, instance)
    if not result["valid"]:
        raise AppError(
            ErrorCode.SCHEMA_VALIDATION_FAILED,
            "Document failed schema validation.",
            {"errors": result["errors"]},
        )
    return result

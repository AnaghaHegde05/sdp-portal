"""Server-side validation of a request's details and document slots against app/core/request_types.py.

Authoritative: the frontend validates the same rules for fast feedback, but nothing is trusted from it.
"""
import json
import re

from fastapi import HTTPException

from app.core.config import settings
from app.core.request_types import REQUEST_TYPES, TEXT_MAX_DEFAULT, get_request_type

_PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{6,18}[0-9]$")


def _bad(errors: list[str]) -> HTTPException:
    return HTTPException(400, " ".join(errors))


def parse_form_data(raw: str | None) -> dict:
    if raw is None or not raw.strip():
        raise HTTPException(400, "The request details are missing.")
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "The request details are not valid.")
    if not isinstance(data, dict):
        raise HTTPException(400, "The request details are not valid.")
    return data


def validate_form_data(code: str, data: dict) -> dict:
    """Return the cleaned details (only known fields, trimmed) or raise 400 listing every problem."""
    spec = get_request_type(code)
    if spec is None:
        raise HTTPException(400, "This document type is not available for online requests.")
    errors: list[str] = []
    cleaned: dict = {}
    known = {f["name"] for f in spec["fields"]}
    for name in data:
        if name not in known:
            errors.append(f"Unexpected field '{name}'.")

    def value_of(name):
        v = data.get(name)
        return v.strip() if isinstance(v, str) else v

    for f in spec["fields"]:
        name, label = f["name"], f["label"]
        v = value_of(name)
        required = f.get("required", False)
        cond = f.get("required_if")
        if cond and value_of(cond["field"]) == cond["equals"]:
            required = True
        empty = v is None or v == ""
        if empty:
            if required:
                errors.append(f"{label} is required.")
            continue

        kind = f["type"]
        if kind in ("text", "textarea", "tel"):
            if not isinstance(v, str):
                errors.append(f"{label} must be text.")
                continue
            if len(v) > f.get("max_length", TEXT_MAX_DEFAULT):
                errors.append(f"{label} is too long.")
                continue
            if kind == "tel" and not _PHONE_RE.match(v):
                errors.append(f"{label} is not a valid phone number.")
                continue
        elif kind == "number":
            try:
                if isinstance(v, bool) or (isinstance(v, float) and v != int(v)):
                    raise ValueError
                v = int(v)
            except (TypeError, ValueError):
                errors.append(f"{label} must be a whole number.")
                continue
            if not (f["min"] <= v <= f["max"]):
                errors.append(f"{label} must be between {f['min']} and {f['max']}.")
                continue
        elif kind == "select":
            if v not in f["options"]:
                errors.append(f"{label}: choose one of the listed options.")
                continue
        cleaned[name] = v
    if errors:
        raise _bad(errors)
    return cleaned


def validate_document_slots(code: str, categories: list[str], file_count: int) -> list[str]:
    """Check the parallel `file_categories` list: one known slot per file, no repeats, all required slots filled."""
    spec = get_request_type(code)
    if spec is None:
        raise HTTPException(400, "This document type is not available for online requests.")
    if len(categories) != file_count:
        raise HTTPException(400, "Each uploaded file must be assigned to one of the listed document slots.")
    by_code = {d["code"]: d for d in spec["documents"]}
    errors: list[str] = []
    seen: set[str] = set()
    for c in categories:
        if c not in by_code:
            errors.append(f"'{c}' is not a document slot for this request.")
        elif c in seen:
            errors.append(f"'{by_code[c]['label']}' was attached more than once.")
        seen.add(c)
    for d in spec["documents"]:
        if d["required"] and d["code"] not in seen:
            errors.append(f"Required document missing: {d['label']}.")
    if errors:
        raise _bad(errors)
    return categories


def assert_config_consistent() -> None:
    """Every request type's document slots must fit within the configured file limit (checked by a test)."""
    for code, spec in REQUEST_TYPES.items():
        if len(spec["documents"]) > settings.max_files_per_application:
            raise RuntimeError(f"{code}: more document slots than MAX_FILES_PER_APPLICATION")

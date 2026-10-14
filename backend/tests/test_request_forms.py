"""Request-specific details, required-document slots and the public request-types description."""
import json

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.request_types import REQUEST_TYPES
from app.models import Application
from tests.conftest import PDF_BYTES, PNG_BYTES, valid_details
from tests.test_eligibility import doc_type_id

CODES = list(REQUEST_TYPES)


def post(api, headers, db_session, code, *, details=None, categories=None, files=None, raw_form=None):
    """POST a submission built by hand (so tests control every part)."""
    spec = REQUEST_TYPES[code]
    categories = categories if categories is not None else [d["code"] for d in spec["documents"] if d["required"]]
    files = files if files is not None else [(f"{c}.png", PNG_BYTES, "image/png") for c in categories]
    data = {
        "document_type_id": str(doc_type_id(db_session, code)),
        "form_data": raw_form if raw_form is not None else json.dumps(valid_details(code) if details is None else details),
        "file_categories": categories,
    }
    return api.post("/api/applications", headers=headers, data=data, files=[("files", f) for f in files] or None)


def app_count(db_session, student):
    return db_session.scalar(select(func.count()).select_from(Application).where(Application.student_id == student.id))


# ---------------------------------------------------------------- GET /api/request-types

def test_request_types_is_public_and_describes_all_four(api):
    r = api.get("/api/request-types")
    assert r.status_code == 200
    body = r.json()
    assert [t["code"] for t in body["request_types"]] == CODES
    for t in body["request_types"]:
        assert t["fields"] and t["documents"]
        assert any(d["required"] for d in t["documents"])
        assert t["requirements_verified"] is False  # honest: no official KLE Tech list was found


def test_upload_limits_come_from_the_single_setting(api, monkeypatch):
    lim = api.get("/api/request-types").json()["upload_limits"]
    assert lim == {
        "max_files": settings.max_files_per_application,
        "max_file_mb": settings.max_upload_mb,
        "allowed_extensions": ["jpeg", "jpg", "pdf", "png"],
        "allowed_description": "PDF, JPG or PNG",
    }
    assert lim["max_files"] == 5 and lim["max_file_mb"] == 5
    monkeypatch.setattr(settings, "max_files_per_application", 3)
    assert api.get("/api/request-types").json()["upload_limits"]["max_files"] == 3


def test_each_request_type_asks_for_its_own_details_and_documents():
    names = {c: {f["name"] for f in REQUEST_TYPES[c]["fields"]} for c in CODES}
    assert "purpose" in names["TRANSCRIPT"] and "number_of_copies" in names["TRANSCRIPT"]
    assert "destination_institution" in names["MIGRATION_CERTIFICATE"]
    assert {"semesters", "exam_session"} <= names["DUPLICATE_GRADE_CARD"]
    assert {"final_result_declared", "all_requirements_completed"} <= names["PROVISIONAL_DEGREE_CERTIFICATE"]
    # request-specific fields are not shared with the other types
    assert "semesters" not in names["TRANSCRIPT"] and "number_of_copies" not in names["MIGRATION_CERTIFICATE"]
    docs = {c: {d["code"] for d in REQUEST_TYPES[c]["documents"]} for c in CODES}
    assert "loss_declaration" in docs["DUPLICATE_GRADE_CARD"] and "loss_declaration" not in docs["TRANSCRIPT"]
    assert len({frozenset(v) for v in docs.values()}) == 4  # four different document lists


# ---------------------------------------------------------------- valid submissions

@pytest.mark.parametrize("code", CODES)
def test_valid_submission_stores_details_and_slots(api, db_session, student_auth, code):
    _, headers = student_auth
    r = post(api, headers, db_session, code)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["form_data"] == valid_details(code)
    required = [d["code"] for d in REQUEST_TYPES[code]["documents"] if d["required"]]
    assert [d["document_category"] for d in body["documents"]] == required


def test_optional_document_is_accepted(api, db_session, student_auth):
    _, headers = student_auth
    cats = [d["code"] for d in REQUEST_TYPES["TRANSCRIPT"]["documents"]]  # all three, incl. optional
    r = post(api, headers, db_session, "TRANSCRIPT", categories=cats)
    assert r.status_code == 201 and len(r.json()["documents"]) == 3


def test_details_are_trimmed_and_unrelated_values_are_not_stored(api, db_session, student_auth):
    _, headers = student_auth
    details = {**valid_details("TRANSCRIPT"), "recipient": "  Some University  "}
    r = post(api, headers, db_session, "TRANSCRIPT", details=details)
    assert r.status_code == 201 and r.json()["form_data"]["recipient"] == "Some University"


# ---------------------------------------------------------------- invalid details

@pytest.mark.parametrize("code", CODES)
def test_each_required_field_is_enforced(api, db_session, student_auth, code):
    student, headers = student_auth
    for f in REQUEST_TYPES[code]["fields"]:
        if not f.get("required"):
            continue
        details = {k: v for k, v in valid_details(code).items() if k != f["name"]}
        r = post(api, headers, db_session, code, details=details)
        assert r.status_code == 400, f["name"]
        assert f["label"] in r.json()["detail"]
    assert app_count(db_session, student) == 0


@pytest.mark.parametrize(
    "patch,fragment",
    [
        ({"contact_phone": "abc"}, "not a valid phone number"),
        ({"contact_phone": "12"}, "not a valid phone number"),
        ({"year_of_passing": 1800}, "between"),
        ({"year_of_passing": "twenty"}, "whole number"),
        ({"number_of_copies": 0}, "between 1 and 10"),
        ({"number_of_copies": 11}, "between 1 and 10"),
        ({"purpose": "Whatever"}, "choose one of the listed options"),
        ({"recipient": "x" * 201}, "too long"),
        ({"sneaky_field": "x"}, "Unexpected field"),
    ],
)
def test_invalid_details_are_rejected(api, db_session, student_auth, patch, fragment):
    student, headers = student_auth
    r = post(api, headers, db_session, "TRANSCRIPT", details={**valid_details("TRANSCRIPT"), **patch})
    assert r.status_code == 400 and fragment in r.json()["detail"]
    assert app_count(db_session, student) == 0


def test_missing_or_malformed_details_are_rejected(api, db_session, student_auth):
    _, headers = student_auth
    assert post(api, headers, db_session, "TRANSCRIPT", raw_form="not json").status_code == 400
    assert post(api, headers, db_session, "TRANSCRIPT", raw_form="[1, 2]").status_code == 400
    assert post(api, headers, db_session, "TRANSCRIPT", raw_form="").status_code == 400


def test_conditional_required_fields(api, db_session, student_auth):
    _, headers = student_auth
    base = valid_details("MIGRATION_CERTIFICATE")
    no_dest = {k: v for k, v in base.items() if k != "destination_institution"}
    r = post(api, headers, db_session, "MIGRATION_CERTIFICATE", details={**no_dest, "reason": "Admission to another university"})
    assert r.status_code == 400 and "Institution / university you are moving to is required" in r.json()["detail"]
    assert post(api, headers, db_session, "MIGRATION_CERTIFICATE", details={**no_dest, "reason": "Employment"}).status_code == 201

    dup = {k: v for k, v in valid_details("DUPLICATE_GRADE_CARD").items() if k != "reason_details"}
    assert post(api, headers, db_session, "DUPLICATE_GRADE_CARD", details={**dup, "reason": "Other"}).status_code == 400
    assert post(api, headers, db_session, "DUPLICATE_GRADE_CARD", details={**dup, "reason": "Lost"}).status_code == 201


# ---------------------------------------------------------------- document slots

def test_missing_required_document_is_rejected_and_nothing_saved(api, db_session, student_auth, upload_dir):
    student, headers = student_auth
    r = post(api, headers, db_session, "TRANSCRIPT", categories=["marks_cards"],
             files=[("m.png", PNG_BYTES, "image/png")])
    assert r.status_code == 400 and "Required document missing: Photo ID proof" in r.json()["detail"]
    assert app_count(db_session, student) == 0
    assert [p for p in upload_dir.rglob("*") if p.is_file()] == []


def test_no_documents_at_all_is_rejected(api, db_session, student_auth):
    _, headers = student_auth
    assert post(api, headers, db_session, "TRANSCRIPT", categories=[], files=[]).status_code == 400


@pytest.mark.parametrize(
    "categories,fragment",
    [
        (["marks_cards", "marks_cards", "id_proof"], "more than once"),
        (["marks_cards", "bogus"], "not a document slot"),
        (["marks_cards"], "assigned to one of the listed document slots"),  # count mismatch with 2 files
    ],
)
def test_bad_slot_assignments_are_rejected(api, db_session, student_auth, categories, fragment):
    _, headers = student_auth
    files = [(f"f{i}.png", PNG_BYTES, "image/png") for i in range(3 if len(categories) == 3 else 2)]
    r = post(api, headers, db_session, "TRANSCRIPT", categories=categories, files=files)
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_a_slot_from_another_request_type_is_rejected(api, db_session, student_auth):
    _, headers = student_auth
    r = post(api, headers, db_session, "TRANSCRIPT", categories=["marks_cards", "id_proof", "loss_declaration"],
             files=[(f"f{i}.png", PNG_BYTES, "image/png") for i in range(3)])
    assert r.status_code == 400 and "loss_declaration" in r.json()["detail"]


# ---------------------------------------------------------------- upload validation still applies per slot

@pytest.mark.parametrize(
    "name,data,ctype,status",
    [
        ("notes.txt", b"hello", "text/plain", 400),            # type
        ("fake.png", b"this is not a png", "image/png", 400),   # actual content
        ("empty.pdf", b"", "application/pdf", 400),
    ],
)
def test_file_type_and_content_validated_for_slot_uploads(api, db_session, student_auth, upload_dir, name, data, ctype, status):
    student, headers = student_auth
    r = post(api, headers, db_session, "TRANSCRIPT",
             files=[(name, data, ctype), ("id.png", PNG_BYTES, "image/png")])
    assert r.status_code == status
    assert app_count(db_session, student) == 0
    assert [p for p in upload_dir.rglob("*") if p.is_file()] == []


def test_file_size_limit_for_slot_uploads(api, db_session, student_auth, monkeypatch):
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"%PDF-" + b"a" * (1024 * 1024)
    r = post(api, headers, db_session, "TRANSCRIPT", files=[("big.pdf", big, "application/pdf"), ("id.png", PNG_BYTES, "image/png")])
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert app_count(db_session, student) == 0


def test_all_four_allowed_extensions_work(api, db_session, student_auth):
    _, headers = student_auth
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 20
    r = post(api, headers, db_session, "TRANSCRIPT", categories=["marks_cards", "degree_certificate", "id_proof"],
             files=[("a.pdf", PDF_BYTES, "application/pdf"), ("b.jpg", jpeg, "image/jpeg"), ("c.PNG", PNG_BYTES, "image/png")])
    assert r.status_code == 201
    r = post(api, headers, db_session, "TRANSCRIPT",
             files=[("a.jpeg", jpeg, "image/jpeg"), ("b.png", PNG_BYTES, "image/png")])
    assert r.status_code == 201


def test_submission_requires_login(api):
    assert api.post("/api/applications", data={"document_type_id": "1"}).status_code == 401

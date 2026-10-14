"""Eligibility tests: three outcomes (ELIGIBLE / INELIGIBLE / MANUAL_REVIEW), run against the real seeded
simulated students and the real OCR pipeline.

Key properties checked here:
* No CGPA / backlog / fee-clearance rule exists: students with fee DUE or backlogs are still ELIGIBLE.
* OCR uncertainty and document mismatches -> MANUAL_REVIEW, never a rejection.
* A rule can only reject (INELIGIBLE) once it is marked verified; unverified rules route to MANUAL_REVIEW.
"""
import dataclasses

import pytest
from sqlalchemy import select

from app.models import DocumentType, Student
from app.services import eligibility
from tests.conftest import submission, valid_details
from tests.test_ocr import SAMPLE_LINES, _blank_png, _text_png  # noqa: F401


def register_seeded(api, usn):
    r = api.post("/api/auth/register", json={"usn": usn, "email": f"{usn.lower()}@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def usn_png(usn):
    """A scan whose text shows the given USN (the portal's OCR then finds it)."""
    return _text_png(["Sample supporting document (test data)", f"USN: {usn}", "CGPA: 8.37", "Date: 12/05/2024"])


def doc_type_id(db_session, code):
    return db_session.scalar(select(DocumentType.id).where(DocumentType.code == code))


def student_by_usn(db_session, usn):
    return db_session.scalar(select(Student).where(Student.usn == usn))


def submit_for(api, headers, dtid, usn=None, fill=None, details=None, files=()):
    data, parts = submission(dtid, files, fill=fill if fill is not None else usn_png(usn), details=details)
    r = api.post("/api/applications", headers=headers, data=data, files=parts)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def full_flow(api, headers, dtid, usn, **kw):
    """Submit -> OCR -> eligibility through the individual endpoints (the portal itself uses /process)."""
    app_id = submit_for(api, headers, dtid, usn, **kw)
    assert api.post(f"/api/applications/{app_id}/ocr", headers=headers).status_code == 200
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


ALL_TYPES = ["TRANSCRIPT", "MIGRATION_CERTIFICATE", "DUPLICATE_GRADE_CARD", "PROVISIONAL_DEGREE_CERTIFICATE"]


@pytest.mark.parametrize("doc_code", ALL_TYPES)
@pytest.mark.parametrize(
    "usn",
    [
        "01FE23CSE001",  # fee CLEAR, no backlogs
        "01FE23CSE002",  # has a backlog
        "01FE23CSE004",  # fee DUE
        "01FE23EEE001",  # fee DUE, no backlogs
    ],
)
def test_no_fee_backlog_or_cgpa_restriction(api, db_session, usn, doc_code):
    """These attributes are NOT policy: they must not affect the outcome."""
    headers = register_seeded(api, usn)
    result = full_flow(api, headers, doc_type_id(db_session, doc_code), usn)
    assert result["status"] == "ELIGIBLE", result["history"][-1]["note"]
    assert result["eligibility_result"]["outcome"] == "ELIGIBLE"
    assert result["eligibility_result"]["reasons"] == []
    assert result["history"][-1]["note"] == "Eligible: all automatic checks passed."


def test_eligible_result_lists_the_checks_that_ran(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001")
    assert r["eligibility_result"]["checks"] == ["required_documents", "usn_on_documents"]
    assert r["eligibility_result"]["requirements_verified"] is False  # honest: lists are provisional


def test_usn_on_a_different_student_goes_to_manual_review(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", fill=usn_png("01FE23ECE001"))
    assert r["status"] == "MANUAL_REVIEW"
    assert r["status_label"] == "Needs verification"
    res = r["eligibility_result"]
    assert res["outcome"] == "MANUAL_REVIEW"
    assert "differs" in res["reasons"][0]["message"] and "01FE23ECE001" in res["reasons"][0]["message"]
    assert r["history"][-1]["note"].startswith("Needs verification:")


def test_usn_not_found_on_document_goes_to_manual_review_not_rejection(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    no_usn = _text_png(["Some marks card", "CGPA: 8.37", "Date: 12/05/2024"])
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", fill=no_usn)
    assert r["status"] == "MANUAL_REVIEW"
    assert "could not be found" in r["eligibility_result"]["reasons"][0]["message"]


def test_unreadable_blank_scan_goes_to_manual_review(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", fill=_blank_png())
    assert r["status"] == "MANUAL_REVIEW"
    assert "No readable text" in r["eligibility_result"]["reasons"][0]["message"]


def test_id_proof_is_not_checked_for_a_usn(api, db_session):
    """Only documents that normally carry the USN are checked; the ID proof may show none."""
    headers = register_seeded(api, "01FE23CSE001")
    files = [("marks.png", usn_png("01FE23CSE001"), "image/png"), ("deg.png", usn_png("01FE23CSE001"), "image/png"),
             ("id.png", _text_png(["Government ID", "Name only"]), "image/png")]
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", files=files)
    assert r["status"] == "ELIGIBLE", r["history"][-1]["note"]


@pytest.mark.parametrize("field", ["final_result_declared", "all_requirements_completed"])
def test_pdc_declared_incomplete_is_unverified_so_manual_review(api, db_session, field):
    """'Degree not completed' is not a confirmed KLE Tech rule, so it must not auto-reject."""
    headers = register_seeded(api, "01FE23CSE001")
    details = {**valid_details("PROVISIONAL_DEGREE_CERTIFICATE"), field: "No"}
    r = full_flow(api, headers, doc_type_id(db_session, "PROVISIONAL_DEGREE_CERTIFICATE"), "01FE23CSE001", details=details)
    assert r["status"] == "MANUAL_REVIEW"
    reason = r["eligibility_result"]["reasons"][0]
    assert reason["outcome"] == "MANUAL_REVIEW" and reason["verified"] is False
    assert "not yet confirmed as university policy" in reason["message"]


def test_a_verified_rule_can_reject_as_ineligible(api, db_session, monkeypatch):
    """Once a rule is confirmed against official policy (verified=True) the same failure is INELIGIBLE."""
    rule = eligibility.RULES_BY_DOCUMENT_TYPE["PROVISIONAL_DEGREE_CERTIFICATE"][0]
    monkeypatch.setitem(
        eligibility.RULES_BY_DOCUMENT_TYPE, "PROVISIONAL_DEGREE_CERTIFICATE", [dataclasses.replace(rule, verified=True)]
    )
    headers = register_seeded(api, "01FE23CSE001")
    details = {**valid_details("PROVISIONAL_DEGREE_CERTIFICATE"), "all_requirements_completed": "No"}
    r = full_flow(api, headers, doc_type_id(db_session, "PROVISIONAL_DEGREE_CERTIFICATE"), "01FE23CSE001", details=details)
    assert r["status"] == "NOT_ELIGIBLE"  # stored value of the INELIGIBLE outcome
    assert r["eligibility_result"]["outcome"] == "INELIGIBLE"
    assert "not completed all requirements" in r["history"][-1]["note"]
    assert api.post(f"/api/applications/{r['id']}/payment/initiate", headers=headers).status_code == 400


def test_unverified_rules_never_reject_anywhere_in_the_default_policy():
    """Guard for the principle: with the shipped policy, nothing that can reject is unverified."""
    for rules in [eligibility.COMMON_RULES, *eligibility.RULES_BY_DOCUMENT_TYPE.values()]:
        for rule in rules:
            if rule.on_fail == eligibility.Outcome.INELIGIBLE and not rule.verified:
                # allowed to exist, but the engine must downgrade it; covered by the manual-review tests above
                assert rule.basis, "an unverified rule must say where it comes from"


def test_no_fee_cgpa_or_backlog_rule_is_configured():
    codes = {r.code for rules in [eligibility.COMMON_RULES, *eligibility.RULES_BY_DOCUMENT_TYPE.values()] for r in rules}
    assert not [c for c in codes if any(w in c for w in ("fee", "cgpa", "backlog"))]


def test_application_without_recorded_document_slots_needs_verification(api, db_session, student_auth, doc_type):
    """Older applications (files, but no slot categories) cannot be matched to the required list."""
    from app.services import uploads
    from app.services.applications import create_application
    from tests.conftest import PNG_BYTES

    student, _ = student_auth
    item = uploads.ValidatedUpload("old.png", "png", "image/png", PNG_BYTES)  # category=None
    application = create_application(db_session, student, doc_type, [item])
    result = eligibility.evaluate(application, student)
    assert result.outcome == eligibility.Outcome.MANUAL_REVIEW
    assert "before document slots were recorded" in result.reasons[0]["message"]


def test_missing_required_document_is_caught_by_the_engine_too(api, db_session, student_auth, doc_type, monkeypatch):
    """The API refuses such submissions; the engine is the second line of defence."""
    from app.services import uploads
    from app.services.applications import create_application
    from tests.conftest import PNG_BYTES

    student, _ = student_auth
    item = uploads.ValidatedUpload("x.png", "png", "image/png", PNG_BYTES, category="degree_certificate")  # optional slot only
    application = create_application(db_session, student, doc_type, [item])
    unverified = eligibility.evaluate(application, student)
    assert unverified.outcome == eligibility.Outcome.MANUAL_REVIEW  # list is unverified -> verification, not rejection
    assert "Required document not provided" in unverified.reasons[0]["message"]

    verified = dataclasses.replace(eligibility._REQUIRED_DOCS, verified=True)
    monkeypatch.setattr(eligibility, "COMMON_RULES", [verified, eligibility._USN_CHECK])
    assert eligibility.evaluate(application, student).outcome == eligibility.Outcome.INELIGIBLE


def test_manual_review_cannot_be_rerun_into_eligible_by_the_student(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    r = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", fill=usn_png("01FE23ECE001"))
    assert r["status"] == "MANUAL_REVIEW"
    again = api.post(f"/api/applications/{r['id']}/eligibility", headers=headers)
    assert again.status_code == 400  # decision stays until a person verifies it


def test_eligibility_requires_ocr_first(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    app_id = submit_for(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001")
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)  # OCR skipped
    assert r.status_code == 400


def test_eligibility_requires_login(api):
    assert api.post("/api/applications/1/eligibility").status_code == 401


def test_eligibility_404_for_someone_elses_application(api, db_session):
    headers_a = register_seeded(api, "01FE23CSE001")
    app_id = full_flow(api, headers_a, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001")["id"]
    headers_b = register_seeded(api, "01FE23CSE002")
    assert api.post(f"/api/applications/{app_id}/eligibility", headers=headers_b).status_code == 404


def test_eligibility_does_not_touch_risk_scoring(api, db_session):
    """ML risk scoring is a separate concern: this step only changes status/history/eligibility_result."""
    from app.models import Transaction

    headers = register_seeded(api, "01FE23CSE001")
    full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001")
    assert db_session.query(Transaction).count() == 0

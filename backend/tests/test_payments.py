"""Mock/sandbox payment tests - full real HTTP flow through OCR -> eligibility -> payment."""
import dataclasses

from tests.conftest import valid_details
from tests.test_eligibility import doc_type_id, register_seeded, submit_for, usn_png


def to_eligible(api, usn, doc_code, db_session):
    headers = register_seeded(api, usn)
    app_id = submit_for(api, headers, doc_type_id(db_session, doc_code), usn)
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "ELIGIBLE", r.json()
    return app_id, headers


def test_full_payment_success_flow(api, db_session):
    app_id, headers = to_eligible(api, "01FE23CSE001", "TRANSCRIPT", db_session)

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_PENDING"
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["payment_status"] == "PENDING"
    assert body["transactions"][0]["amount"] == "200.00"  # TRANSCRIPT placeholder fee

    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_COMPLETED"
    assert body["transactions"][0]["payment_status"] == "SUCCESS"
    assert body["history"][-1]["status"] == "PAYMENT_COMPLETED"


def test_failed_payment_does_not_complete_application(api, db_session):
    app_id, headers = to_eligible(api, "01FE23CSE001", "MIGRATION_CERTIFICATE", db_session)

    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "failure"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_PENDING"  # NOT silently completed
    assert body["transactions"][0]["payment_status"] == "FAILED"
    assert "PAYMENT_COMPLETED" not in [h["status"] for h in body["history"]]


def test_initiate_response_includes_the_new_pending_transaction(api, db_session):
    """The frontend picks 'Simulate payment' vs 'Start/Retry payment' from this very response, so
    it must already contain the PENDING row that was just created (regression: it used to come
    back with an empty list because the reload returned the session's stale collection)."""
    app_id, headers = to_eligible(api, "01FE23CSE001", "DUPLICATE_GRADE_CARD", db_session)
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    assert [t["payment_status"] for t in r.json()["transactions"]] == ["PENDING"]


def test_retry_after_failed_payment_creates_new_transaction(api, db_session):
    app_id, headers = to_eligible(api, "01FE23CSE001", "DUPLICATE_GRADE_CARD", db_session)

    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "failure"})
    # Retry: initiate again (allowed while PAYMENT_PENDING), then succeed.
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["transactions"]) == 2
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.json()["status"] == "PAYMENT_COMPLETED"
    statuses = [t["payment_status"] for t in r.json()["transactions"]]
    assert statuses == ["FAILED", "SUCCESS"]  # first attempt kept for the audit trail


def test_manual_review_application_cannot_pay(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    app_id = submit_for(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001", fill=usn_png("01FE23ECE001"))
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "MANUAL_REVIEW"

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400 and "needs verification" in r.json()["detail"]
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.status_code == 400  # nothing pending; cannot be forced through
    assert api.get(f"/api/applications/{app_id}", headers=headers).json()["transactions"] == []


def test_ineligible_application_cannot_pay(api, db_session, monkeypatch):
    from app.services import eligibility

    rule = eligibility.RULES_BY_DOCUMENT_TYPE["PROVISIONAL_DEGREE_CERTIFICATE"][0]
    monkeypatch.setitem(eligibility.RULES_BY_DOCUMENT_TYPE, "PROVISIONAL_DEGREE_CERTIFICATE", [dataclasses.replace(rule, verified=True)])
    headers = register_seeded(api, "01FE23CSE001")
    details = {**valid_details("PROVISIONAL_DEGREE_CERTIFICATE"), "all_requirements_completed": "No"}
    app_id = submit_for(api, headers, doc_type_id(db_session, "PROVISIONAL_DEGREE_CERTIFICATE"), "01FE23CSE001", details=details)
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    assert api.post(f"/api/applications/{app_id}/eligibility", headers=headers).json()["status"] == "NOT_ELIGIBLE"
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400 and "not eligible" in r.json()["detail"]


def test_undecided_application_cannot_pay(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    app_id = submit_for(api, headers, doc_type_id(db_session, "TRANSCRIPT"), "01FE23CSE001")
    assert api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers).status_code == 400  # SUBMITTED


def test_eligible_status_without_a_stored_decision_cannot_pay(api, db_session):
    """e.g. an older application decided under the former placeholder rules: it must be re-checked first."""
    from app.models import Application

    app_id, headers = to_eligible(api, "01FE23CSE001", "TRANSCRIPT", db_session)
    application = db_session.get(Application, app_id)
    application.eligibility_result = None  # as on a pre-update row
    db_session.flush()
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400 and "re-checked" in r.json()["detail"]
    # re-running the eligibility check (allowed from ELIGIBLE) stores a decision and unblocks payment
    assert api.post(f"/api/applications/{app_id}/eligibility", headers=headers).status_code == 200
    assert api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers).status_code == 200


def test_cannot_complete_payment_with_none_pending(api, db_session):
    app_id, headers = to_eligible(api, "01FE23CSE001", "TRANSCRIPT", db_session)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.status_code == 400  # never initiated


def test_invalid_outcome_rejected(api, db_session):
    app_id, headers = to_eligible(api, "01FE23CSE001", "TRANSCRIPT", db_session)
    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "maybe"})
    assert r.status_code == 400


def test_payment_requires_login(api):
    assert api.post("/api/applications/1/payment/initiate").status_code == 401
    assert api.post("/api/applications/1/payment/complete", json={"outcome": "success"}).status_code == 401


def test_payment_404_for_someone_elses_application(api, db_session):
    app_id, _ = to_eligible(api, "01FE23CSE001", "TRANSCRIPT", db_session)
    other_headers = register_seeded(api, "01FE23CSE002")
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=other_headers)
    assert r.status_code == 404

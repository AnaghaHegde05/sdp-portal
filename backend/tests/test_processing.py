"""Tests for POST /applications/{id}/process - the automatic OCR -> eligibility chain.

Runs the real Tesseract pipeline and the real eligibility rules; nothing is mocked.
"""
from tests.conftest import PNG_BYTES, valid_details
from tests.test_eligibility import doc_type_id, register_seeded, submit_for, usn_png
from tests.test_applications import submit


def _statuses(body):
    return [h["status"] for h in body["history"]]


def _start(api, db_session, usn="01FE23CSE001", code="TRANSCRIPT", **kw):
    headers = register_seeded(api, usn)
    return headers, submit_for(api, headers, doc_type_id(db_session, code), usn, **kw)


def test_process_runs_ocr_then_eligibility(api, db_session):
    headers, app_id = _start(api, db_session)
    r = api.post(f"/api/applications/{app_id}/process", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ELIGIBLE"
    assert _statuses(body) == ["SUBMITTED", "OCR_COMPLETED", "ELIGIBLE"]  # history preserved via set_status
    assert all(d["ocr_result"]["status"] == "SUCCESS" for d in body["documents"])
    assert body["eligibility_result"]["outcome"] == "ELIGIBLE"
    assert body["transactions"] == []  # processing never starts a payment
    assert body["fee_amount"] is not None


def test_process_is_idempotent(api, db_session):
    headers, app_id = _start(api, db_session)
    first = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    second = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert second["status"] == "ELIGIBLE"
    assert _statuses(second) == _statuses(first)  # no second OCR / eligibility run
    assert second["documents"][0]["ocr_result"]["processed_at"] == first["documents"][0]["ocr_result"]["processed_at"]


def test_process_unclear_document_stops_at_manual_review(api, db_session):
    headers, app_id = _start(api, db_session, fill=usn_png("01FE23ECE001"))  # someone else's USN on the scan
    body = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert body["status"] == "MANUAL_REVIEW"
    assert body["eligibility_result"]["outcome"] == "MANUAL_REVIEW"
    assert api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers).status_code == 400
    again = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert _statuses(again) == _statuses(body)  # a decided application is left alone


def test_process_failed_ocr_does_not_run_eligibility_and_can_retry(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    corrupt = b"%PDF-1.4\n" + (b"\x00\x01\x02garbage" * 30)
    r = submit(api, headers, doc_type_id(db_session, "TRANSCRIPT"), [("bad.pdf", corrupt, "application/pdf")],
               fill=usn_png("01FE23CSE001"))
    app_id = r.json()["id"]

    body = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert body["status"] == "OCR_COMPLETED"  # stopped: eligibility must not run on unreadable input
    assert body["documents"][0]["ocr_result"]["status"] == "FAILED"
    assert "could not be read" in body["history"][-1]["note"]
    assert body["eligibility_result"] is None

    again = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert _statuses(again) == ["SUBMITTED", "OCR_COMPLETED"]  # no automatic retry loop
    retried = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert _statuses(retried) == ["SUBMITTED", "OCR_COMPLETED", "OCR_COMPLETED"]
    assert len(retried["documents"]) == 2 and retried["documents"][0]["ocr_result"]["status"] == "FAILED"


def test_retry_ocr_is_a_noop_when_ocr_already_succeeded(api, db_session):
    headers, app_id = _start(api, db_session)
    first = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    again = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert _statuses(again) == _statuses(first)


def test_process_leaves_payment_states_alone(api, db_session):
    headers, app_id = _start(api, db_session)
    api.post(f"/api/applications/{app_id}/process", headers=headers)
    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    body = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert body["status"] == "PAYMENT_PENDING"
    assert len(body["transactions"]) == 1


def test_process_requires_login(api):
    assert api.post("/api/applications/1/process").status_code == 401


def test_process_404_for_someone_elses_application(api, db_session):
    headers, app_id = _start(api, db_session)
    other = register_seeded(api, "01FE23CSE002")
    assert api.post(f"/api/applications/{app_id}/process", headers=other).status_code == 404
    assert api.get(f"/api/applications/{app_id}", headers=headers).json()["status"] == "SUBMITTED"


def test_detail_exposes_fee_from_backend_schedule(api, db_session):
    headers = register_seeded(api, "01FE23CSE001")
    for code, fee in [("TRANSCRIPT", "200.00"), ("MIGRATION_CERTIFICATE", "500.00")]:
        app_id = submit_for(api, headers, doc_type_id(db_session, code), "01FE23CSE001")
        assert api.get(f"/api/applications/{app_id}", headers=headers).json()["fee_amount"] == fee

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Application
from app.services import uploads
from tests.conftest import PDF_BYTES, PNG_BYTES
from tests.test_applications import submit


def app_count(db_session, student):
    return db_session.scalar(select(func.count()).select_from(Application).where(Application.student_id == student.id))


def files_on_disk(upload_dir):
    return [p for p in upload_dir.rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    "name,data,ctype",
    [
        ("notes.txt", b"hello", "text/plain"),                       # extension not allowed
        ("script.exe", b"MZ\x90\x00", "application/octet-stream"),   # extension not allowed
        ("fake.pdf", b"this is not a pdf", "application/pdf"),       # right extension, wrong content
        ("really_png.pdf", PNG_BYTES, "application/pdf"),            # PNG bytes named .pdf
        ("really_pdf.png", PDF_BYTES, "image/png"),                  # PDF bytes named .png
        ("empty.pdf", b"", "application/pdf"),
    ],
)
def test_bad_files_rejected_and_nothing_saved(api, student_auth, doc_type, db_session, upload_dir, name, data, ctype):
    student, headers = student_auth
    r = submit(api, headers, doc_type.id, [(name, data, ctype)])
    assert r.status_code == 400
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_oversized_file_rejected(api, student_auth, doc_type, db_session, upload_dir, monkeypatch):
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    limit = 1024 * 1024
    ok = submit(api, headers, doc_type.id, [("ok.pdf", b"%PDF-" + b"a" * (limit - 5), "application/pdf")])
    assert ok.status_code == 201  # exactly at the limit is allowed
    too_big = submit(api, headers, doc_type.id, [("big.pdf", b"%PDF-" + b"a" * (limit - 4), "application/pdf")])
    assert too_big.status_code == 413
    assert app_count(db_session, student) == 1


def test_too_many_files_rejected(api, student_auth, doc_type, db_session):
    student, headers = student_auth
    files = [(f"f{i}.pdf", PDF_BYTES, "application/pdf") for i in range(uploads.MAX_FILES_PER_APPLICATION + 1)]
    r = submit(api, headers, doc_type.id, files)
    assert r.status_code == 400
    assert f"At most {settings.max_files_per_application} files" in r.json()["detail"]
    assert app_count(db_session, student) == 0


def test_file_count_limit_is_configurable_in_one_place(api, student_auth, doc_type, db_session, monkeypatch):
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_files_per_application", 2)
    three = [("a.pdf", PDF_BYTES, "application/pdf"), ("b.png", PNG_BYTES, "image/png"), ("c.png", PNG_BYTES, "image/png")]
    r = submit(api, headers, doc_type.id, three)
    assert r.status_code == 400 and "At most 2 files" in r.json()["detail"]
    assert submit(api, headers, doc_type.id, three[:2], categories=["marks_cards", "id_proof"]).status_code == 201
    assert app_count(db_session, student) == 1


def test_every_request_type_fits_within_the_file_limit():
    from app.services.request_forms import assert_config_consistent

    assert_config_consistent()  # raises if a request type needs more document slots than the limit


def test_one_bad_file_means_nothing_saved(api, student_auth, doc_type, db_session, upload_dir):
    student, headers = student_auth
    r = submit(api, headers, doc_type.id, [("good.pdf", PDF_BYTES, "application/pdf"), ("bad.txt", b"x", "text/plain")])
    assert r.status_code == 400
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_path_traversal_filename_is_neutralised(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [("../../evil.pdf", PDF_BYTES, "application/pdf")])
    assert r.status_code == 201
    assert r.json()["documents"][0]["original_filename"] == "evil.pdf"
    stored = files_on_disk(upload_dir)
    assert len(stored) == 2  # the evil-named file plus the helper's top-up for the other required slot
    assert all(upload_dir.resolve() in p.resolve().parents for p in stored)
    assert all(p.name != "evil.pdf" for p in stored)


def test_failure_while_saving_rolls_back_and_removes_files(api, student_auth, doc_type, db_session, upload_dir, monkeypatch):
    student, headers = student_auth
    real_store = uploads.store_file
    calls = {"n": 0}

    def flaky(application_id, item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_store(application_id, item)

    monkeypatch.setattr(uploads, "store_file", flaky)
    with pytest.raises(OSError):
        submit(api, headers, doc_type.id, [("a.pdf", PDF_BYTES, "application/pdf"), ("b.pdf", PDF_BYTES, "application/pdf")])
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []

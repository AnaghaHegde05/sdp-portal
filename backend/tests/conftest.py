"""Backend tests run against the real PostgreSQL database configured in backend/.env.

Prerequisites: `alembic upgrade head` and `python -m app.db.seed` have been run.
Every test that writes data uses a transaction that is rolled back, so tests leave no rows behind;
uploaded files go to a temporary folder.
"""
import json
import struct
import zlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine, get_db
from app.main import app
from app.core.request_types import REQUEST_TYPES
from app.models import DocumentType, Student

PASSWORD = "Passw0rd!x"


def make_png() -> bytes:
    """A tiny valid 1x1 PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PNG_BYTES = make_png()


def valid_details(code: str) -> dict:
    """Valid values for every field of a request type (see app/core/request_types.py)."""
    values = {}
    for f in REQUEST_TYPES[code]["fields"]:
        if f["type"] == "number":
            values[f["name"]] = f["min"]
        elif f["type"] == "select":
            values[f["name"]] = f["options"][0]
        elif f["type"] == "tel":
            values[f["name"]] = "9876543210"
        else:
            values[f["name"]] = "Test"
    return values


def code_for_id(doc_type_id: int) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            select(DocumentType.code).where(DocumentType.id == doc_type_id)
        ).scalar()


def submission(doc_type_id, files=(), fill=None, details=None, categories=None):
    """Build (data, parts) for POST /api/applications.

    `files` = (name, bytes, content_type) tuples, mapped onto the request type's document slots in order.
    Required slots left unfilled are topped up with `fill` bytes (default: a tiny PNG) so tests that
    care about something else still submit a complete, valid application. For a document type with no
    online configuration only the type id is sent (the API must reject it).
    """
    code = code_for_id(doc_type_id)
    data = {"document_type_id": str(doc_type_id)}
    if code not in REQUEST_TYPES:
        return data, None
    slots = [d["code"] for d in REQUEST_TYPES[code]["documents"]]
    required = [d["code"] for d in REQUEST_TYPES[code]["documents"] if d["required"]]
    items = [(slots[i] if i < len(slots) else f"extra{i}", f) for i, f in enumerate(files)]
    have = {c for c, _ in items}
    for c in required:
        if c not in have:
            items.append((c, (f"{c}.png", fill if fill is not None else PNG_BYTES, "image/png")))
    if categories is not None:
        items = [(c, f) for c, (_, f) in zip(categories, items)]
    data["form_data"] = json.dumps(valid_details(code) if details is None else details)
    data["file_categories"] = [c for c, _ in items]
    parts = [("files", f) for _, f in items]
    return data, parts or None


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Plain client for endpoints that need no data isolation (health checks, CORS)."""
    return TestClient(app)


@pytest.fixture
def db_session():
    connection = engine.connect()
    outer = connection.begin()
    # expire_on_commit=False and autoflush=False mirror the production SessionLocal
    # (app/db/session.py). With SQLAlchemy's defaults, commits expire loaded objects, which hid a
    # real stale-collection bug in payment/initiate's response from the whole test suite.
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def api(db_session, upload_dir):
    """Client whose requests use the rolled-back test session and a temporary upload folder."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_student(db_session):
    counter = {"n": 0}

    def _make(usn: str | None = None, **overrides) -> Student:
        counter["n"] += 1
        student = Student(
            usn=usn or f"01FE23BEV{counter['n']:03d}",
            full_name=overrides.pop("full_name", "Test Student"),
            department="Computer Science and Engineering",
            semester=7,
            cgpa=Decimal("8.50"),
            **overrides,
        )
        db_session.add(student)
        db_session.flush()
        return student

    return _make


@pytest.fixture
def register(api):
    def _register(usn: str, email: str = "student@example.com", password: str = PASSWORD):
        return api.post("/api/auth/register", json={"usn": usn, "email": email, "password": password})

    return _register


@pytest.fixture
def student_auth(make_student, register):
    """A registered student: returns (student, auth headers)."""
    student = make_student()
    token = register(student.usn).json()["access_token"]
    return student, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def doc_type(db_session) -> DocumentType:
    return db_session.scalars(select(DocumentType).where(DocumentType.is_active).order_by(DocumentType.id)).first()

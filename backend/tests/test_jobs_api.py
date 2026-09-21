"""API tests for job creation: success path vs failure/forbidden paths.

A failure (bad input / missing sample) or a permission error (auditor /
anonymous) must surface ONLY an error and must never be reported as accepted.
Only a real creation by bioops returns 201 with a job id.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module
from app.database import Base, get_db
from app.main import app
from app.models import Job, Sample

MINIMAL_FASTQ = "@SEQ1\nACGT\n+\nIIII\n"


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Do not let background pipeline runs touch a real database in tests.
    monkeypatch.setattr(api_module, "SessionLocal", factory)
    monkeypatch.setattr(api_module, "_run_job_background", lambda job_id: None)

    db = factory()
    db.add(
        Sample(
            name="demo-good",
            description="合格样例",
            is_broken=False,
            fastq_content=MINIMAL_FASTQ,
        )
    )
    db.commit()
    db.close()

    yield factory
    app.dependency_overrides.clear()


@pytest.fixture
def client(session_factory):
    return TestClient(app)


def _login(client, username, password):
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def bioops_headers(client):
    token = _login(client, "bioops", "fastq123456")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auditor_headers(client):
    token = _login(client, "auditor", "audit123456")
    return {"Authorization": f"Bearer {token}"}


def _assert_error_only(payload):
    """An error response must carry no success/accepted markers."""
    assert "accepted" not in payload
    assert "queued" not in payload
    assert "id" not in payload
    assert isinstance(payload["detail"], str)
    assert payload["detail"]


def test_bioops_create_success_returns_201_and_persists(client, bioops_headers, session_factory):
    resp = client.post("/api/jobs", json={"sampleId": 1}, headers=bioops_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["status"] == "pending"
    assert body["created_by"] == "bioops"

    db = session_factory()
    try:
        assert db.query(Job).count() == 1
        assert db.query(Job).first().id == body["id"]
    finally:
        db.close()


def test_auditor_create_forbidden_is_error_only(client, auditor_headers, session_factory):
    resp = client.post("/api/jobs", json={"sampleId": 1}, headers=auditor_headers)
    assert resp.status_code == 403
    _assert_error_only(resp.json())

    db = session_factory()
    try:
        assert db.query(Job).count() == 0
    finally:
        db.close()


def test_anonymous_create_unauthorized_is_error_only(client, session_factory):
    resp = client.post("/api/jobs", json={"sampleId": 1})
    assert resp.status_code == 401
    _assert_error_only(resp.json())

    db = session_factory()
    try:
        assert db.query(Job).count() == 0
    finally:
        db.close()


def test_missing_sample_is_error_only(client, bioops_headers, session_factory):
    resp = client.post("/api/jobs", json={"sampleId": 999}, headers=bioops_headers)
    assert resp.status_code == 404
    _assert_error_only(resp.json())

    db = session_factory()
    try:
        assert db.query(Job).count() == 0
    finally:
        db.close()


def test_empty_payload_is_error_only(client, bioops_headers, session_factory):
    resp = client.post("/api/jobs", json={}, headers=bioops_headers)
    assert resp.status_code == 400
    _assert_error_only(resp.json())

    db = session_factory()
    try:
        assert db.query(Job).count() == 0
    finally:
        db.close()

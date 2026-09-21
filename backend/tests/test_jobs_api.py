"""API tests for job creation: success vs failure/forbidden must be distinguishable.

Regression for the planted "false accept" behaviour where a 4xx was decorated
with accepted/queued and the UI toasted success. Errors must be errors; only a
genuinely created job returns 201.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module
from app.database import Base, get_db
from app import main as main_module
from app.main import app
from app.models import Sample


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    seed = testing_session_local()
    seed.add(
        Sample(
            name="good",
            description="合格样例",
            is_broken=False,
            fastq_content="@S\nACGT\n+\nIIII\n",
        )
    )
    seed.commit()
    seed.close()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    # Background task opens its own session via api.SessionLocal; lifespan
    # creates tables via main.engine — point both at the in-memory SQLite DB.
    monkeypatch.setattr(api_module, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _token(client, username, password):
    r = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200
    return r.json()["access_token"]


def test_auditor_forbidden_is_error_only(client):
    token = _token(client, "auditor", "audit123456")
    r = client.post(
        "/api/jobs",
        json={"sampleId": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body == {"detail": "仅运维账号可提交质控作业"}
    assert "accepted" not in body
    assert "queued" not in body


def test_anonymous_is_unauthorized(client):
    r = client.post("/api/jobs", json={"sampleId": 1})
    assert r.status_code == 401
    body = r.json()
    assert "accepted" not in body
    assert "queued" not in body


def test_missing_sample_is_error(client):
    token = _token(client, "bioops", "fastq123456")
    r = client.post(
        "/api/jobs",
        json={"sampleId": 999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body == {"detail": "样例不存在"}
    assert "accepted" not in body
    assert "queued" not in body


def test_empty_payload_is_error(client):
    token = _token(client, "bioops", "fastq123456")
    r = client.post(
        "/api/jobs",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body == {"detail": "请提供 sampleId 或 fastqText"}
    assert "accepted" not in body
    assert "queued" not in body


def test_bioops_success_creates_job(client):
    token = _token(client, "bioops", "fastq123456")
    r = client.post(
        "/api/jobs",
        json={"sampleId": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1
    assert body["created_by"] == "bioops"
    assert body["status"] in ("pending", "running", "success")
    assert len(body["stages"]) == 4
    assert "accepted" not in body
    assert "queued" not in body

    # The job is genuinely persisted and fetchable.
    r2 = client.get(
        "/api/jobs/1", headers={"Authorization": f"Bearer {token}"}
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == 1


def test_bioops_custom_fastq_success(client):
    token = _token(client, "bioops", "fastq123456")
    r = client.post(
        "/api/jobs",
        json={"fastqText": "@S\nACGT\n+\nIIII\n"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    assert r.json()["sample_name"] == "自定义输入"

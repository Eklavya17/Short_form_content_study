"""The production entry point (what gunicorn loads on Render)."""

import importlib
import sys

import pytest

from rq3 import storage

URL = "https://rq3-short-video-study.onrender.com"


def load_wsgi():
    sys.modules.pop("rq3.wsgi", None)
    return importlib.import_module("rq3.wsgi")


def test_wsgi_app_serves_both_pages_and_the_health_check(database_url, db, monkeypatch):
    monkeypatch.setenv(storage.DATABASE_URL_ENV, database_url)
    monkeypatch.setenv("RQ3_SECRET_KEY", "test-secret")
    app = load_wsgi().app
    client = app.test_client()

    health = client.get("/healthz", base_url=URL).get_json()
    assert health == {"ok": True, "clips": 44, "database": True}
    assert b"RQ3 feed demo" in client.get("/", base_url=URL).data
    assert b"Participant ID" in client.get("/participant?pid=T1", base_url=URL).data

    status = client.post("/participant/api/begin", json={"participant_id": "T1"}, base_url=URL).get_json()
    assert status["stage"] == "ready"


def test_wsgi_refuses_to_start_without_a_database_url(monkeypatch):
    monkeypatch.delenv(storage.DATABASE_URL_ENV, raising=False)
    monkeypatch.setenv("RQ3_SECRET_KEY", "test-secret")
    with pytest.raises(RuntimeError, match=storage.DATABASE_URL_ENV):
        load_wsgi()


def test_wsgi_refuses_to_start_without_a_secret_key(database_url, monkeypatch):
    monkeypatch.setenv(storage.DATABASE_URL_ENV, database_url)
    monkeypatch.delenv("RQ3_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RQ3_SECRET_KEY"):
        load_wsgi()

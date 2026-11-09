"""Admin commands: list, delete and links, against the test database."""

from rq3 import admin, storage
from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.study import Study


def test_list_and_delete(database_url, db, monkeypatch, capsys):
    monkeypatch.setenv(storage.DATABASE_URL_ENV, database_url)
    Study(load_catalog(), DEFAULT_CONFIG).begin(db, "P9", {})

    assert admin.main(["list"]) == 0
    assert "P9" in capsys.readouterr().out

    assert admin.main(["delete", "P9", "--yes"]) == 0
    assert storage.get_participant(db, "P9") is None
    assert admin.main(["delete", "P9", "--yes"]) == 1  # already gone


def test_delete_asks_first_and_keeps_data_on_no(database_url, db, monkeypatch):
    monkeypatch.setenv(storage.DATABASE_URL_ENV, database_url)
    Study(load_catalog(), DEFAULT_CONFIG).begin(db, "P9", {})
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert admin.main(["delete", "P9"]) == 1
    assert storage.get_participant(db, "P9") is not None


def test_links(capsys):
    assert admin.main(["links", "P001", "P002", "--base", "https://study.example.org/"]) == 0
    out = capsys.readouterr().out
    assert "https://study.example.org/participant?pid=P001" in out and "pid=P002" in out

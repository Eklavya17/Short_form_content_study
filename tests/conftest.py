"""Shared fixtures: one throwaway Postgres for the whole test run (pixeltable-pgserver,
from requirements-dev.txt). Database tests are skipped if it is not installed."""

import pytest

from rq3 import storage


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    pytest.importorskip("pixeltable_pgserver")
    from rq3.devdb import start_local_postgres

    url = start_local_postgres(tmp_path_factory.mktemp("rq3_postgres"))
    with storage.connect(url) as connection:
        storage.init_schema(connection)
    return url


@pytest.fixture
def db(database_url):
    """A connection to an empty set of RQ3 tables."""
    with storage.connect(database_url) as connection:
        storage.clear_all(connection)
        yield connection

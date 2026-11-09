"""A local Postgres for development and tests, with nothing installed system-wide.

Uses the pixeltable-pgserver package (requirements-dev.txt), which bundles
Postgres binaries. Data lives in .rq3_dev_db/ (git-ignored) and survives
restarts; delete that folder to start from scratch.
"""

from __future__ import annotations

import os
from pathlib import Path

from rq3.storage import DATABASE_URL_ENV

ROOT = Path(__file__).resolve().parent.parent
DEV_DATA_DIR = ROOT / ".rq3_dev_db"


def start_local_postgres(data_dir: Path = DEV_DATA_DIR) -> str:
    """Start (or reuse) a local Postgres in `data_dir` and return its URL.
    It stops when this Python process exits."""
    import pixeltable_pgserver

    data_dir.mkdir(parents=True, exist_ok=True)
    server = pixeltable_pgserver.get_server(data_dir, cleanup_mode="stop")
    return server.get_uri()


def database_url_or_local() -> tuple[str, bool]:
    """RQ3_DATABASE_URL if set, else a local development database.
    Returns the URL and whether it is the local one."""
    url = os.environ.get(DATABASE_URL_ENV)
    if url:
        return url, False
    return start_local_postgres(), True

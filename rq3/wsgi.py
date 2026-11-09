"""Production entry point for the RQ3 app (Render runs `gunicorn rq3.wsgi:app`).

Requires two settings on the host:
    RQ3_DATABASE_URL   the RQ3 Postgres database (never the RQ1 one)
    RQ3_SECRET_KEY     a long random string, so browser sessions survive restarts

Creates the rq3_ tables on start if they do not exist yet.
"""

from __future__ import annotations

import os

from rq3 import storage
from rq3.demo import app

if not os.environ.get("RQ3_SECRET_KEY"):
    raise RuntimeError("Set RQ3_SECRET_KEY on the host so browser sessions survive restarts.")

app.config["RQ3_DATABASE_URL"] = storage.database_url()
with storage.connect(app.config["RQ3_DATABASE_URL"]) as connection:
    storage.init_schema(connection)

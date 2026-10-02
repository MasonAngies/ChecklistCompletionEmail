"""Database connection helper for the Angie's backend (Supabase Postgres).

Same shape as the other repos' `src/db.py`, kept local for the usual reason: a
connection tweak in one tool must not be able to change another's behaviour.
"""

from __future__ import annotations

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def configured() -> bool:
    """Is a database configured at all?

    The report goes out perfectly well without one — the email is the job and the
    tables are the record — so every caller checks this rather than assuming.
    """
    return bool(os.environ.get("DATABASE_URL"))


def get_connection():
    """Open a new connection to the Supabase Postgres database.

    Reads DATABASE_URL from the environment (the IPv4 Session Pooler URI).
    Caller is responsible for closing the connection.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Check your .env file.")
    # TCP keepalives matter on the shared pooler: an idle connection is dropped
    # ("could not receive data from server"), which would otherwise turn a slow
    # write into a failed one.
    return psycopg2.connect(
        url,
        keepalives=1,
        keepalives_idle=60,
        keepalives_interval=20,
        keepalives_count=5,
    )

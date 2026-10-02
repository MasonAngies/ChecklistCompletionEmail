"""Apply this repo's schema to Supabase.

    ./.venv/bin/python scripts/init_db.py

Idempotent — every statement is CREATE ... IF NOT EXISTS, so running it again is
harmless. This repo owns `checklist_*` and touches nothing else.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import get_connection  # noqa: E402

SCHEMA_FILES = ["sql/checklists.sql"]


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = get_connection()
    try:
        for name in SCHEMA_FILES:
            path = os.path.join(root, name)
            print(f"applying {name}")
            with open(path) as handle, conn.cursor() as cur:
                cur.execute(handle.read())
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name,
                       (SELECT count(*) FROM information_schema.columns c
                         WHERE c.table_name = t.table_name AND c.table_schema='public')
                  FROM information_schema.tables t
                 WHERE table_schema='public' AND table_name LIKE 'checklist%'
                 ORDER BY table_name
                """
            )
            for table, columns in cur.fetchall():
                cur.execute(f'SELECT count(*) FROM "{table}"')
                print(f"  {table:<26} {columns:>3} cols, {cur.fetchone()[0]:>7} rows")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()

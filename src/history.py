"""Write down what each store had completed, as of the morning we looked.

Kintone mutates. A store can open last Tuesday's closing checklist today and
tick the boxes, and from then on Kintone says Tuesday was complete. Re-querying
a past date therefore cannot tell you what the DMs were shown that morning, or
what was true when it mattered. These tables are the record that can.

Nothing here may fail the morning run. The DMs' email is the job; the database
is the record, and a record that can take the job down with it is worth less
than no record at all. Every function swallows its own failures and says so.
"""

from __future__ import annotations

from typing import List, Optional

from src import db
from src.checklists import CLEANING_PASS, COLUMNS, Report, store_score


def record(
    report: Report,
    status: str,
    recipients: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
    dry_run: bool = False,
    backfill: bool = False,
) -> Optional[int]:
    """Write one run, its per-store rows, and any cleaning week.

    Returns the run id, or None if nothing was written. Never raises.
    """
    if not db.configured():
        print("  history: DATABASE_URL not set — not recording this run")
        return None

    try:
        conn = db.get_connection()
    except Exception as exc:  # noqa: BLE001 - the record must never fail the send
        print(f"  !! history unavailable ({type(exc).__name__}: {exc})")
        return None

    try:
        with conn.cursor() as cur:
            run_id = _write_run(cur, report, status, recipients, cc, dry_run, backfill)
            rows = _write_completion(cur, report, run_id)
            weeks = _write_cleaning(cur, report, run_id)
        conn.commit()
        print(f"  history: run {run_id} recorded ({rows} store/checklist row(s)"
              + (f", {weeks} cleaning week row(s)" if weeks else "") + ")")
        return run_id
    except Exception as exc:  # noqa: BLE001 - the record must never fail the send
        conn.rollback()
        print(f"  !! could not record this run ({type(exc).__name__}: {exc})")
        return None
    finally:
        conn.close()


def _write_run(cur, report: Report, status: str, recipients, cc,
               dry_run: bool, backfill: bool) -> int:
    done = graded = perfect = 0
    for store in report.stores:
        d, t = store_score(report, store.number)
        done += d
        graded += t
        perfect += bool(t) and d == t

    cur.execute(
        """
        INSERT INTO checklist_run (
            business_date, status, dry_run, backfill, store_count, completed,
            gradeable, stores_perfect, unmatched, recipients, cc, problems
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            report.business_date, status, dry_run, backfill, len(report.stores),
            done, graded, perfect, len(report.unmatched),
            ", ".join(recipients or []) or None,
            ", ".join(cc or []) or None,
            "; ".join(report.failures) or None,
        ),
    )
    return cur.fetchone()[0]


def _write_completion(cur, report: Report, run_id: int) -> int:
    """Upsert one row per store per checklist.

    COALESCE on `completed` is the important part: a run whose Kintone app was
    unreadable writes NULL, and that must never erase a day already recorded as
    complete. The same guard keeps a re-run from downgrading a known answer.
    """
    rows = []
    for store in report.stores:
        for key, *_ in COLUMNS:
            count, first = report.detail.get((store.number, key), (0, None))
            rows.append((
                report.business_date, store.number, key,
                report.done[(store.number, key)], count, first,
                store.name, store.district, store.dm, run_id,
            ))
    if not rows:
        return 0
    cur.executemany(
        """
        INSERT INTO checklist_completion (
            business_date, store_number, checklist, completed, submissions,
            first_submitted_at, store_name, district, district_manager, run_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (business_date, store_number, checklist) DO UPDATE SET
            completed = COALESCE(EXCLUDED.completed, checklist_completion.completed),
            submissions = GREATEST(EXCLUDED.submissions, checklist_completion.submissions),
            first_submitted_at = LEAST(
                COALESCE(EXCLUDED.first_submitted_at, checklist_completion.first_submitted_at),
                COALESCE(checklist_completion.first_submitted_at, EXCLUDED.first_submitted_at)
            ),
            store_name = EXCLUDED.store_name,
            district = EXCLUDED.district,
            district_manager = EXCLUDED.district_manager,
            run_id = EXCLUDED.run_id,
            updated_at = now()
        """,
        rows,
    )
    return len(rows)


def _write_cleaning(cur, report: Report, run_id: int) -> int:
    """Upsert the Mon-Sun cleaning week, when this run graded one.

    Every active store gets a row, including the ones that filed nothing —
    `submitted = FALSE` with a zero percentage. A store missing from the table
    would otherwise be indistinguishable from a week nobody graded.
    """
    if not report.cleaning_week or not report.cleaning_ok or not report.cleaning_total:
        return 0
    week_start, week_end = report.cleaning_week
    total = report.cleaning_total
    rows = []
    for store in report.stores:
        filled = report.cleaning_filled.get(store.number)
        submitted = filled is not None
        filled = filled or 0
        pct = filled / total
        rows.append((
            week_start, week_end, store.number, filled, total, round(pct, 4),
            pct >= CLEANING_PASS, submitted,
            store.name, store.district, store.dm, run_id,
        ))
    cur.executemany(
        """
        INSERT INTO checklist_cleaning_week (
            week_start, week_end, store_number, photos_filled, photos_total,
            pct, passed, submitted, store_name, district, district_manager, run_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (week_start, store_number) DO UPDATE SET
            week_end = EXCLUDED.week_end,
            photos_filled = EXCLUDED.photos_filled,
            photos_total = EXCLUDED.photos_total,
            pct = EXCLUDED.pct,
            passed = EXCLUDED.passed,
            submitted = EXCLUDED.submitted,
            store_name = EXCLUDED.store_name,
            district = EXCLUDED.district,
            district_manager = EXCLUDED.district_manager,
            run_id = EXCLUDED.run_id,
            updated_at = now()
        """,
        rows,
    )
    return len(rows)

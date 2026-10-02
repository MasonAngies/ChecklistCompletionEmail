"""Grade past business dates into the database. Sends nothing, ever.

    ./.venv/bin/python scripts/backfill.py              # the last 30 days
    ./.venv/bin/python scripts/backfill.py 60           # the last 60 days
    ./.venv/bin/python scripts/backfill.py 2026-09-01 2026-09-30

Dates run oldest first so a watcher sees history fill forwards. Each date is
independent: one bad day is reported and the rest still land, because a backfill
that abandons three weeks over a single Kintone hiccup is worse than useless.

A caveat worth keeping in mind when reading backfilled rows: they are what
Kintone says TODAY about those days, not what the DMs were shown that morning.
A store that went back and ticked last week's boxes reads as complete here.
Rows written by the daily 7:29 run are contemporaneous; these are not, and
`checklist_run.backfill` is how you tell them apart.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db, history  # noqa: E402
from src.checklists import KintoneClient, az_today, build_report  # noqa: E402

DEFAULT_DAYS = 30


def _dates() -> list:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    end = az_today() - timedelta(days=1)          # yesterday, the last full day

    if len(args) >= 2:
        try:
            start, end = date.fromisoformat(args[0]), date.fromisoformat(args[1])
        except ValueError:
            sys.exit("Use YYYY-MM-DD YYYY-MM-DD, or a number of days.")
    elif args:
        try:
            days = int(args[0])
        except ValueError:
            sys.exit(f"Not a number of days: {args[0]!r}")
        start = end - timedelta(days=days - 1)
    else:
        start = end - timedelta(days=DEFAULT_DAYS - 1)

    if start > end:
        sys.exit(f"Start {start} is after end {end}.")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def main() -> None:
    if not db.configured():
        sys.exit("DATABASE_URL is not set — a backfill with nowhere to write.")

    days = _dates()
    print(f"Backfilling {len(days)} day(s): {days[0]} .. {days[-1]}")
    # One client for the whole run: each date is several Kintone queries, and a
    # fresh session per day would be 30x the handshakes for no benefit.
    client = KintoneClient()
    failed = []

    for when in days:
        print(f"\n{when} ({when:%A})")
        try:
            report = build_report(when, client=client)
            history.record(report, "built", backfill=True)
        except Exception as exc:  # noqa: BLE001 - one bad day must not end the run
            failed.append(f"{when}: {type(exc).__name__}: {exc}")
            print(f"  !! {type(exc).__name__}: {exc}")

    print(f"\nDone. {len(days) - len(failed)} of {len(days)} day(s) recorded.")
    if failed:
        print("Failed:")
        for line in failed:
            print(f"  {line}")
        sys.exit(1)


if __name__ == "__main__":
    main()

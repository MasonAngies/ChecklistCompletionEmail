"""Modal deployment for the checklist completion report.

DELIBERATELY UNSCHEDULED, like the DC pick sheets: Modal caps this workspace at
five scheduled functions and all five are taken. The punch report's
`followup_report` (7:29 AM Arizona, repo Angies) calls it after the pick sheets:

    modal.Function.from_name("angies-checklists", "daily_run").remote()

If a scheduled slot is ever freed, uncomment the `schedule=` line below and
remove that caller — in the same sitting, or the report goes out twice.

Deploy:  ./.venv/bin/modal deploy modal_app.py
Dry run: ./.venv/bin/modal run modal_app.py::test_dry_run
Re-run a date:
         ./.venv/bin/modal run modal_app.py::rerun --business-date 2026-09-27
"""

from __future__ import annotations

import sys

import modal

app = modal.App("angies-checklists")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(
        ".",
        remote_path="/root/app",
        ignore=[".venv", ".git", "**/__pycache__", "*.pyc", ".env", "out"],
    )
)

# Its own secret. A tool that needs a new key must never be a reason to rebuild
# another tool's secret.
#
# Contents: KINTONE_SUBDOMAIN, the seven KINTONE_*_APP_ID / _API_TOKEN pairs in
# .env.example, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
# GRAPH_SENDER_ADDRESS, CHECKLIST_RECIPIENTS, CHECKLIST_CC, ALERT_RECIPIENTS,
# TEST_RECIPIENT, CHECKLIST_DRY_RUN
secret = modal.Secret.from_name("angies-checklists")


def _app_path() -> None:
    if "/root/app" not in sys.path:
        sys.path.insert(0, "/root/app")


@app.function(
    image=image,
    secrets=[secret],
    timeout=900,
    retries=modal.Retries(max_retries=2, initial_delay=60.0, backoff_coefficient=2.0),
    # schedule=modal.Cron("29 14 * * *"),  # 14:29 UTC = 7:29 AM Arizona.
    #   Commented out ONLY because the workspace's five scheduled slots are full.
)
def daily_run() -> str:
    """Yesterday's checklists. Called by the punch report's 7:29 cron."""
    _app_path()
    from scripts.send_checklist_report import run

    return run()


@app.function(image=image, secrets=[secret], timeout=900)
def rerun(business_date: str = "", dry_run: bool = False) -> str:
    """Rebuild and resend any business date:

        ./.venv/bin/modal run modal_app.py::rerun --business-date 2026-09-27
        ./.venv/bin/modal run modal_app.py::rerun --business-date 2026-09-27 --dry-run
    """
    _app_path()
    from datetime import date as _date

    from scripts.send_checklist_report import run

    when = None
    if business_date:
        try:
            when = _date.fromisoformat(business_date)
        except ValueError:
            raise SystemExit(f"Not a date: {business_date!r}. Use YYYY-MM-DD.")
    return run(business_date=when, dry_run=True if dry_run else None)


@app.function(image=image, secrets=[secret], timeout=900)
def test_dry_run() -> str:
    """Send yesterday's report to the alert list only, whatever the secret says:

        ./.venv/bin/modal run modal_app.py::test_dry_run
    """
    _app_path()
    from scripts.send_checklist_report import run

    return run(dry_run=True)


@app.function(image=image, secrets=[secret], timeout=900)
def test_build_only() -> str:
    """Build yesterday's report and send nothing at all. The safest smoke test:

        ./.venv/bin/modal run modal_app.py::test_build_only
    """
    _app_path()
    from scripts.send_checklist_report import run

    return run(send=False)


@app.function(image=image, secrets=[secret], timeout=120)
def show_config() -> str:
    """Who tomorrow's report would go to — reads the directory, sends nothing:

        ./.venv/bin/modal run modal_app.py::show_config

    Worth having because the list is no longer written down anywhere: it is
    derived from the Store Directory at send time, so this is the only way to
    see it without waiting for 7:29.
    """
    _app_path()
    import os

    from src.checklists import KintoneClient, build_roster, load_stores
    from src.graph_mailer import parse_recipients

    dry = os.environ.get("CHECKLIST_DRY_RUN", "1").strip() != "0"
    alert = parse_recipients("ALERT_RECIPIENTS", "TEST_RECIPIENT")
    lines = [f"mode     : {'DRY RUN (sends to the alert list only)' if dry else 'LIVE'}"]
    try:
        roster = build_roster(load_stores(KintoneClient()))
        lines += [
            f"to       : {', '.join(roster.to)}",
            f"cc       : {', '.join(roster.cc) or '(none)'}",
        ]
        if roster.rejected:
            lines.append(f"SKIPPED  : {', '.join(roster.rejected)} (bad address/domain)")
        if roster.missing:
            lines.append(f"NO DM    : {', '.join(roster.missing)}")
    except Exception as exc:  # noqa: BLE001
        fallback = parse_recipients("CHECKLIST_RECIPIENTS")
        lines += [f"to       : !! directory unreadable ({type(exc).__name__}: {exc})",
                  f"fallback : {', '.join(fallback) or '(empty)'}"]
    lines.append(f"alerts   : {', '.join(alert) or '(none)'}")
    print("\n".join(lines))
    return "\n".join(lines)

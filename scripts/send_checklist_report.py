"""Grade yesterday's checklists for every active store and email the report.

    python3 scripts/send_checklist_report.py                 # yesterday (Phoenix)
    python3 scripts/send_checklist_report.py 2026-09-27      # a specific business date
    python3 scripts/send_checklist_report.py --dry-run       # force send to Mason only
    python3 scripts/send_checklist_report.py --live          # force send to the real list
    python3 scripts/send_checklist_report.py --out=out       # also write the HTML to ./out
    python3 scripts/send_checklist_report.py --no-email      # build only, send nothing
    python3 scripts/send_checklist_report.py --to=someone@angies.com

With no date, the business date is yesterday in Arizona — computed from UTC plus
a fixed offset, never from the runner's clock. A Sunday business date (the
Monday email) also carries last week's Weekly Cleaning column.

Live vs dry run comes from CHECKLIST_DRY_RUN in the secret ("1" = only the alert
list gets it, with [DRY RUN] in the subject) unless --dry-run / --live / --to
overrides it.
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import email_body  # noqa: E402
from src.checklists import az_today, build_report  # noqa: E402
from src.graph_mailer import parse_recipients, send_email  # noqa: E402

LOGO = ROOT / "assets" / "logo_navy.png"


def _flag(name: str) -> bool:
    return any(a == f"--{name}" for a in sys.argv[1:])


def _opt(name: str) -> str:
    prefix = f"--{name}="
    for arg in sys.argv[1:]:
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return ""


def _positional() -> list:
    return [a for a in sys.argv[1:] if not a.startswith("--")]


def _alert_recipients() -> list:
    return parse_recipients("ALERT_RECIPIENTS", "TEST_RECIPIENT")


def _send_alert(title: str, lines: list) -> None:
    """Tell Mason. Never raises — a failing alert must not mask the real error."""
    to = _alert_recipients()
    if not to:
        print("  !! no ALERT_RECIPIENTS / TEST_RECIPIENT set — alert not sent")
        return
    try:
        send_email(subject=f"[ALERT] Checklist report: {title}",
                   html_body=email_body.alert(title, lines), to=to)
        print(f"  alert emailed to {', '.join(to)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  !! alert email failed: {type(exc).__name__}: {exc}")


def run(
    business_date: Optional[date] = None,
    dry_run: Optional[bool] = None,
    send: bool = True,
    out_dir: str = "",
    to_override: Optional[list] = None,
) -> str:
    """Build and send one day's report. Returns a one-line summary.

    Raises on failure, after alerting, so Modal marks the run red.
    """
    business_date = business_date or az_today() - timedelta(days=1)
    if dry_run is None:
        dry_run = os.environ.get("CHECKLIST_DRY_RUN", "1").strip() != "0"

    print(f"Checklist completion for {business_date} ({business_date:%A})")
    try:
        report = build_report(business_date)
    except Exception as exc:
        _send_alert("run failed", [f"Business date {business_date}",
                                   f"{type(exc).__name__}: {exc}",
                                   "No report went out."])
        raise

    html = email_body.render(report)
    total_done = sum(1 for v in report.done.values() if v)
    total = sum(1 for v in report.done.values() if v is not None)
    summary = (f"{business_date}: {total_done}/{total} checklists across "
               f"{len(report.stores)} stores, {len(report.unmatched)} unmatched")

    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        path = Path(out_dir) / f"checklists_{business_date}.html"
        # Inline the logo so the preview shows it without the cid: part.
        logo = "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode()
        path.write_text(html.replace(f"cid:{email_body.LOGO_CID}", logo))
        print(f"  wrote {path}")

    if report.failures:
        _send_alert("some checklists couldn't be read",
                    [f"Business date {business_date}", *report.failures,
                     "The report still went out with those columns marked n/a."])

    if not send:
        print(f"Done. {summary} (not sent)")
        return summary

    subject = f"Checklist Completion — {business_date:%a %-m/%-d}"
    cc: list = []
    if to_override:
        to = to_override
    elif dry_run:
        to = _alert_recipients()
        subject = f"[DRY RUN] {subject}"
    else:
        to = parse_recipients("CHECKLIST_RECIPIENTS")
        cc = parse_recipients("CHECKLIST_CC")
        if not to:
            _send_alert("no recipients", ["CHECKLIST_RECIPIENTS is empty in the secret.",
                                          "Live run refused to send."])
            raise SystemExit("CHECKLIST_RECIPIENTS is empty — refusing a live send.")
    if not to:
        raise SystemExit("No recipients (ALERT_RECIPIENTS / TEST_RECIPIENT empty).")

    try:
        send_email(subject=subject, html_body=html, to=to, cc=cc or None,
                   inline_images=[(email_body.LOGO_CID, LOGO.read_bytes())])
    except Exception as exc:
        _send_alert("send failed", [f"Business date {business_date}",
                                    f"{type(exc).__name__}: {exc}"])
        raise
    print(f"  sent to {', '.join(to)}" + (f" (cc {', '.join(cc)})" if cc else ""))
    print(f"Done. {summary}")
    return summary


def main() -> None:
    args = _positional()
    when = None
    if args:
        try:
            when = date.fromisoformat(args[0])
        except ValueError:
            sys.exit(f"Not a date: {args[0]!r}. Use YYYY-MM-DD.")
    dry = True if _flag("dry-run") else False if _flag("live") else None
    to = [a.strip() for a in _opt("to").split(",") if a.strip()]
    run(business_date=when, dry_run=dry, send=not _flag("no-email"),
        out_dir=_opt("out"), to_override=to or None)


if __name__ == "__main__":
    main()

"""HTML for the checklist completion email, styled to the Angie's brand kit.

Brand kit (Angies/Angies Brand Kit 6.25, March 2026 v1.0):
    Navy  #1F2F44  primary        Red    #C7372F  primary
    Blue  #A8C8D8  accent         Cream  #EDE8DC  background
    Bebas Neue for headings, DM Sans for everything else.

Email clients are the constraint, not the kit. Everything is inline-styled
tables; the web fonts are linked for Apple Mail / iOS and fall back to Arial
elsewhere (Outlook ignores <link>). The logo is a PNG sent as an inline `cid:`
part (assets/logo_navy.png, rendered from "Angies Logo for Red_BlueBG.svg" with
the navy baked in) because no mainstream client renders SVG in email.

This module lays out whatever Report it is handed. If a cell is wrong, the bug
is in src/checklists.py.
"""

from __future__ import annotations

import html
from itertools import groupby
from typing import List

from src.checklists import CLEANING_PASS, COLUMNS, Report, store_score

NAVY = "#1F2F44"
RED = "#C7372F"
BLUE = "#A8C8D8"
CREAM = "#EDE8DC"
WHITE = "#FFFFFF"
RED_TINT = "#F7DEDC"     # missed cell
BLUE_TINT = "#E4EEF3"    # passed cleaning cell
ROW_ALT = "#F8F6F1"      # zebra, a whisper of cream
MUTED = "#6B7482"
LINE = "#E3DED2"

LOGO_CID = "angies-logo"

_DISPLAY = "'Bebas Neue','Arial Narrow',Arial,sans-serif"
_BODY = "'DM Sans',Arial,Helvetica,sans-serif"

_WIDTH = 680


def _e(s) -> str:
    return html.escape(str(s))


def _long_date(d) -> str:
    return f"{d:%a}, {d:%b} {d.day}"


def _short(d) -> str:
    return f"{d.month}/{d.day}"


# --- cells ---------------------------------------------------------------------

_CELL = (f"padding:9px 4px;text-align:center;font-family:{_BODY};font-size:15px;"
         f"border-bottom:1px solid {LINE};")


def _status_cell(value) -> str:
    if value is None:
        return f'<td style="{_CELL}color:{MUTED};font-size:11px;">n/a</td>'
    if value:
        return f'<td style="{_CELL}color:{NAVY};font-weight:700;">&#10003;</td>'
    return (f'<td style="{_CELL}background:{RED_TINT};color:{RED};font-weight:700;">'
            f'&#10007;</td>')


def _cleaning_cell(report: Report, number: str) -> str:
    if not report.cleaning_ok:
        return f'<td style="{_CELL}color:{MUTED};font-size:11px;">n/a</td>'
    pct = report.cleaning.get(number)
    if pct is None:
        return (f'<td style="{_CELL}background:{RED_TINT};color:{RED};font-size:12px;'
                f'font-weight:700;">None</td>')
    label = f"{round(pct * 100)}%"
    if pct >= CLEANING_PASS:
        return (f'<td style="{_CELL}background:{BLUE_TINT};color:{NAVY};font-size:13px;'
                f'font-weight:700;">{label}</td>')
    return (f'<td style="{_CELL}background:{RED_TINT};color:{RED};font-size:13px;'
            f'font-weight:700;">{label}</td>')


def _score_cell(done: int, total: int) -> str:
    if total and done == total:
        pill = (f'<span style="display:inline-block;background:{NAVY};color:{WHITE};'
                f'border-radius:10px;padding:2px 8px;font-size:12px;font-weight:700;">'
                f'{done}/{total}</span>')
    else:
        pill = (f'<span style="color:{RED};font-size:13px;font-weight:700;">'
                f'{done}/{total}</span>')
    return f'<td style="{_CELL}">{pill}</td>'


# --- blocks --------------------------------------------------------------------

def _header(report: Report) -> str:
    return f"""
<tr><td style="background:{NAVY};padding:28px 32px 26px;border-radius:8px 8px 0 0;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
    <td valign="middle" width="140">
      <img src="cid:{LOGO_CID}" width="133" height="78" alt="Angie's — The New Fast Food"
           style="display:block;border:0;width:133px;height:78px;">
    </td>
    <td valign="middle" align="right" style="font-family:{_BODY};">
      <div style="font-size:12px;font-weight:500;letter-spacing:3px;color:{BLUE};
                  text-transform:uppercase;">Checklist Completion</div>
      <div style="font-family:{_DISPLAY};font-size:40px;line-height:44px;color:{WHITE};
                  letter-spacing:1px;margin-top:4px;">{_e(_long_date(report.business_date))}</div>
    </td>
  </tr></table>
</td></tr>"""


def _summary(report: Report) -> str:
    done = total = perfect = 0
    for store in report.stores:
        d, t = store_score(report, store.number)
        done += d
        total += t
        perfect += bool(t) and d == t
    pct = round(100 * done / total) if total else 0

    per_col = []
    for key, header, *_ in COLUMNS:
        if not report.columns_ok[key]:
            continue
        n = sum(bool(report.done[(s.number, key)]) for s in report.stores)
        per_col.append(
            f'<td align="center" style="font-family:{_BODY};padding:0 4px;">'
            f'<div style="font-size:11px;font-weight:500;letter-spacing:1.5px;color:{MUTED};'
            f'text-transform:uppercase;white-space:nowrap;">{_e(header)}</div>'
            f'<div style="font-size:16px;font-weight:700;color:{NAVY};margin-top:2px;">'
            f'{n}<span style="color:{MUTED};font-weight:400;font-size:12px;">/{len(report.stores)}</span>'
            f'</div></td>'
        )

    cleaning = ""
    if report.cleaning_week and report.cleaning_ok:
        passed = sum(report.cleaning.get(s.number, 0) >= CLEANING_PASS for s in report.stores)
        wk0, wk1 = report.cleaning_week
        cleaning = (
            f'<div style="font-family:{_BODY};font-size:13px;color:{NAVY};margin-top:14px;">'
            f'<b>Weekly cleaning {_short(wk0)}&ndash;{_short(wk1)}:</b> {passed} of '
            f'{len(report.stores)} stores at {round(CLEANING_PASS * 100)}%+ photos.</div>'
        )

    return f"""
<tr><td style="background:{CREAM};padding:24px 32px;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
    <td valign="middle" width="150" style="font-family:{_DISPLAY};font-size:56px;line-height:52px;
        color:{RED if pct < 100 else NAVY};">{pct}%</td>
    <td valign="middle" style="font-family:{_BODY};font-size:15px;line-height:22px;color:{NAVY};">
      <b>{done} of {total}</b> daily checklists completed.<br>
      <b>{perfect} of {len(report.stores)}</b> stores completed every one.
    </td>
  </tr></table>
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:18px;">
    <tr>{''.join(per_col)}</tr>
  </table>
  {cleaning}
</td></tr>"""


def _banner(report: Report) -> str:
    if not report.failures:
        return ""
    names = ", ".join(_e(f.split(":")[0]) for f in report.failures)
    return f"""
<tr><td style="padding:16px 32px 0;">
  <div style="background:{RED_TINT};border-left:4px solid {RED};padding:10px 14px;
              font-family:{_BODY};font-size:13px;color:{NAVY};">
    <b>Couldn't read {names} from Kintone.</b> Those columns show <i>n/a</i> and are left
    out of the scores &mdash; they are not misses.
  </div>
</td></tr>"""


def _col_headers(report: Report) -> str:
    th = (f"padding:8px 4px;font-family:{_BODY};font-size:10px;font-weight:700;"
          f"letter-spacing:1px;color:{NAVY};text-transform:uppercase;text-align:center;"
          f"background:{CREAM};line-height:13px;")
    cells = [f'<td style="{th}text-align:left;padding-left:12px;">Store</td>']
    for _key, header, *_ in COLUMNS:
        cells.append(f'<td style="{th}">{_e(header).replace(" ", "<br>")}</td>')
    if report.cleaning_week:
        wk0, wk1 = report.cleaning_week
        cells.append(f'<td style="{th}">Cleaning<br>{_short(wk0)}&ndash;{_short(wk1)}</td>')
    cells.append(f'<td style="{th}">Done</td>')
    return f"<tr>{''.join(cells)}</tr>"


def _district(report: Report, district: str, stores: list) -> str:
    ncols = len(COLUMNS) + 2 + bool(report.cleaning_week)
    done = sum(store_score(report, s.number)[0] for s in stores)
    total = sum(store_score(report, s.number)[1] for s in stores)
    dm = stores[0].dm if stores else ""

    rows = [
        f'<tr><td colspan="{ncols}" style="height:22px;line-height:22px;font-size:0;">&nbsp;</td></tr>',
        f'<tr><td colspan="{ncols}" style="background:{NAVY};padding:9px 12px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td style="font-family:{_DISPLAY};font-size:22px;line-height:24px;color:{WHITE};'
        f'letter-spacing:1px;">{_e(district)}'
        + (f'<span style="font-family:{_BODY};font-size:12px;color:{BLUE};letter-spacing:0;">'
           f'&nbsp;&nbsp;{_e(dm)}</span>' if dm else "")
        + f'</td><td align="right" style="font-family:{_BODY};font-size:13px;font-weight:700;'
        f'color:{WHITE};">{done}/{total}</td></tr></table></td></tr>',
        _col_headers(report),
    ]
    for i, store in enumerate(stores):
        bg = ROW_ALT if i % 2 else WHITE
        cells = [
            f'<td style="padding:8px 4px 8px 12px;border-bottom:1px solid {LINE};'
            f'font-family:{_BODY};color:{NAVY};">'
            f'<div style="font-size:14px;font-weight:700;">{_e(store.number)}</div>'
            f'<div style="font-size:11px;color:{MUTED};line-height:14px;">{_e(store.name)}</div></td>'
        ]
        for key, *_ in COLUMNS:
            cells.append(_status_cell(report.done[(store.number, key)]))
        if report.cleaning_week:
            cells.append(_cleaning_cell(report, store.number))
        cells.append(_score_cell(*store_score(report, store.number)))
        rows.append(f'<tr style="background:{bg};">{"".join(cells)}</tr>')
    return "\n".join(rows)


def _unmatched(report: Report) -> str:
    if not report.unmatched:
        return ""
    items = "".join(
        f'<tr><td style="padding:4px 8px 4px 0;font-family:{_BODY};font-size:12px;color:{NAVY};'
        f'white-space:nowrap;">{_e(u.source)}</td>'
        f'<td style="padding:4px 8px;font-family:{_BODY};font-size:12px;color:{RED};font-weight:700;">'
        f'&ldquo;{_e(u.raw_store) or "(blank)"}&rdquo;</td>'
        f'<td style="padding:4px 8px;font-family:{_BODY};font-size:12px;color:{MUTED};">'
        f'{_e(u.who)}{" &middot; " if u.who and u.when else ""}{_e(u.when)}</td></tr>'
        for u in report.unmatched
    )
    return f"""
<tr><td style="padding:28px 32px 0;">
  <div style="font-family:{_BODY};font-size:12px;font-weight:500;letter-spacing:3px;color:{RED};
              text-transform:uppercase;">Couldn't match to a store</div>
  <div style="font-family:{_BODY};font-size:13px;color:{NAVY};margin:6px 0 8px;line-height:19px;">
    These were submitted, but the store field doesn't hold a store number from the directory, so
    they aren't counted above. Have the store enter its 5-digit number.
  </div>
  <table cellpadding="0" cellspacing="0" border="0">{items}</table>
</td></tr>"""


def _footer(report: Report) -> str:
    legend = (f'<span style="color:{NAVY};font-weight:700;">&#10003;</span> completed &nbsp;&middot;&nbsp; '
              f'<span style="color:{RED};font-weight:700;">&#10007;</span> not submitted')
    clean = ""
    if report.cleaning_week:
        clean = (f" &nbsp;&middot;&nbsp; Cleaning = share of photo tasks with a picture; "
                 f"{round(CLEANING_PASS * 100)}% passes")
    return f"""
<tr><td style="padding:28px 32px 32px;font-family:{_BODY};font-size:12px;line-height:18px;color:{MUTED};">
  {legend}{clean}.<br>
  Opening counts either opening checklist. Q&amp;FS and Rush Readiness are due once per AM and PM shift.
  Stores and districts come from the Kintone Store Directory.
</td></tr>"""


def render(report: Report) -> str:
    body: List[str] = []
    for district, group in groupby(report.stores, key=lambda s: s.district):
        body.append(_district(report, district, list(group)))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:{CREAM};">
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{CREAM};">
<tr><td align="center" style="padding:24px 8px;">
<table cellpadding="0" cellspacing="0" border="0" width="{_WIDTH}"
       style="max-width:{_WIDTH}px;width:100%;background:{WHITE};border-radius:8px;">
{_header(report)}
{_summary(report)}
{_banner(report)}
<tr><td style="padding:0 20px;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;">
  {''.join(body)}
  </table>
</td></tr>
{_unmatched(report)}
{_footer(report)}
</table>
</td></tr></table>
</body></html>"""


def alert(title: str, lines: List[str]) -> str:
    """Plain failure notice for ALERT_RECIPIENTS — never the DMs."""
    items = "".join(f"<li style='margin:4px 0;'>{_e(line)}</li>" for line in lines)
    return f"""<html><body style="margin:0;padding:24px;background:{CREAM};font-family:{_BODY};color:{NAVY};">
<div style="max-width:640px;background:{WHITE};border-top:4px solid {RED};padding:20px 24px;border-radius:6px;">
<div style="font-family:{_DISPLAY};font-size:26px;color:{RED};letter-spacing:1px;">{_e(title)}</div>
<ul style="font-size:14px;line-height:20px;padding-left:18px;">{items}</ul>
<div style="font-size:12px;color:{MUTED};">Checklist completion report &middot; repo ChecklistCompletionEmail &middot; Modal app angies-checklists</div>
</div></body></html>"""

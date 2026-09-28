# Checklist Completion Email

A daily email that shows, store by store, whether yesterday's Kintone checklists
were completed. It goes out at 7:29 AM Arizona, after the punch report and the DC
pick sheets.

## What it grades

One Arizona business date (yesterday), for every **Active** store in the Store
Directory (Kintone app 897), grouped by district with the DM's name:

| Column | Kintone app | Requirement |
|---|---|---|
| Opening | 841 **or** 842 | at least one record from either |
| Q&FS AM / PM | 807 Quality & Food Safety | one per shift |
| Rush AM / PM | 814 Rush Readiness | one per shift |
| Closing | 810 | one |
| Cleaning *(Mondays only)* | 846 Weekly Cleaning | last Mon–Sun week, ≥ 75% of photo tasks with a picture |

**Done** is completed / gradeable daily checklists (out of 6). Cleaning is shown
as a percentage and is not part of Done.

## How records are matched

- **Store:** the five-digit store number in the checklist's store field, or failing
  that, the store account that submitted it ("11108 - Gilbert & Queen Creek").
  Anything that still can't be matched is listed at the bottom of the email.
- **Date:** the record's own Date field (Q&FS: Date and time), so a closing filed
  at 12:20 AM counts for the night before.
- **Shift:** the AM/PM checkbox. If both or neither are ticked, submission time
  decides (before noon = AM).
- **Cleaning:** every store record created in the week, photo fields unioned,
  divided by the number of photo fields on the form (47 today, read live).

## Running it

```
./.venv/bin/python scripts/send_checklist_report.py --no-email --out=out   # build, preview in out/
./.venv/bin/python scripts/send_checklist_report.py 2026-09-27 --dry-run   # send to the alert list
./.venv/bin/python scripts/send_checklist_report.py 2026-09-27 --to=you@angies.com
```

## Deployment

Modal app `angies-checklists`, secret `angies-checklists`. It is **not scheduled**
itself — the workspace's five cron slots are full — so the punch report's
`followup_report` (repo Angies, 7:29 AM AZ) calls it last:

```python
modal.Function.from_name("angies-checklists", "daily_run").remote()
```

That call is wrapped so a checklist failure can never take down the punch report.

- Code change: `./.venv/bin/modal deploy modal_app.py` (git push does not deploy).
- Who gets it: `./.venv/bin/modal run modal_app.py::show_config`.
- Go live: set `CHECKLIST_RECIPIENTS` and `CHECKLIST_DRY_RUN=0` in the secret.
- Resend a date: `./.venv/bin/modal run modal_app.py::rerun --business-date 2026-09-27`.

## Branding

Colors, type and logo follow the Angie's Brand Kit (March 2026 v1.0): navy
`#1F2F44`, red `#C7372F`, blue `#A8C8D8`, cream `#EDE8DC`; Bebas Neue headings,
DM Sans body. `assets/logo_navy.png` is "Angies Logo for Red_BlueBG.svg" rendered
on navy, sent as an inline image because email clients don't render SVG.

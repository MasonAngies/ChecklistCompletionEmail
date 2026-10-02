# Checklist Completion Email — working notes

See README.md for what the report grades. This file is about working here.

## Isolation

This tool lives in its own repo, its own Modal app (`angies-checklists`) and its
own secret (`angies-checklists`). It keeps its own copy of the Kintone client and
Graph mailer on purpose. Work on `main`. **The GitHub repo is public** — tokens
live only in `.env` (gitignored) and the Modal secret.

The only footprint outside this repo is one guarded call at the end of
`followup_report` in the Angies (punch report) repo's `modal_app.py`. Moving or
removing it is a two-sided change: edit there AND redeploy that app.

## Conventions

- Python 3.9 in `./.venv`. No argparse: `sys.argv`, `--flag` / `--opt=value`.
- Kintone field codes are generic (`Text_2`, `Check_box_19`). Pin them as `_F_*`
  constants in `src/checklists.py` with the real label as a comment; never inline one.
- `AZ_OFFSET = timedelta(hours=-7)`. Arizona has no DST.
- Business rules live in `src/checklists.py` only. `src/email_body.py` lays out
  whatever `Report` it is handed.
- Logging is `print()`: header line, indented detail, `Done. …`, `!!` for problems.

## Things that bite

- **Store fields are free text** ("1108", "Tyler", "Signal/11103"). Matching is
  five-digit number in the text, then the submitting store account. Don't add
  fuzzy matching — a wrong guess credits the wrong store.
- **Shift is a checkbox**, so a record can say AM and PM. It never counts twice.
- **Closings are filed after midnight** — always grade by the record's Date field.
- **One checklist app down ≠ a row of misses.** Its column shows n/a with a banner
  and Mason gets an alert. Only the Store Directory failing stops the run.
- **Cleaning column is Monday-only** (keyed off a Sunday business date).
- **The recipient list is not written down** — it is rebuilt from the Store
  Directory every run (DMs to, directors cc). Editing `CHECKLIST_RECIPIENTS`
  changes only the fallback. To change who gets it, change the directory, or
  check what it will do with `modal run modal_app.py::show_config`.
- **The domain allowlist is the last guard before a real send.** Don't loosen it
  to make one odd address work; fix the address in the directory instead.
- **Opening compliance is genuinely low** (~36% of store-days in Sept 2026);
  that is the data, not a bug.
- **`checklist_completion.completed` is nullable** — NULL means the app was
  unreadable, not that the store missed it. Query misses with `completed IS
  FALSE`. The upsert's COALESCE stops a NULL erasing a recorded yes; don't
  "simplify" it away.
- **The database write must never fail the send.** `src/history.py` swallows
  everything and prints; keep it that way.
- **This repo owns `checklist_*` only.** `stores` belongs to the punch report,
  and `store_number` here is a soft key — no foreign key, so a store that is in
  the Kintone directory but not in `stores` cannot fail the morning write.
- After any code change: `./.venv/bin/modal deploy modal_app.py`, then
  `./.venv/bin/modal run modal_app.py::test_dry_run`.

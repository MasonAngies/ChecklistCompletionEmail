"""Which store completed which checklist. Every business rule lives here.

The report grades one Arizona business date (yesterday, when run at 7:30 AM):

    Opening        at least one record in app 841 OR app 842 (two versions of
                   the same checklist; a store needs only one)
    Q&FS AM / PM   Quality & Food Safety, app 807, once per shift
    Rush AM / PM   Rush Readiness, app 814, once per shift
    Closing        app 810

and, on the Monday email only, the Weekly Cleaning checklist (app 846) for the
Monday-Sunday week that just ended: the share of its photo fields with at least
one picture, passing at 75%.

The store list, district and DM come from the Kintone Store Directory (app 897),
Active stores only — the same source the punch report groups by.

Things that bite (all measured on real data, 2026-09-28):

  * The store is FREE TEXT on every checklist ("11205", "Signal/11103",
    "Prime 11205", "11202 copper", "1108", a person's name). A store is matched
    when its five-digit number appears in the text. Failing that, the Kintone
    login that submitted it: stores submit from a store account named like
    "11108 - Gilbert & Queen Creek", which rescues "1108" and "Tyler". Anything
    still unmatched is not guessed at — it is listed at the bottom of the email
    so the DM can see a checklist was done but filed badly.
  * The shift is a checkbox, not a radio, so a record can carry AM, PM, both
    or neither. One value is taken as given; both or neither fall back to the
    submission time (before noon Arizona = AM). A single record never counts
    for both shifts.
  * The business date is the record's own Date field, not its created time:
    closings are regularly submitted after midnight against the prior day.
    Q&FS has no Date field; its Date_and_time is used instead.
  * Weekly cleaning is ONE record per store per week, created early in the week
    and edited as photos are added. A few stores split a week across two
    records, so the week is scored on the union of photo fields filled across
    all of that store's records created in the week.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.kintone_client import KintoneClient, KintoneApiError, field, text

AZ_OFFSET = timedelta(hours=-7)  # Arizona, no DST

CLEANING_PASS = 0.75
_NOON = 12

# Store Directory (app 897).
_F_DIR_NUMBER = "Store_Number"
_F_DIR_NAME = "Store_Name"
_F_DIR_DISTRICT = "District"
_F_DIR_DM = "District_Manager_Name"
_F_DIR_STATUS = "Active_Status"                   # Active/Opening/Closed/Inactive

# Shared by every checklist app.
_F_CREATED = "Created_datetime"
_F_CREATOR = "Created_by"
_F_RECORD = "Record_number"

# Opening (841, 842), Rush (814), Closing (810): "Store Name/Number:" + "Date".
_F_STORE = "Text"                                 # Store Name/Number:
_F_DATE = "Date"                                  # Date
# Q&FS (807).
_F_QFS_STORE = "Text_2"                           # Store Number
_F_QFS_WHEN = "Date_and_time"                     # Date and time
_F_QFS_SHIFT = "Check_box_1"                      # Shift: AM / PM
# Rush Readiness (814).
_F_RUSH_SHIFT = "Check_box_19"                    # Shift: AM / PM
# Weekly Cleaning (846): "Store Number:"; its photo fields are read off the form.
_F_CLEAN_STORE = "Text"                           # Store Number:


@dataclass(frozen=True)
class Source:
    """One Kintone app this report reads."""
    key: str          # env var stem: KINTONE_<key>_APP_ID / _API_TOKEN
    label: str        # how the app is named in the email's footnotes
    store_code: str
    date_code: str    # a DATE field, or a DATETIME for Q&FS
    shift_code: str = ""

    @property
    def app_id(self) -> str:
        return os.environ.get(f"KINTONE_{self.key}_APP_ID", "")

    @property
    def token(self) -> str:
        return os.environ.get(f"KINTONE_{self.key}_API_TOKEN", "")


OPENING_A = Source("OPENING_A", "Opening (841)", _F_STORE, _F_DATE)
OPENING_B = Source("OPENING_B", "Opening (842)", _F_STORE, _F_DATE)
QFS = Source("QFS", "Quality & Food Safety", _F_QFS_STORE, _F_QFS_WHEN, _F_QFS_SHIFT)
RUSH = Source("RUSH", "Rush Readiness", _F_STORE, _F_DATE, _F_RUSH_SHIFT)
CLOSING = Source("CLOSING", "Closing", _F_STORE, _F_DATE)
CLEANING = Source("CLEANING", "Weekly Cleaning", _F_CLEAN_STORE, "")
STOREDIR = Source("STOREDIR", "Store Directory", _F_DIR_NUMBER, "")

DAILY_SOURCES = (OPENING_A, OPENING_B, QFS, RUSH, CLOSING)

# The email's columns, in order: (key, header, sources that satisfy it, shift).
COLUMNS: Tuple[Tuple[str, str, Tuple[Source, ...], str], ...] = (
    ("opening", "Opening", (OPENING_A, OPENING_B), ""),
    ("qfs_am", "Q&FS AM", (QFS,), "AM"),
    ("qfs_pm", "Q&FS PM", (QFS,), "PM"),
    ("rush_am", "Rush AM", (RUSH,), "AM"),
    ("rush_pm", "Rush PM", (RUSH,), "PM"),
    ("closing", "Closing", (CLOSING,), ""),
)


@dataclass
class Store:
    number: str
    name: str
    district: str
    dm: str


@dataclass
class Unmatched:
    """A submission that could not be tied to an active store."""
    source: str
    raw_store: str
    who: str
    when: str


@dataclass
class Report:
    business_date: date
    stores: List[Store]
    # (store number, column key) -> True/False; a column whose source could
    # not be read is absent from `columns_ok` and every cell in it is None.
    done: Dict[Tuple[str, str], Optional[bool]]
    columns_ok: Dict[str, bool]
    unmatched: List[Unmatched]
    failures: List[str]
    cleaning_week: Optional[Tuple[date, date]] = None
    cleaning: Dict[str, float] = dc_field(default_factory=dict)  # store -> 0..1
    cleaning_ok: bool = True


# --- time helpers --------------------------------------------------------------

def az_today() -> date:
    return (datetime.now(timezone.utc) + AZ_OFFSET).date()


def _utc_iso(d: date) -> str:
    """Midnight Arizona on `d`, as the UTC timestamp Kintone queries expect."""
    start = datetime.combine(d, time.min) - AZ_OFFSET
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_az(stamp: str) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        utc = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return utc + AZ_OFFSET


def cleaning_week_for(business_date: date) -> Optional[Tuple[date, date]]:
    """The Mon-Sun cleaning week to grade, or None when this email skips it.

    Only the Monday email carries the column, and it grades the week that
    ended the day before — so it is keyed off a Sunday business date.
    """
    if business_date.weekday() != 6:
        return None
    return business_date - timedelta(days=6), business_date


# --- store matching ------------------------------------------------------------

_FIVE_DIGITS = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def match_store(raw: str, known: Dict[str, Store]) -> Optional[str]:
    """The active store whose five-digit number appears in `raw`, else None."""
    for number in _FIVE_DIGITS.findall(raw or ""):
        if number in known:
            return number
    return None


def record_store(src: "Source", rec: dict, known: Dict[str, Store]) -> Optional[str]:
    """The typed store field first, then the submitting store account."""
    return (match_store(text(rec, src.store_code), known)
            or match_store(_creator(rec), known))


def _creator(record: dict) -> str:
    who = field(record, _F_CREATOR) or {}
    return (who.get("name") or who.get("code") or "").strip() if isinstance(who, dict) else ""


# --- reading Kintone -----------------------------------------------------------

def load_stores(client: KintoneClient) -> List[Store]:
    """Active stores from the Store Directory, sorted by district then number.

    This is the one read the report cannot do without, so it raises rather than
    guessing at a store list.
    """
    if not STOREDIR.app_id or not STOREDIR.token:
        raise KintoneApiError("KINTONE_STOREDIR_APP_ID / _API_TOKEN not set.")
    stores = []
    for rec in client.records(STOREDIR.app_id, STOREDIR.token, order_by="$id asc"):
        if text(rec, _F_DIR_STATUS) != "Active":
            continue
        number = text(rec, _F_DIR_NUMBER)
        if not number:
            continue
        stores.append(Store(
            number=number,
            name=text(rec, _F_DIR_NAME),
            district=text(rec, _F_DIR_DISTRICT) or "Other",
            dm=text(rec, _F_DIR_DM),
        ))
    if not stores:
        raise KintoneApiError("Store Directory returned no Active stores.")
    stores.sort(key=lambda s: (s.district == "Other", s.district, s.number))
    return stores


def _business_date(src: Source, rec: dict) -> Optional[date]:
    raw = text(rec, src.date_code)
    if raw:
        if src is QFS:
            az = _to_az(raw)
            if az:
                return az.date()
        else:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
    created = _to_az(text(rec, _F_CREATED))
    return created.date() if created else None


def _shift(src: Source, rec: dict) -> str:
    ticked = set(field(rec, src.shift_code) or []) & {"AM", "PM"}
    if len(ticked) == 1:
        return ticked.pop()
    created = _to_az(text(rec, _F_CREATED))
    return "AM" if created and created.hour < _NOON else "PM"


def _fetch_day(client: KintoneClient, src: Source, business_date: date) -> List[dict]:
    """Records that could belong to `business_date`.

    Pulled by created time with a day of slack either side (a closing lands
    after midnight; a store occasionally back-fills yesterday's opening), then
    narrowed to the business date by `_business_date`.
    """
    if not src.app_id or not src.token:
        raise KintoneApiError(f"KINTONE_{src.key}_APP_ID / _API_TOKEN not set.")
    lo = _utc_iso(business_date - timedelta(days=1))
    hi = _utc_iso(business_date + timedelta(days=2))
    where = f'{_F_CREATED} >= "{lo}" and {_F_CREATED} < "{hi}"'
    return [r for r in client.records(src.app_id, src.token, where=where)
            if _business_date(src, r) == business_date]


def _photo_fields(client: KintoneClient) -> List[str]:
    """Every FILE field on the cleaning form, read live so a new task counts."""
    props = client.form_fields(CLEANING.app_id, CLEANING.token)
    return [code for code, p in props.items() if p.get("type") == "FILE"]


def load_cleaning(client: KintoneClient, week: Tuple[date, date],
                  known: Dict[str, Store]) -> Tuple[Dict[str, float], List[Unmatched]]:
    """Share of photo fields filled per store for the week (Mon..Sun inclusive)."""
    if not CLEANING.app_id or not CLEANING.token:
        raise KintoneApiError("KINTONE_CLEANING_APP_ID / _API_TOKEN not set.")
    photos = _photo_fields(client)
    if not photos:
        raise KintoneApiError("Weekly Cleaning form has no photo fields.")
    lo, hi = _utc_iso(week[0]), _utc_iso(week[1] + timedelta(days=1))
    where = f'{_F_CREATED} >= "{lo}" and {_F_CREATED} < "{hi}"'

    filled: Dict[str, set] = {}
    unmatched: List[Unmatched] = []
    for rec in client.records(CLEANING.app_id, CLEANING.token, where=where):
        have = {code for code in photos if field(rec, code)}
        number = record_store(CLEANING, rec, known)
        if number is None:
            # An empty draft with no store and no photos is noise, not a filing error.
            if have or text(rec, CLEANING.store_code):
                unmatched.append(_unmatched(CLEANING, rec))
            continue
        filled.setdefault(number, set()).update(have)
    return {n: len(codes) / len(photos) for n, codes in filled.items()}, unmatched


def _unmatched(src: Source, rec: dict) -> Unmatched:
    created = _to_az(text(rec, _F_CREATED))
    return Unmatched(
        source=src.label,
        raw_store=text(rec, src.store_code),
        who=_creator(rec),
        when=created.strftime("%a %-I:%M %p") if created else "",
    )


def build_report(business_date: date, client: Optional[KintoneClient] = None) -> Report:
    """Read every app and grade every active store for `business_date`.

    One checklist app failing does not stop the report: its column prints as
    "n/a" with a banner, rather than as a row of misses that DMs would chase.
    The failure is returned so the caller can alert on it.
    """
    client = client or KintoneClient()
    stores = load_stores(client)
    known = {s.number: s for s in stores}

    failures: List[str] = []
    unmatched: List[Unmatched] = []
    # (source key, store, shift) seen on the business date.
    seen: set = set()
    read_ok: Dict[str, bool] = {}

    for src in DAILY_SOURCES:
        try:
            records = _fetch_day(client, src, business_date)
        except Exception as exc:  # noqa: BLE001 - reported, then the column is n/a
            failures.append(f"{src.label}: {type(exc).__name__}: {exc}")
            read_ok[src.key] = False
            print(f"  !! {src.label}: {exc}")
            continue
        read_ok[src.key] = True
        matched = 0
        for rec in records:
            number = record_store(src, rec, known)
            if number is None:
                unmatched.append(_unmatched(src, rec))
                continue
            matched += 1
            seen.add((src.key, number, _shift(src, rec) if src.shift_code else ""))
        print(f"  {src.label:<22} {len(records):>4} records, {matched} matched to a store")

    done: Dict[Tuple[str, str], Optional[bool]] = {}
    columns_ok: Dict[str, bool] = {}
    for key, _header, sources, shift in COLUMNS:
        # Opening counts either app, so it stays gradeable if just one is down.
        ok_sources = [s for s in sources if read_ok.get(s.key)]
        ok = bool(ok_sources) if key == "opening" else len(ok_sources) == len(sources)
        columns_ok[key] = ok
        for store in stores:
            if not ok:
                done[(store.number, key)] = None
                continue
            done[(store.number, key)] = any(
                (s.key, store.number, shift) in seen for s in ok_sources
            )

    report = Report(business_date, stores, done, columns_ok, unmatched, failures)

    week = cleaning_week_for(business_date)
    if week:
        report.cleaning_week = week
        try:
            report.cleaning, clean_unmatched = load_cleaning(client, week, known)
            report.unmatched.extend(clean_unmatched)
            print(f"  {CLEANING.label:<22} week {week[0]}..{week[1]}, "
                  f"{len(report.cleaning)} stores submitted")
        except Exception as exc:  # noqa: BLE001
            report.cleaning_ok = False
            failures.append(f"{CLEANING.label}: {type(exc).__name__}: {exc}")
            print(f"  !! {CLEANING.label}: {exc}")
    return report


def store_score(report: Report, number: str) -> Tuple[int, int]:
    """(completed, gradeable) daily checklists for one store."""
    cells = [report.done[(number, key)] for key, *_ in COLUMNS]
    graded = [c for c in cells if c is not None]
    return sum(graded), len(graded)

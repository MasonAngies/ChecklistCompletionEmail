"""Read-only Kintone REST client for the checklist completion report.

A copy of the DC pick sheets client (DC-Orders-Picking/src/kintone_client.py),
kept here rather than imported so a fix or a rotated key in one tool can never
break another. Read-only on purpose: this report must not be able to mutate a
store's checklist. Every request retries, because it runs unattended at 7:30.

Kintone auth is a per-app API token in the `X-Cybozu-API-Token` header. The app
ids and tokens this tool reads are listed in .env.example.

Required environment variables:
    KINTONE_SUBDOMAIN   e.g. "angieslobster" or "angieslobster.kintone.com"
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

_TIMEOUT = 60
# Kintone caps records.json at 500 per request; page with offset beyond that.
_PAGE_SIZE = 500
# Spec: three attempts with exponential backoff before a run is considered failed.
_ATTEMPTS = 3
_BACKOFF = 2.0


class KintoneApiError(RuntimeError):
    """Raised on request failures, with a readable message."""


def _host() -> str:
    """Normalize KINTONE_SUBDOMAIN into a bare host.

    The env var may hold either a bare subdomain ("angieslobster") or the full
    host ("angieslobster.kintone.com"); accept both so a trailing ".kintone.com"
    is never doubled.
    """
    raw = os.environ.get("KINTONE_SUBDOMAIN", "").strip().rstrip("/")
    if not raw:
        raise KintoneApiError(
            "Missing required environment variable 'KINTONE_SUBDOMAIN'. Check your .env file."
        )
    host = raw.replace("https://", "").replace("http://", "")
    return host if "." in host else f"{host}.kintone.com"


def _retryable(status: int) -> bool:
    """Worth a second attempt: rate limits and anything server-side.

    A 400/401/403 means the query or the token is wrong and will be exactly as
    wrong three seconds later, so those surface immediately instead of turning a
    typo into a 12-second stall.
    """
    return status == 429 or status >= 500


class KintoneClient:
    """Lightweight read-only Kintone REST client."""

    def __init__(self) -> None:
        self.host = _host()
        self._base = f"https://{self.host}/k/v1"

    def _get(self, path: str, token: str, params: dict) -> dict:
        last = ""
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                resp = requests.get(
                    self._base + path,
                    headers={"X-Cybozu-API-Token": token},
                    params=params,
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as exc:
                # Connection reset, DNS blip, read timeout: all worth retrying.
                last = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if not _retryable(resp.status_code):
                    break
            if attempt < _ATTEMPTS:
                delay = _BACKOFF ** attempt
                print(f"  WARNING: GET {path} attempt {attempt} failed ({last}); "
                      f"retrying in {delay:.0f}s")
                time.sleep(delay)
        raise KintoneApiError(f"GET {path} failed after {_ATTEMPTS} attempt(s). {last}")

    def form_fields(self, app_id: str, token: str) -> dict:
        """Field definitions for an app (used by scripts/discover_fields.py)."""
        return self._get("/app/form/fields.json", token, {"app": app_id})["properties"]

    def records(
        self,
        app_id: str,
        token: str,
        where: Optional[str] = None,
        order_by: str = "$id asc",
    ) -> Iterator[dict]:
        """Yield every record matching `where`, paging past Kintone's 500-record cap.

        `where` is a Kintone query WITHOUT limit/offset (those are added here), e.g.
        'Created_datetime >= "2026-09-27T07:00:00Z"'. Paging uses offset, so the order clause
        must be stable — hence the $id default.
        """
        offset = 0
        while True:
            clause = f"{where} " if where else ""
            query = f"{clause}order by {order_by} limit {_PAGE_SIZE} offset {offset}"
            batch = self._get(
                "/records.json", token, {"app": app_id, "query": query}
            ).get("records", [])
            if not batch:
                return
            for record in batch:
                yield record
            if len(batch) < _PAGE_SIZE:
                return
            offset += _PAGE_SIZE


def field(record: dict, code: str):
    """Read a field's raw value out of a Kintone record ({'value': ...} wrappers)."""
    cell = record.get(code)
    return None if cell is None else cell.get("value")


def text(record: dict, code: str) -> str:
    """Read a text field as a stripped string; None and absent both become ''."""
    raw = field(record, code)
    return "" if raw is None else str(raw).strip()


def number(record: dict, code: str, default: Optional[float] = None) -> Optional[float]:
    """Read a numeric field, tolerating Kintone's empty-string-for-blank convention."""
    raw = field(record, code)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default

"""Microsoft Graph email sender for the checklist completion report.

A copy of the house mailer (Angies/src/graph_mailer.py) with one addition:
inline images, so the brand logo travels inside the email as a `cid:` part
instead of a hosted URL that Outlook would block by default. A copy rather than
an import because this tool lives in its own repo and its own Modal image.

Required environment variables (loaded from .env):
    GRAPH_TENANT_ID
    GRAPH_CLIENT_ID
    GRAPH_CLIENT_SECRET
    GRAPH_SENDER_ADDRESS   e.g. noreply-reports@angies.com
"""

from __future__ import annotations

import base64
import os
from typing import Iterable, Optional, Sequence, Tuple, Union

import requests
from dotenv import load_dotenv

load_dotenv()

_LOGIN_HOST = "https://login.microsoftonline.com"
_GRAPH_HOST = "https://graph.microsoft.com/v1.0"
_TOKEN_TIMEOUT = 30
_SEND_TIMEOUT = 120


class GraphEmailError(RuntimeError):
    """Raised when token acquisition or sending fails, with a readable message."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise GraphEmailError(
            f"Missing required environment variable '{name}'. Check your .env file."
        )
    return value


def _get_access_token() -> str:
    """Fetch an app-only bearer token via the OAuth2 client-credentials flow."""
    tenant_id = _require_env("GRAPH_TENANT_ID")
    client_id = _require_env("GRAPH_CLIENT_ID")
    client_secret = _require_env("GRAPH_CLIENT_SECRET")

    url = f"{_LOGIN_HOST}/{tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    resp = requests.post(url, data=data, timeout=_TOKEN_TIMEOUT)
    if resp.status_code != 200:
        detail = _safe_json(resp)
        code = detail.get("error", "unknown_error")
        desc = detail.get("error_description", resp.text)
        raise GraphEmailError(
            f"Failed to get access token (HTTP {resp.status_code}, {code}). Details: {desc}"
        )
    token = resp.json().get("access_token")
    if not token:
        raise GraphEmailError("Token endpoint returned no access_token.")
    return token


def _as_recipient_list(addresses: Union[str, Iterable[str]]) -> list:
    if isinstance(addresses, str):
        addresses = [addresses]
    return [{"emailAddress": {"address": a}} for a in addresses if a]


def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


def parse_recipients(*env_names: str) -> list:
    """First non-empty env var wins, split on comma or semicolon.

    Recipient lists live in the secret so changing who gets the report is never
    a code change.
    """
    for name in env_names:
        raw = os.environ.get(name) or ""
        found = [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]
        if found:
            return found
    return []


def send_email(
    subject: str,
    html_body: str,
    to: Union[str, Iterable[str]],
    cc: Optional[Union[str, Iterable[str]]] = None,
    sender: Optional[str] = None,
    inline_images: Optional[Sequence[Tuple[str, bytes]]] = None,
) -> None:
    """Send an HTML email through Microsoft Graph.

    Args:
        subject: Email subject line.
        html_body: HTML content for the email body.
        to: A single address or an iterable of addresses.
        cc: Optional single address or iterable of CC addresses.
        sender: Override the From mailbox. Defaults to GRAPH_SENDER_ADDRESS.
        inline_images: (content_id, png_bytes) pairs, referenced from the body
            as <img src="cid:content_id">.

    Raises:
        GraphEmailError: if authentication or sending fails.
    """
    sender = sender or _require_env("GRAPH_SENDER_ADDRESS")

    to_recipients = _as_recipient_list(to)
    if not to_recipients:
        raise GraphEmailError("No 'to' recipient provided.")

    message: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": to_recipients,
    }
    if cc:
        message["ccRecipients"] = _as_recipient_list(cc)
    if inline_images:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": f"{cid}.png",
                "contentType": "image/png",
                "contentId": cid,
                "isInline": True,
                "contentBytes": base64.b64encode(blob).decode("ascii"),
            }
            for cid, blob in inline_images
        ]

    token = _get_access_token()
    payload = {"message": message, "saveToSentItems": True}
    url = f"{_GRAPH_HOST}/users/{sender}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = requests.post(url, headers=headers, json=payload, timeout=_SEND_TIMEOUT)

    # A successful sendMail returns 202 Accepted with an empty body.
    if resp.status_code == 202:
        return

    detail = _safe_json(resp).get("error", {})
    code = detail.get("code", "unknown")
    msg = detail.get("message", resp.text)
    raise GraphEmailError(
        f"sendMail failed (HTTP {resp.status_code}, {code}) from sender "
        f"'{sender}'. Details: {msg}"
    )

"""Email the operator when a demo request arrives. Optional: with nothing configured, requests are only stored.

Two ways to send, chosen by what is set:
  RESEND_API_KEY (+ LEAD_FROM_EMAIL)       an HTTPS email API. Works on hosts that block SMTP ports.
  SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD  any SMTP server (port 587 STARTTLS, or 465 SSL).
LEAD_NOTIFY_EMAIL is where requests are sent; nothing is sent without it."""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any, Dict, Optional

_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def recipient() -> Optional[str]:
    to = os.getenv("LEAD_NOTIFY_EMAIL", "").strip()
    return to if re.fullmatch(r"[^@\s,;<>]{1,64}@[^@\s,;<>]{1,255}\.[A-Za-z]{2,}", to) else None


def configured() -> bool:
    return bool(recipient()) and bool(os.getenv("RESEND_API_KEY") or (os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD")))


def _clean(s: str, n: int) -> str:
    """One line, no control characters: visitor text goes into a header, so a newline must not survive."""
    return _CTRL.sub(" ", s or "").strip()[:n]


def compose(lead: Dict[str, Any]) -> Dict[str, str]:
    name, company = _clean(lead["name"], 80), _clean(lead.get("company", ""), 80)
    body = (
        f"New demo request from the NeuraFlow site.\n\nName: {name}\nEmail: {lead['email']}\nCompany: {company or '(none)'}\n\n"
        f"Message:\n{(lead.get('message') or '(none)').strip()}\n\nReply to this email to answer them. Manage requests on /platform."
    )
    return {"subject": f"NeuraFlow demo request: {name}" + (f" ({company})" if company else ""), "body": body, "reply_to": lead["email"].strip()}


def _send_resend(to: str, m: Dict[str, str]) -> None:
    frm = os.getenv("LEAD_FROM_EMAIL", "NeuraFlow <onboarding@resend.dev>")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": frm, "to": [to], "subject": m["subject"], "text": m["body"], "reply_to": m["reply_to"]}).encode(),
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # raises on a non-2xx status
        r.read()


def _send_smtp(to: str, m: Dict[str, str]) -> None:
    user = os.environ["SMTP_USERNAME"]
    msg = EmailMessage()
    msg["From"] = os.getenv("LEAD_FROM_EMAIL") or formataddr(("NeuraFlow", parseaddr(user)[1] or user))
    msg["To"], msg["Subject"], msg["Reply-To"] = to, m["subject"], m["reply_to"]
    msg.set_content(m["body"])
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as s:
            s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)


def send_lead(lead: Dict[str, Any]) -> bool:
    """True if an email went out. Never raises: a failed email must not lose or block the request."""
    to = recipient()
    if not to or not configured():
        return False
    try:
        m = compose(lead)
        (_send_resend if os.getenv("RESEND_API_KEY") else _send_smtp)(to, m)
        return True
    except Exception:  # noqa: BLE001
        return False

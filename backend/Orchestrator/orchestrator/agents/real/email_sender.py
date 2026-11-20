"""Email channel sender (Brevo) -- same sender contract as TwilioWhatsAppSender
in sender.py: sender.send(channel, handle, message, account_id=None,
idempotency_key=None) -> {"disposition": ..., "duration": ...}.

Adapted from the standalone emailbot.py prototype. Two things from that
prototype are deliberately NOT carried over, because the agents calling this
sender already do them:
- Its own idempotency/dedupe tracking -- reminder_agent/negotiation_agent
  already do SENT-then-FINAL idempotency in contact_log before send() is
  ever called, so a second dedupe layer here would just mask real resends.
- Its own SCRIPTS template text -- the agents already pick the outbound
  message from their own templates.json (template-only drafting rule); this
  sender just delivers whatever `message` it's given, like every other
  channel sender in this project.

What IS carried over: the allowlist/override safety guard, so this can't
email a real dataset address by accident while testing.
"""
import os
import re

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILENAME_FALLBACKS = [".env", "_.env", ".env.local", "env", "env.example"]


def _clean_value(v):
    v = v.split("#", 1)[0].strip()
    if v.startswith("export "):
        v = v[len("export "):].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return v.strip()


def _load_env():
    for name in ENV_FILENAME_FALLBACKS:
        path = os.path.join(SCRIPT_DIR, name)
        if not os.path.exists(path):
            continue
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            v = _clean_value(v)
            if os.environ.get(k, "") == "":
                os.environ[k] = v
        return path
    return None


_load_env()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
DEMO_OVERRIDE_EMAIL = os.getenv("DEMO_OVERRIDE_EMAIL")
ALLOWED_EMAILS = [a.strip() for a in os.getenv("ALLOWED_EMAILS", "").split(",") if a.strip()]


class EmailConfigError(Exception):
    """Raised by send() when BREVO_API_KEY/EMAIL_FROM aren't configured --
    caught by the calling agent the same way any other sender exception is
    (FAILED, error_code sender_error)."""


class EmailBlocked(Exception):
    """Raised when the recipient isn't in ALLOWED_EMAILS and no
    DEMO_OVERRIDE_EMAIL is set -- a deliberate safety guard against emailing
    a real dataset address while testing, distinct from a config/API error."""


def mask_handle(value):
    if not value:
        return value
    value = str(value).strip()
    local, _, domain = value.partition("@")
    if not domain:
        return value
    masked_local = local[0] + "*" * (len(local) - 1) if len(local) > 1 else local
    return f"{masked_local}@{domain}"


class BrevoEmailSender:
    def __init__(self, api_key=None, from_email=None, allowed_emails=None,
                 override_email=None, session=None, timeout=10):
        self.api_key = api_key or BREVO_API_KEY
        self.from_email = from_email or EMAIL_FROM
        self.allowed_emails = allowed_emails if allowed_emails is not None else ALLOWED_EMAILS
        self.override_email = override_email if override_email is not None else DEMO_OVERRIDE_EMAIL
        self.session = session or requests
        self.timeout = timeout

    def send(self, channel, handle, message, account_id=None, idempotency_key=None):
        if channel != "email":
            return {"disposition": "failed", "duration": 0}

        to = self.override_email or (handle if handle in self.allowed_emails else None)
        if not to:
            raise EmailBlocked(
                f"recipient not in allowlist / no DEMO_OVERRIDE_EMAIL set "
                f"(demo_override_set={bool(self.override_email)})"
            )

        if not (self.api_key and self.from_email):
            raise EmailConfigError("BREVO_API_KEY / EMAIL_FROM not configured")

        subject = "Regarding your loan account"
        resp = self.session.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"},
            json={"sender": {"email": self.from_email}, "to": [{"email": to}],
                  "subject": subject, "textContent": message},
            timeout=self.timeout,
        )
        resp.raise_for_status()  # non-2xx -> requests.HTTPError, propagates as a sender failure
        return {"disposition": "sent", "duration": 0}

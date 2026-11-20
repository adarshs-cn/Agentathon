"""
Voicebot layer for the MT-02 supervisor  --  Level 1 (one-way outbound call).

Supervisor calls:   handle_call(agent, payload)
  agent    : "reminder" | "negotiation"
  payload  : dict, see EXAMPLE_PAYLOAD at the bottom

What happens:
  1. Safety guard   - only dials approved / override numbers (never synthetic ones)
  2. Idempotency    - same borrower+agent+intent+date is never called twice
  3. Script         - Sarvam conversational LLM, with fixed template fallback
  4. Call           - Twilio REST API with inline TwiML (no server / public URL needed)
  5. Trace          - every step appended to a JSONL file with its reason

Config comes from environment variables only (see .env.example). No secrets in code.
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import requests


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no extra dependency). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parent / ".env")
_load_dotenv(Path.cwd() / ".env")

# --------------------------------------------------------------------------- config
SARVAM_URL = os.getenv("SARVAM_URL", "https://api.sarvam.ai/v2/chat/completions")
SARVAM_MODEL = os.getenv("SARVAM_CONV_MODEL", "sarvam-105b-conversations")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "8"))

TRACE_FILE = Path(os.getenv("VOICEBOT_TRACE", "voicebot_trace.jsonl"))

# Twilio voices are configurable: Polly.Aditi speaks both en-IN and hi-IN.
VOICE = os.getenv("TWILIO_VOICE", "Polly.Aditi")
LANG_CODES = {"en": "en-IN", "hi": "hi-IN"}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


# --------------------------------------------------------------------------- trace
def _log(event: str, **fields) -> dict:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _already_done(key: str, event: str = "CALL_PLACED") -> bool:
    if not TRACE_FILE.exists():
        return False
    for line in TRACE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Only a really placed contact counts. Dry runs / blocked / failed attempts must not
        # stop the real contact from going out later.
        if r.get("idempotency_key") == key and r.get("event") == event:
            return True
    return False


# --------------------------------------------------------------------------- safety
def _resolve_number(borrower_phone: str):
    """
    Returns (number_to_dial, reason). number is None if the call must be blocked.
    Priority: DEMO_OVERRIDE_NUMBER (team phone) > ALLOWED_NUMBERS allow-list.
    The borrower's own (synthetic) number is only dialled if explicitly allow-listed.
    """
    override = _env("DEMO_OVERRIDE_NUMBER")
    if override:
        return override, "demo override number used instead of borrower number"
    allowed = {n.strip() for n in _env("ALLOWED_NUMBERS").split(",") if n.strip()}
    if borrower_phone in allowed:
        return borrower_phone, "number is on the approved list"
    return None, "blocked: number not on approved list and no demo override set"


# --------------------------------------------------------------------------- scripts
SYSTEM_PROMPT = (
    "You write the spoken script for an automated voice call from a lender's collections "
    "assistant in India. Rules: polite, calm, respectful; never threaten, shame, or mention "
    "legal action; never reveal the debt to anyone but the borrower; speak plain sentences "
    "suitable for text-to-speech (no markdown, no emojis, no lists); at most 60 words; "
    "output ONLY the words to be spoken."
)

TASKS = {
    "reminder": (
        "Remind the borrower that their EMI of Rs {emi_amount} is due on {due_date}. "
        "Ask them to keep at least that balance in their account before the due date so the "
        "payment goes through. Do not mention any past promises or overdue amounts. "
        "Thank them at the end."
    ),
    "negotiation": (
        "The borrower promised to pay Rs {ptp_amount} on {ptp_date} but the payment was not "
        "received. Politely mention this, then ask for the earliest date they can pay. "
        "Offer to note the new date. Stay supportive, not accusatory."
    ),
}

FALLBACK = {
    ("reminder", "en"): (
        "Hello {name}. This is a friendly reminder that your EMI of rupees {emi_amount} is due "
        "on {due_date}. Please keep this balance in your account before the due date so your "
        "payment goes through smoothly. Thank you."
    ),
    ("reminder", "hi"): (
        "नमस्ते {name}। यह एक सूचना है कि आपकी {emi_amount} रुपये की ईएमआई {due_date} को देय है। "
        "कृपया देय तिथि से पहले अपने खाते में इतनी राशि बनाए रखें। धन्यवाद।"
    ),
    ("negotiation", "en"): (
        "Hello {name}. You had promised to pay rupees {ptp_amount} on {ptp_date}, but we have "
        "not received the payment. Could you please share the earliest date by which you can "
        "make it? We will note it down. Thank you for your help."
    ),
    ("negotiation", "hi"): (
        "नमस्ते {name}। आपने {ptp_date} को {ptp_amount} रुपये का भुगतान करने का वादा किया था, "
        "लेकिन हमें भुगतान प्राप्त नहीं हुआ है। कृपया बताइए कि आप जल्द से जल्द किस तारीख तक "
        "भुगतान कर सकते हैं। धन्यवाद।"
    ),
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _fallback_script(agent: str, payload: dict) -> str:
    lang = payload.get("language", "en")
    tpl = FALLBACK.get((agent, lang)) or FALLBACK[(agent, "en")]
    return tpl.format(**{k: payload.get(k, "") for k in
                         ("name", "emi_amount", "due_date", "ptp_amount", "ptp_date")})


def _generate_live(agent: str, payload: dict):
    """Live per-call LLM generation (slow). Only used when LIVE_LLM=1."""
    key = _env("SARVAM_API_KEY")
    if not key:
        return _fallback_script(agent, payload), "fallback:no_api_key"

    lang_name = "Hindi" if payload.get("language") == "hi" else "English (Indian)"
    task = TASKS[agent].format(**{k: payload.get(k, "") for k in
                                  ("emi_amount", "due_date", "ptp_amount", "ptp_date")})
    user_msg = (
        f"Borrower name: {payload.get('name', '')}\nLanguage: {lang_name}\nTask: {task}"
    )
    try:
        r = requests.post(
            SARVAM_URL,
            headers={"api-subscription-key": key, "Content-Type": "application/json",
                 "User-Agent": "agentathon-voicebot/1.0"},
            json={
                "model": SARVAM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.4,
                "max_tokens": 300,
            },
            timeout=LLM_TIMEOUT,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        text = _THINK_RE.sub("", text).strip().strip('"')
        if not text or len(text.split()) > 120:
            raise ValueError("empty or overlong script")
        return text, "sarvam"
    except Exception as e:  # any failure -> deterministic template, call still happens
        _log("SCRIPT_FALLBACK", agent=agent, error=f"{type(e).__name__}: {e}"[:300])
        return _fallback_script(agent, payload), "fallback:llm_error"


# ---- pre-generated script templates (fast path: no LLM call during a call) ----------
CACHE_FILE = Path(os.getenv("SCRIPT_CACHE", str(Path(__file__).resolve().parent / "scripts_cache.json")))
FIELDS = {
    "reminder": ["name", "emi_amount", "due_date"],
    "negotiation": ["name", "ptp_amount", "ptp_date"],
}


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fill(template: str, agent: str, payload: dict) -> str:
    for f in FIELDS[agent]:
        template = template.replace("{" + f + "}", str(payload.get(f, "")))
    return template


def build_template(agent: str, language: str) -> str:
    """Ask Sarvam ONCE for a script containing literal {placeholders}. Validates the result."""
    key = _env("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY not set")
    fields = FIELDS[agent]
    lang_name = "Hindi" if language == "hi" else "English (Indian)"
    task = TASKS[agent].replace("{emi_amount}", "{emi_amount}")  # placeholders stay literal
    user_msg = (
        f"Language: {lang_name}\nTask: {task}\n"
        f"Write the script using these literal placeholders exactly as written, in curly "
        f"braces: {', '.join('{' + f + '}' for f in fields)}. Use each placeholder at least "
        f"once. Do not use any other curly braces."
    )
    r = requests.post(
        SARVAM_URL,
        headers={"api-subscription-key": key, "Content-Type": "application/json",
                 "User-Agent": "agentathon-voicebot/1.0"},
        json={"model": SARVAM_MODEL,
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": user_msg}],
              "temperature": 0.4, "max_tokens": 300},
        timeout=max(LLM_TIMEOUT, 20),
    )
    r.raise_for_status()
    text = _THINK_RE.sub("", r.json()["choices"][0]["message"]["content"]).strip().strip('"')
    missing = [f for f in fields if "{" + f + "}" not in text]
    stray = set(re.findall(r"\{(\w+)\}", text)) - set(fields)
    if missing or stray or len(text.split()) > 120:
        raise ValueError(f"template rejected (missing={missing}, stray={sorted(stray)})")
    return text


def save_template(agent: str, language: str, text: str) -> None:
    cache = _load_cache()
    cache[f"{agent}:{language}"] = text
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_script(agent: str, payload: dict):
    """
    Returns (script_text, source). Order of preference (all fast except the last):
      1. cached Sarvam template  -> 'cache'
      2. live Sarvam call        -> 'sarvam'   (only if LIVE_LLM=1)
      3. built-in fixed template -> 'fallback'
    """
    lang = payload.get("language", "en")
    tpl = _load_cache().get(f"{agent}:{lang}")
    if tpl:
        return _fill(tpl, agent, payload), "cache"
    if _env("LIVE_LLM") == "1":
        return _generate_live(agent, payload)
    return _fallback_script(agent, payload), "fallback:no_cache"


# --------------------------------------------------------------------------- telephony
def build_twiml(script: str, language: str) -> str:
    lang = LANG_CODES.get(language, "en-IN")
    say = f'<Say voice="{escape(VOICE)}" language="{lang}">{escape(script)}</Say>'
    return f'<Response><Pause length="1"/>{say}<Pause length="1"/><Hangup/></Response>'


PENDING_DIR = Path(__file__).resolve().parent / "twiml_pending"


def _twilio_base() -> str:
    return (_env("TWILIO_API_BASE") or "https://api.twilio.com").rstrip("/")


def place_call(to_number: str, twiml: str, call_key: str = "call") -> dict:
    """
    Two modes:
      * PUBLIC_BASE_URL set  -> URL mode: the TwiML is saved to twiml_pending/<call_key>.xml
                                and Twilio fetches it from our server (works on trial accounts).
      * PUBLIC_BASE_URL empty -> inline mode: TwiML is sent inside the request (paid accounts).
    """
    sid, token, from_ = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"), _env("TWILIO_FROM_NUMBER")
    data = {"To": to_number, "From": from_}
    base = _env("PUBLIC_BASE_URL").rstrip("/")
    if base:
        PENDING_DIR.mkdir(exist_ok=True)
        (PENDING_DIR / f"{call_key}.xml").write_text(twiml, encoding="utf-8")
        # Only To / From / Url are sent: Twilio trial accounts reject extra parameters
        # (Method, inline Twiml, ...). Twilio will POST to this Url; twiml_server.py handles that.
        data["Url"] = f"{base}/twiml/{call_key}.xml"
    else:
        data["Twiml"] = twiml
    r = requests.post(
        f"{_twilio_base()}/2010-04-01/Accounts/{sid}/Calls.json",
        auth=(sid, token),
        data=data,
        timeout=15,
    )
    if not r.ok:  # surface Twilio's own error code + message, not just "400"
        try:
            e = r.json()
            raise RuntimeError(f"Twilio {r.status_code} (code {e.get('code')}): {e.get('message')}")
        except ValueError:
            raise RuntimeError(f"Twilio {r.status_code}: {r.text[:200]}")
    j = r.json()
    return {"call_sid": j.get("sid"), "status": j.get("status")}


def get_call_status(call_sid: str) -> str:
    sid, token = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN")
    r = requests.get(
        f"{_twilio_base()}/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json",
        auth=(sid, token), timeout=10,
    )
    r.raise_for_status()
    return r.json().get("status", "unknown")


def wait_for_final_status(call_sid: str, max_wait: int = 60) -> str:
    """Poll until the call ends (completed / busy / no-answer / failed / canceled)."""
    final = {"completed", "busy", "no-answer", "failed", "canceled"}
    end = time.time() + max_wait
    status = "unknown"
    while time.time() < end:
        status = get_call_status(call_sid)
        if status in final:
            break
        time.sleep(3)
    return status


# --------------------------------------------------------------------------- entry point
def handle_call(agent: str, payload: dict, wait: bool = False, force: bool = False) -> dict:
    """
    Called by the supervisor after it has granted this agent the lease on the borrower.
    Never raises: always returns a result dict the supervisor can log / act on.
    """
    if agent not in TASKS:
        return {"ok": False, "status": "rejected", "reason": f"unknown agent '{agent}'"}

    borrower_id = payload.get("borrower_id", "?")
    intent = "ptp_followup" if agent == "negotiation" else "emi_reminder"
    anchor = payload.get("ptp_date") if agent == "negotiation" else payload.get("due_date")
    idem = hashlib.sha256(f"{borrower_id}|{agent}|{intent}|{anchor}".encode()).hexdigest()[:16]
    base = {"borrower_id": borrower_id, "account_id": payload.get("account_id"),
            "agent": agent, "intent": intent, "idempotency_key": idem}

    # 1. idempotency
    if not force and _already_done(idem):
        _log("CALL_SKIPPED_DUPLICATE", **base, reason="same call already placed")
        return {"ok": True, "status": "skipped_duplicate", "reason": "already called", **base}

    # 2. safety guard
    number, why = _resolve_number(payload.get("phone", ""))
    if number is None:
        _log("CALL_BLOCKED", **base, reason=why)
        return {"ok": False, "status": "blocked", "reason": why, **base}

    # 3. script
    script, source = generate_script(agent, payload)
    _log("SCRIPT_READY", **base, script_source=source, script=script)

    # 4. call (dry-run when Twilio credentials are not configured)
    twiml = build_twiml(script, payload.get("language", "en"))
    have_twilio = all(_env(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    if not have_twilio:
        _log("CALL_DRY_RUN", **base, to=number, reason=why + "; twilio not configured")
        return {"ok": True, "status": "dry_run", "script": script, "script_source": source,
                "twiml": twiml, "reason": why, **base}
    try:
        res = place_call(number, twiml, call_key=f"{idem}_{int(time.time())}")
        _log("CALL_PLACED", **base, to=number, call_sid=res["call_sid"],
             status=res["status"], reason=why)
        out = {"ok": True, "status": res["status"], "call_sid": res["call_sid"],
               "script": script, "script_source": source, "reason": why, **base}
        if wait:
            final = wait_for_final_status(res["call_sid"], max_wait=120)
            _log("CALL_FINAL_STATUS", **base, call_sid=res["call_sid"], status=final)
            out["final_status"] = final
        return out
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
        _log("CALL_FAILED", **base, to=number, error=err)
        return {"ok": False, "status": "failed", "reason": err, "script": script, **base}


# --------------------------------------------------------------------------- sample payloads
EXAMPLE_PAYLOADS = {
    "reminder": {
        "borrower_id": "B1001", "account_id": "A5001", "name": "Ramesh",
        "phone": "+910000000001", "language": "en",
        "due_date": "25 November", "emi_amount": "12,500",
    },
    "negotiation": {
        "borrower_id": "B1002", "account_id": "A5002", "name": "Sunita",
        "phone": "+910000000002", "language": "hi",
        "ptp_date": "15 November", "ptp_amount": "8,000",
    },
}

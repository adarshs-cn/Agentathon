"""The message a channel agent sends, as text.

The stub agents use this so the dashboard can show exactly what a borrower would receive. A real agent
adapter would return its own text in the same shape: {"channel", "to", "subject", "body"}.

Only already-masked or non-personal values are ever placed in a message (see ui/scenario.py for the demo contact).
"""
from __future__ import annotations

import os

from orchestrator.config import load_env

LENDER = "CreditNirvana"
OFFICER = "Grievance Officer, grievance@creditnirvana.example"   # a placeholder footer, not a real address


def inr(v) -> str:
    """Indian digit grouping: 1234567 -> ₹12,34,567."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return "your balance"
    s = str(abs(n))
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("₹" + ",".join(parts + [tail])) if parts else "₹" + tail


# What each D12 action says, in one sentence. {…} come from the message context.
LINES = {
    "emi_due_reminder": "your EMI of {emi} is due soon.",
    "pre_due_reminder": "your EMI of {emi} is due soon.",
    "overdue_reminder": "your payment of {dues} is overdue by {dpd} days.",
    "ptp_capture": "your account is {dpd} days overdue ({dues}). When can you pay? Reply with a date, or call us to agree a plan.",
    "ptp_reminder": "this is a reminder that your promised payment of {amount} is due tomorrow.",
    "broken_ptp_followup": "we did not receive the payment you promised. Let us agree a new date: reply to this message or call us.",
    "settlement_offer": "we can offer you a settlement on your overdue {dues}. Reply to hear the options.",
    "restructure_offer": "we can restructure your loan to make repayments easier. Reply to hear the options.",
    "payment_confirmation": "we have received your payment of {amount}. Thank you.",
    "statement": "your account statement is ready.",
    "service_request": "we have received your request and will get back to you shortly.",
    "legal_notice": "this is a formal notice about your overdue amount of {dues} ({dpd} days). Please contact us within 7 days to avoid further action.",
    "demand_notice": "this is a formal demand for your overdue amount of {dues} ({dpd} days). Please contact us within 7 days.",
}
SUBJECTS = {
    "emi_due_reminder": "Your EMI is due soon", "pre_due_reminder": "Your EMI is due soon",
    "overdue_reminder": "Your payment is overdue", "ptp_capture": "Let us agree a payment date",
    "ptp_reminder": "Your promised payment is due tomorrow", "broken_ptp_followup": "About your missed payment",
    "settlement_offer": "A settlement option for you", "restructure_offer": "A way to ease your repayments",
    "payment_confirmation": "We received your payment", "statement": "Your statement is ready",
    "service_request": "We received your request", "legal_notice": "Formal notice regarding your account",
    "demand_notice": "Formal demand notice",
}
NO_PAY_LINK = {"payment_confirmation", "statement", "service_request", "legal_notice", "demand_notice"}


def demo_contact() -> dict:
    """The contact every demo message is addressed to. Configured outside the code, masked unless told otherwise."""
    load_env()
    phone = os.environ.get("MT02_DEMO_PHONE", "").strip()
    email = os.environ.get("MT02_DEMO_EMAIL", "").strip()
    full = os.environ.get("MT02_SHOW_FULL_PHONE") == "1"
    digits = "".join(ch for ch in phone if ch.isdigit())
    return {
        "name": os.environ.get("MT02_DEMO_NAME", "").strip() or "Customer",
        "phone": phone if (full and phone) else (("X" * 6 + digits[-4:]) if len(digits) >= 4 else "your demo number"),
        "email": email if (full and email) else ((email[0] + "***@" + email.split("@", 1)[1]) if "@" in email else "your demo email"),
        "configured": bool(phone),
    }


def message_context(db, customer_id: str, event: dict, action: str) -> dict:
    """Values a message may use. The amounts and DPD are those of the ACCOUNT the event is about (falling back to the
    customer's worst account only if the event names none). Names and numbers are never read from the personal-data
    columns: only the masked forms and the configured demo contact."""
    acc = (db.one("SELECT * FROM account WHERE account_id=? AND customer_id=?", (event.get("account_id"), customer_id))
           if event.get("account_id") else None) or db.one(
        "SELECT * FROM account WHERE customer_id=? ORDER BY dpd DESC", (customer_id,))
    if acc is None:
        return {}
    demo = demo_contact()
    ctx = {"name": demo["name"], "emi": inr(acc["emi"]), "dues": inr(acc["total_dues"]), "dpd": acc["dpd"],
           "amount": inr(acc["emi"]), "to_phone": demo["phone"], "to_email": demo["email"]}
    if action == "ptp_reminder":
        p = db.one("SELECT amount FROM ds_ptp WHERE account_id=? AND status='open' ORDER BY promised_date LIMIT 1", (acc["account_id"],))
        if p:
            ctx["amount"] = inr(p["amount"])
    elif action == "broken_ptp_followup":
        p = (db.one("SELECT amount, promised_date FROM ds_ptp WHERE account_id=? AND status='broken' "
                     "ORDER BY promised_date DESC LIMIT 1", (acc["account_id"],))
             or db.one("SELECT amount, promised_date FROM ds_ptp WHERE account_id=? AND status='open' "
                        "ORDER BY promised_date DESC LIMIT 1", (acc["account_id"],)))
        if p:
            ctx["amount"] = inr(p["amount"])
            ctx["ptp_date"] = p["promised_date"]
    elif action == "payment_confirmation":
        p = db.one("SELECT amount FROM ds_payment WHERE customer_id=? AND status='success' ORDER BY at DESC LIMIT 1", (customer_id,))
        if p:
            ctx["amount"] = inr(p["amount"])
    return ctx


def render(action: str, channel: str, ctx: dict) -> dict:
    """channel: whatsapp | email | voice. Returns {channel, to, subject, body}."""
    line = LINES.get(action, "we have an update on your account.").format(**{k: ctx.get(k, "") for k in
                                                                              ("emi", "dues", "dpd", "amount")})
    name = ctx.get("name", "Customer")
    link = "" if action in NO_PAY_LINK else " Pay securely: https://pay.example/demo"
    if channel == "whatsapp":
        return {"channel": "whatsapp", "to": ctx.get("to_phone"), "subject": None,
                "body": f"Hi {name}, this is {LENDER}: {line}{link}\nReply STOP to opt out."}
    if channel == "email":
        return {"channel": "email", "to": ctx.get("to_email"), "subject": SUBJECTS.get(action, "An update on your account"),
                "body": f"Dear {name},\n\n{line[0].upper() + line[1:]}{link}\n\nRegards,\n{LENDER}\n{OFFICER}"}
    return {"channel": "voice", "to": ctx.get("to_phone"), "subject": None,
            "body": f"Hello, this is {LENDER} calling for {name}. {line[0].upper() + line[1:]} "
                    f"Press 1 to hear payment options, or press 2 to speak to an agent."}

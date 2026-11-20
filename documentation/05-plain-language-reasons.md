# 05. Plain-language reasons

Rule: **every reason on screen is a short sentence a stranger understands.** The rule code is secondary: small grey text
after the sentence, or in a tooltip. It is never the headline.

The API will return, next to each code, a `label` (the headline below) and `explain` (one sentence). The frontend shows
`label`; `explain` appears in the hover or drawer.

## Event names (replace the technical names)

| Code | Shown as |
|---|---|
| `DUE_SOON` | Reminder due |
| `OVERDUE` | Payment overdue |
| `PTP_DUE` | Promise to pay due tomorrow |
| `PTP_BROKEN` | Promise to pay broken |
| `PAYMENT_RECEIVED` | Payment received |
| `CONTACT_REQUESTED` | Contact requested |
| `SERVICE_REQUEST` | Service request |

## Outcome words

| Code | Shown as |
|---|---|
| CONTACTED | Message sent |
| BLOCKED | Not allowed |
| SUPPRESSED | Nobody could act |
| DEFERRED | Waiting for a better time |
| ESCALATED | Sent to a person |
| REJECTED | Invalid event |

## Agent names

| Code | Shown as |
|---|---|
| `reminder` / `negotiation` / `servicing` / `legal` | Reminder / Negotiation / Servicing / Legal agent |
| `whatsapp` / `email` / `voice` | WhatsApp / Email / Voice call (IVR) |

## Reasons (the catalogue)

### Holds and suppression
| Code | Label | One-line explanation |
|---|---|---|
| R058 | Borrower has passed away | No contact on any channel; the legal-heir desk handles this account. |
| R059 | Borrower asked us to stop | The customer asked us not to contact them. |
| R060 | A complaint is open | Contact is frozen for 30 days while the complaint is handled. |
| R061 | The debt is disputed | Calls, SMS and WhatsApp are paused until the dispute is settled. |
| R062 | A promise to pay is open | No collection contact until the day after the promised date. |
| R063 | Only the promise's owner may remind | The one reminder the day before comes from the agent that took the promise. |
| R064 | A broken promise goes to Negotiation | Negotiation takes over when a promise is broken. |
| R066 | A payment just came in | No contact for 48 hours while it is reconciled (except the confirmation). |

### Limits on how often
| Code | Label | One-line explanation |
|---|---|---|
| R009, R023, R025, R027, R029, R031 | Daily contact limit reached | The borrower already had the maximum contacts today, across all channels and accounts. The limit depends on the stage (1 to 3 a day). |
| R010, R024, R026, R028, R030, R032 | Weekly contact limit reached | The borrower already had the maximum contacts in 7 days. |
| R011, R013, R015, R017, R019 | Channel limit for today reached | Too many contacts on this channel today (calls 2, SMS 2, WhatsApp 1, email 1). |
| R012, R014, R016, R018, R020 | Channel limit for the week reached | Too many contacts on this channel this week. |
| R021 | Calls must be an hour apart | The last call was less than 60 minutes ago. |
| R022 | Contacts must be 30 minutes apart | Another contact went out a moment ago, so this one waits. |
| R033, R034 | Counted per borrower, failed attempts included | Limits count all of a borrower's accounts together, and a failed attempt still counts. |

### Who may act (ownership)
| Code | Label | One-line explanation |
|---|---|---|
| R035, R036 | Another agent owns this borrower | Only the owner may contact; the other agent is stopped. |
| R037, R038 | One owner for 24 hours | Ownership covers all of the borrower's accounts and lasts 24 hours after the last contact. |
| R039, A12 | A higher-priority agent took over | Legal outranks Negotiation, which outranks Servicing, which outranks Reminder. The change is approved and logged. |
| R040 | Legal case: only the Legal agent may act | Every other agent is excluded. |
| R041 | Settlement in progress: only Negotiation may act | Every other agent is excluded. |
| R042 | Restructure in progress: no legal action | Legal action needs approval first. |
| R075 | Legal agent only after 90 days | Or when a legal flag is set. |
| D12-matrix | No agent is allowed to act at this stage | The policy table lists no agent for this event and this overdue stage. |

### Consent and contact details
| Code | Label | One-line explanation |
|---|---|---|
| R043 | No consent to call | Call consent is missing or withdrawn. |
| R044 | No consent to SMS | SMS consent is missing or withdrawn. |
| R045 | WhatsApp needs clear consent | "Unknown" is not enough for WhatsApp. |
| R046 | No consent to email | Email consent is withdrawn. |
| R047 | Borrower opted out of this channel | They told us to stop using it. |
| R048 | Consent has expired | Treated as not given. |
| R049 | Consent source is unrecorded | We cannot show where the consent came from. |
| R050, R051, R053 | On the Do-Not-Disturb list | No calls or SMS unless the message is a transaction notice; takes effect 7 days after registration. |
| R055 | Wrong number on record | The number is blocked for every agent. |
| R056 | Phone shared with another borrower | Identity must be checked before discussing the debt. |
| R069 | No phone number on record | |
| R070 | No email address on record | |
| R072 | WhatsApp is not used after 90 days | Formal notices go by email. |

### Hours
| Code | Label | One-line explanation |
|---|---|---|
| R001 to R005, R007 | Outside contact hours | Contact is allowed only between 8 am and 7 pm. |
| R006 | Borrower asked for specific hours | We only contact within the window they chose. |

### Budget
| Code | Label | One-line explanation |
|---|---|---|
| R092 | Agent's daily budget used up | The channel agent reached its attempts or spend limit for today. |

## Sentences for each station's hover ("what the supervisor did")

Generated from the real decision-log row; `{...}` are filled from it.

| Station | Sentence (success) | Sentence (stopped or changed) |
|---|---|---|
| Event received | "Checked the event is valid." | "Rejected: {why}." |
| Borrower loaded | "Opened the file: {dpd} days past due, {n} account(s)." | |
| Safety checks | "Allowed. {used} of {cap} contacts used today, no holds." | "Stopped: {label}." |
| Agent chosen | "Chose {Role} agent ({action}) on {Channel}. {Others} kept as backups." | "No agent can act: {label}." / "Waiting: {label}." |
| Ownership taken | "Locked the borrower to {Channel}. Owner: nobody → {Role}." | "Handoff {from} → {to}: {label}." |
| Agent acts | "{Channel} agent sent the message in {ms} ms." | "{Channel} agent {crashed / stopped answering / returned junk}." |
| Result checked | "The result is well formed; the contact is confirmed." | "Problem found: {fault in words}." |
| Recover | "Asked the provider: {sent / not sent / unknown}. {Action in words}." | |
| State saved | "Saved the contact and gave {Role} a 24-hour lease." | "Held for a person: {why}." |
| Done / Stopped | "Done: {outcome word}." | "Stopped: {label}." |

## Where each translation lives

One backend module (`orchestrator/ui/reasons.py`) holds this catalogue and the sentence builders; every API that returns a
reason returns both the code list and the plain text. The frontend never translates, so there is one source of wording and a
test can check that **no code reaches the screen without a label** (see 08).

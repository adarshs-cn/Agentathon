# 04. Demo scenario: 15 events, one idea each

The dropdown holds exactly these 15 events. Each one is chosen to make **one** workflow feature visible, so a viewer who steps
through them in order sees every important behaviour of the supervisor once, with no repetition.

All 15 use **real borrowers from the loaded portfolio**, picked by rule at build time (not hard-coded IDs), so the data is real
and the result is repeatable. Every message is shown as sent to **one configurable demo phone number** (see 09 and 06).

Event times are on the dataset's "today" (31 Oct 2026), in running order from 09:00, except the two that need a particular hour.

| # | Dropdown label | Event | Borrower is chosen as | Set up beforehand | Expected path | Expected result (plain words) | What it teaches |
|---|---|---|---|---|---|---|---|
| 1 | **Reminder due** | `DUE_SOON` | 0 days past due; WhatsApp consent granted with a source, not expired, no opt-out; no contact in the last 7 days; no open promise | none | Reminder agent, WhatsApp | **Message sent** on WhatsApp. Owner: nobody, then Reminder for 24 h. | The happy path, start to finish. |
| 2 | **Reminder due, WhatsApp not allowed** | `DUE_SOON` | As 1, but WhatsApp consent is "unknown" and email consent granted | none | Reminder agent, WhatsApp refused, Email chosen | **Message sent** by email. | The supervisor reads consent and falls back to another channel. |
| 3 | **Payment overdue, 31 to 60 days** | `OVERDUE` | 31 to 60 days past due; voice allowed; no hold | none | Negotiation agent, Voice (IVR) | **Message sent**: the IVR call script. | A different role and channel for a later stage. |
| 4 | **A higher-priority agent takes over** | `OVERDUE` | 31 to 60 days past due | A Reminder contact was made yesterday evening, so Reminder owns the borrower | Negotiation outranks Reminder, takes over | **Message sent**, with a visible handoff Reminder → Negotiation. | One owner at a time; ownership can pass to a higher-priority agent, and it is logged. |
| 5 | **Promise due tomorrow** | `PTP_DUE` | Open promise to pay due tomorrow, taken by the Reminder agent; 1 to 30 days past due | the open promise | The agent that took the promise reminds, on its preferred channel | **Message sent**: the one allowed reminder the day before. | Only the promise's owner may remind. |
| 6 | **Promise broken** | `PTP_BROKEN` | Promise marked broken; 1 to 30 days past due | the broken promise | Negotiation takes over from Reminder | **Message sent** by Negotiation. | A broken promise moves ownership to Negotiation. |
| 7 | **Payment received** | `PAYMENT_RECEIVED` | Any borrower with no legal flag | a payment today | Servicing agent | **Message sent**: a payment confirmation. | Confirmations are allowed even during the 48-hour payment hold. |
| 8 | **Overdue, but a promise is open** | `OVERDUE` | Open promise due in 2 to 5 days | the open promise | Stopped at Safety checks | **Not allowed**: a promise to pay is open until the day after it is due. | The supervisor refuses, and says why in words. |
| 9 | **Borrower asked us to stop** | `OVERDUE` | Suppression reason "customer request" | none | Stopped at Safety checks | **Not allowed**: the borrower asked us to stop. | Suppression beats everything else. |
| 10 | **Outside contact hours** | `OVERDUE` at **07:30** | 1 to 30 days past due; WhatsApp allowed | none | Stopped at Agent chosen, deferred | **Waiting for a better time**: earliest 08:00. | Nothing is lost; it is rescheduled. |
| 11 | **Two requests at once: the first** | `OVERDUE` at **14:00** | 1 to 30 days past due; WhatsApp allowed | none | Reminder agent, WhatsApp | **Message sent**. | First of a pair. |
| 12 | **Two requests at once: the second** | `CONTACT_REQUESTED` at **14:02**, same borrower as 11 | (same as 11) | event 11 must have run | Stopped at Safety checks | **Waiting**: another contact went out 2 minutes ago; minimum gap is 30 minutes. | "Two agents fire on the same borrower at once" ends in exactly one contact. |
| 13 | **Agent crashes after sending** | `OVERDUE` | 1 to 30 days past due; WhatsApp allowed | fault injected: WhatsApp agent crashes **after** the send | Recover branch lights up | **Message sent once.** The supervisor asked the provider, saw it was sent, and did not send again. | The hardest fault: crash after send must not double-contact. |
| 14 | **Agent stops making progress** | `OVERDUE` | 1 to 30 days past due; WhatsApp and email allowed | fault injected: the WhatsApp agent answers "still working" three times | Recover branch: retry twice, then switch channel | **Message sent** by email after WhatsApp was abandoned. | Loop detection, then rerouting. |
| 15 | **Legal case** | `OVERDUE` | Legal flag on any account, email on record | none | Legal agent, Email | **Message sent**: a formal notice by email. Reminder and Negotiation are excluded. | A legal flag means only the Legal agent may act. |

## Why these 15

They cover, with no overlap: the happy path (1), channel fallback by consent (2), role by stage (3), ownership handoff (4), the
promise rules (5, 6, 8), service replies (7), suppression (9), contact hours and deferral (10), simultaneous requests (11, 12),
the two hardest fault classes (13, 14), and exclusivity by legal flag (15). If one slot must change, the next candidates are:
Do-Not-Disturb blocking calls (swap for 2), a deceased borrower (swap for 9), a timeout quarantined for a human (swap for 14).

## How the borrowers are chosen

A deterministic builder (see 06) asks the database for the first borrower matching each row's criteria (seeded, so the same
borrowers every time). A test asserts that every criterion finds a borrower and that each event ends the way the table says.
If the dataset ever lacks a match, the builder fails loudly instead of quietly picking something else.

## The demo contact

For presentation, each of the 15 borrowers is shown with the **same demo phone number**, so the "phone view" always reads
`To: XXXXXX1234`. The number is configured outside the code (see 09); it is never committed and is masked unless explicitly
unmasked for the demo machine. The borrower's own masked name is used in the message text.

## Order and independence

Events are meant to be run in order 1 to 15, but each can be run alone, except **12**, which needs **11** to have run (the
dropdown shows 12 as unavailable until then, with a one-line explanation). **Reset demo** returns all 15 to "not run" and
rebuilds the data.

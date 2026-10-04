"""Shared side-effect machinery: institution suspension cascade, file
supersession, servicer-notification generation, and the pinned six-step
logical-clock advance (PRD §2.4).
"""
from datetime import timedelta

import calc
import db
from db import touch


# ---------------------------------------------------------------------------
# Agreements / institution status
# ---------------------------------------------------------------------------
def active_agreement_covers(institution_id):
    """An ACTIVE-status agreement of this institution exists (status is the
    source of truth; the clock keeps it consistent with the window)."""
    for a in db.store.agreements.values():
        if a["institution_id"] == institution_id and a["status"] == "ACTIVE":
            return True
    return False


def cancel_requests_for_institution(institution_id):
    """QUOTED/PAID requests targeting the institution -> CANCELLED, created_at
    ASC; PAID requests refund fee_cents in full (PRD §3.1)."""
    targets = [
        r
        for r in db.store.requests.values()
        if r["institution_id"] == institution_id and r["status"] in ("QUOTED", "PAID")
    ]
    for r in db.sorted_created(targets):
        if r["status"] == "PAID":
            r["refund_cents"] = r["fee_cents"]
            if r["requester_id"]:
                requester = db.store.requesters.get(r["requester_id"])
                if requester is not None:
                    requester["credit_balance_cents"] += r["refund_cents"]
                    touch(requester)
        r["status"] = "CANCELLED"
        touch(r)


def suspend_institution(inst, reason):
    inst["status"] = "SUSPENDED"
    inst["suspension_reason"] = reason
    touch(inst)
    cancel_requests_for_institution(inst["id"])


# ---------------------------------------------------------------------------
# Servicer notifications
# ---------------------------------------------------------------------------
def generate_notification(entry):
    """QUEUED ServicerNotification for an ACCEPTED entry with servicer_ref."""
    if not entry.get("servicer_ref"):
        return None
    grace_end = None
    if entry["deferment_status"] == "WITHDRAWN_GRACE" and entry["withdrawal_date"] is not None:
        grace_end = entry["withdrawal_date"] + timedelta(days=calc.WITHDRAWAL_GRACE_DAYS)
    n = db.new_entity(
        {
            "enrollment_entry_id": entry["id"],
            "student_id": entry["student_id"],
            "servicer_ref": entry["servicer_ref"],
            "notification_type": entry["deferment_status"],
            "grace_end_date": grace_end,
            "status": "QUEUED",
        }
    )
    db.store.notifications[n["id"]] = n
    return n


def supersede_notifications_for_entry(entry_id):
    """QUEUED/SENT notifications of an entry -> SUPERSEDED; ACKNOWLEDGED remain."""
    for n in db.store.notifications.values():
        if n["enrollment_entry_id"] == entry_id and n["status"] in ("QUEUED", "SENT"):
            n["status"] = "SUPERSEDED"
            touch(n)


# ---------------------------------------------------------------------------
# EnrollmentFile supersession
# ---------------------------------------------------------------------------
def supersede_file_entries(file, include_rejected):
    for e in db.store.entries.values():
        if e["file_id"] != file["id"]:
            continue
        if e["entry_status"] == "ACCEPTED" or (include_rejected and e["entry_status"] == "REJECTED"):
            e["entry_status"] = "SUPERSEDED"
            touch(e)


def supersede_certified_file(file):
    """CERTIFIED/AMENDMENT_PENDING file superseded by a new certification:
    ACCEPTED entries -> SUPERSEDED; QUEUED/SENT notifications -> SUPERSEDED."""
    file["status"] = "SUPERSEDED"
    touch(file)
    for e in db.store.entries.values():
        if e["file_id"] == file["id"] and e["entry_status"] == "ACCEPTED":
            e["entry_status"] = "SUPERSEDED"
            touch(e)
            supersede_notifications_for_entry(e["id"])


# ---------------------------------------------------------------------------
# ReportingPeriod close
# ---------------------------------------------------------------------------
def close_period(period):
    files = [
        f
        for f in db.store.files.values()
        if f["reporting_period_id"] == period["id"] and f["certified_at"] is not None
    ]
    if any(f["certified_at"] <= period["submission_due_at"] for f in files):
        period["outcome"] = "ON_TIME"
    elif files:
        period["outcome"] = "LATE"
    else:
        period["outcome"] = "DELINQUENT"
    inst = db.store.institutions.get(period["institution_id"])
    if inst is not None:
        inst["compliance_standing"] = calc.compliance_standing(inst["id"])
        touch(inst)


# ---------------------------------------------------------------------------
# Logical clock advance — pinned six-step order (PRD §2.4)
# ---------------------------------------------------------------------------
def process_clock(new_now):
    store = db.store
    store.current_utc = new_now
    now = new_now

    # Step 1: agreements flip, institution cascades applied as they go.
    # Activations first so a covering agreement landing in the same step
    # prevents a spurious lapse-suspension.
    agreements = db.sorted_created(store.agreements.values())
    for a in agreements:
        if a["status"] == "SCHEDULED" and a["effective_from"] <= now < a["effective_to"]:
            a["status"] = "ACTIVE"
            touch(a)
            inst = store.institutions.get(a["institution_id"])
            if (
                inst is not None
                and inst["status"] == "SUSPENDED"
                and inst["suspension_reason"] == "AGREEMENT_LAPSE"
            ):
                inst["status"] = "ACTIVE"
                inst["suspension_reason"] = "NONE"
                touch(inst)
    for a in agreements:
        if a["status"] in ("SCHEDULED", "ACTIVE") and now >= a["effective_to"]:
            was_active = a["status"] == "ACTIVE"
            a["status"] = "EXPIRED"
            touch(a)
            if was_active:
                inst = store.institutions.get(a["institution_id"])
                if (
                    inst is not None
                    and inst["status"] == "ACTIVE"
                    and not active_agreement_covers(inst["id"])
                ):
                    # Step 2 (request-cancellation cascade) runs inside
                    # suspend_institution, in created_at ASC order.
                    suspend_institution(inst, "AGREEMENT_LAPSE")

    # Step 3: reporting periods advance (submission_due_at ASC, created_at ASC).
    periods = [p for p in store.periods.values() if p["status"] != "CLOSED"]
    periods.sort(key=lambda p: p["_seq"])
    periods.sort(key=lambda p: p["submission_due_at"])  # stable
    for p in periods:
        if now > p["grace_ends_at"]:
            target = "CLOSED"
        elif now > p["submission_due_at"]:
            target = "GRACE"
        elif now >= p["submission_opens_at"]:
            target = "OPEN"
        else:
            target = p["status"]
        if target != p["status"]:
            p["status"] = target
            touch(p)
            if target == "CLOSED":
                close_period(p)

    # Step 4: QUOTED requests past quote_expires_at -> EXPIRED (created_at ASC).
    for r in db.sorted_created([r for r in store.requests.values() if r["status"] == "QUOTED"]):
        if now >= r["quote_expires_at"]:
            r["status"] = "EXPIRED"
            touch(r)

    # Step 5: QUEUED notifications -> SENT (created_at ASC).
    for n in db.sorted_created([n for n in store.notifications.values() if n["status"] == "QUEUED"]):
        n["status"] = "SENT"
        touch(n)

    # Step 6: ACTIVE privacy directives past effective_to -> EXPIRED (created_at ASC).
    for d in db.sorted_created([d for d in store.directives.values() if d["status"] == "ACTIVE"]):
        if d["effective_to"] is not None and now >= d["effective_to"]:
            d["status"] = "EXPIRED"
            touch(d)

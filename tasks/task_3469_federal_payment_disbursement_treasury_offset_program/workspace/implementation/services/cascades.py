"""System-driven cascades: payment-file rollup, the clock's settlement sweep,
and the do-not-pay hold/release cascades (PRD §2.4, §2.11, §3.4, §3.5, §3.9).
"""
from db import STORE, clock_now, touch

_TERMINAL_PAYMENT_STATUSES = ("SETTLED", "REVERSED")


def file_recompute(payment_file):
    """Recompute a PaymentFile's derived totals and status after any payment
    state change (SCAFFOLD calculations.file_total_aggregation): totals are the
    plain sums of the per-payment rounded values; the file flips RECEIVED ->
    PROCESSING on its first payment and PROCESSING -> COMPLETED once it holds
    at least one payment and every payment is SETTLED or REVERSED."""
    payments = [
        p for p in STORE["payments"].values() if p["payment_file_id"] == payment_file["id"]
    ]
    changed = False
    count = len(payments)
    total_offset = sum(p["total_offset_cents"] for p in payments)
    total_disbursed = sum(p["disbursed_cents"] for p in payments)
    if (
        payment_file["payment_count"] != count
        or payment_file["total_offset_cents"] != total_offset
        or payment_file["total_disbursed_cents"] != total_disbursed
    ):
        payment_file["payment_count"] = count
        payment_file["total_offset_cents"] = total_offset
        payment_file["total_disbursed_cents"] = total_disbursed
        changed = True
    if payment_file["status"] == "RECEIVED" and count > 0:
        payment_file["status"] = "PROCESSING"
        changed = True
    if (
        payment_file["status"] == "PROCESSING"
        and count > 0
        and all(p["processing_status"] in _TERMINAL_PAYMENT_STATUSES for p in payments)
    ):
        payment_file["status"] = "COMPLETED"
        changed = True
    if changed:
        touch(payment_file)


def settlement_sweep():
    """POST /_clock/set_current_utc sweep: every EXECUTED payment whose parent
    file's settlement_date is on or before the clock's UTC date transitions to
    SETTLED (PRD §2.4); files may then bubble to COMPLETED."""
    now = clock_now()
    for p in sorted(STORE["payments"].values(), key=lambda x: x["_seq"]):
        if p["processing_status"] != "EXECUTED":
            continue
        payment_file = STORE["files"].get(p["payment_file_id"])
        if payment_file is None:
            continue
        if payment_file["settlement_date"].date() <= now.date():
            p["processing_status"] = "SETTLED"
            touch(p)
            file_recompute(payment_file)


def dnp_hit(tin):
    """Does an ACTIVE do-not-pay record exist whose closed interval contains
    the current clock (PRD §2.11)?"""
    now = clock_now()
    for r in STORE["dnp_records"].values():
        if (
            r["status"] == "ACTIVE"
            and r["tin"] == tin
            and r["effective_from"] <= now <= r["effective_until"]
        ):
            return True
    return False


def dnp_window_overlap(tin, list_source, effective_from, effective_until):
    """Closed-interval conflict on the same (tin, list_source) among ACTIVE
    records; touching intervals count as overlapping (PRD §2.11)."""
    for r in STORE["dnp_records"].values():
        if r["status"] != "ACTIVE":
            continue
        if r["tin"] != tin or r["list_source"] != list_source:
            continue
        if effective_from <= r["effective_until"] and r["effective_from"] <= effective_until:
            return True
    return False


def dnp_create_cascade(tin):
    """Flag/hold cascade on record creation (PRD §3.9): every not-yet-executed
    payment whose payee TIN now matches is flagged — VERIFIED is forced to
    HELD, EVALUATED is flagged but stays EVALUATED. Payments past execution
    are untouched."""
    if not dnp_hit(tin):
        return
    for p in STORE["payments"].values():
        if p["payee_tin"] != tin:
            continue
        if p["processing_status"] == "VERIFIED":
            p["integrity_status"] = "FLAGGED"
            p["processing_status"] = "HELD"
            touch(p)
        elif p["processing_status"] == "EVALUATED" and p["integrity_status"] != "FLAGGED":
            p["integrity_status"] = "FLAGGED"
            touch(p)


def dnp_remove_cascade(tin):
    """Release cascade on record removal (PRD §3.9): when no remaining ACTIVE
    record matches the TIN at the current clock, HELD payments return to
    VERIFIED with integrity CLEAR; EVALUATED payments that were flagged are
    cleared in place (they stay EVALUATED)."""
    if dnp_hit(tin):
        return
    for p in STORE["payments"].values():
        if p["payee_tin"] != tin:
            continue
        if p["processing_status"] == "HELD":
            p["processing_status"] = "VERIFIED"
            p["integrity_status"] = "CLEAR"
            touch(p)
        elif p["processing_status"] == "EVALUATED" and p["integrity_status"] == "FLAGGED":
            p["integrity_status"] = "CLEAR"
            touch(p)

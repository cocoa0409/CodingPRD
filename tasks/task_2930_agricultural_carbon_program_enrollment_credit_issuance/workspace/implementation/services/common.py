"""Shared lookups, filters and cascades."""

from decimal import Decimal

from flask import request

import db
from errors import ApiError
from services import calc

TERMINAL_ENROLLMENT_STATUSES = ("REJECTED", "EXITED", "TERMINATED")


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# lookups (rung 3 for path parameters, rung 6 for body foreign keys)
# ---------------------------------------------------------------------------
def _lookup(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


def get_grower(grower_id):
    return _lookup(db.growers, grower_id, "ERR_GROWER_NOT_FOUND")


def get_field(field_id):
    return _lookup(db.fields, field_id, "ERR_FIELD_NOT_FOUND")


def get_practice_history(row_id):
    return _lookup(db.practice_history, row_id, "ERR_PRACTICE_HISTORY_NOT_FOUND")


def get_practice_standard(standard_id):
    return _lookup(db.practice_standards, standard_id, "ERR_PRACTICE_STANDARD_NOT_FOUND")


def get_enrollment(enrollment_id):
    return _lookup(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def get_baseline(baseline_id):
    return _lookup(db.baselines, baseline_id, "ERR_BASELINE_NOT_FOUND")


def get_data_packet(packet_id):
    return _lookup(db.data_packets, packet_id, "ERR_DATA_PACKET_NOT_FOUND")


def get_quantification_run(run_id):
    return _lookup(db.quantification_runs, run_id, "ERR_QUANTIFICATION_RUN_NOT_FOUND")


def get_verification_body(body_id):
    return _lookup(db.verification_bodies, body_id, "ERR_VERIFICATION_BODY_NOT_FOUND")


def get_verification(verification_id):
    return _lookup(db.verifications, verification_id, "ERR_VERIFICATION_NOT_FOUND")


def get_credit_batch(batch_id):
    return _lookup(db.credit_batches, batch_id, "ERR_CREDIT_BATCH_NOT_FOUND")


def get_buffer_account(account_id):
    return _lookup(db.buffer_accounts, account_id, "ERR_BUFFER_ACCOUNT_NOT_FOUND")


def get_reversal_event(event_id):
    return _lookup(db.reversal_events, event_id, "ERR_REVERSAL_EVENT_NOT_FOUND")


def get_grower_payment(payment_id):
    return _lookup(db.grower_payments, payment_id, "ERR_GROWER_PAYMENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# ownership resolution
# ---------------------------------------------------------------------------
def enrollment_grower_id(enrollment):
    return enrollment["grower_id"]


def run_grower_id(run):
    return db.enrollments[run["enrollment_id"]]["grower_id"]


def verification_grower_id(verification):
    return run_grower_id(db.quantification_runs[verification["quantification_run_id"]])


def batch_grower_id(batch):
    return db.enrollments[batch["enrollment_id"]]["grower_id"]


# ---------------------------------------------------------------------------
# list filters
# ---------------------------------------------------------------------------
def _int_arg(name):
    raw = request.args.get(name)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def apply_filters(rows, spec):
    """``spec`` maps a query parameter name to (row_key, kind)."""
    out = list(rows)
    for param, (key, kind) in spec.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        if kind == "int":
            wanted = _int_arg(param)
            out = [r for r in out if r.get(key) == wanted]
        elif kind == "list":
            out = [r for r in out if raw in (r.get(key) or [])]
        else:
            out = [r for r in out if r.get(key) == raw]
    return out


# ---------------------------------------------------------------------------
# buffer pool derivation
# ---------------------------------------------------------------------------
def recompute_pool(pool):
    pool["required_reserve_credits"] = calc.required_reserve(
        pool["min_reserve_ratio"], pool["outstanding_issued_credits"]
    )
    pool["pool_status"] = (
        "HEALTHY" if pool["balance_credits"] >= pool["required_reserve_credits"] else "DEFICIT"
    )
    return pool


# ---------------------------------------------------------------------------
# grower suspension cascade (section 3.1)
# ---------------------------------------------------------------------------
def suspend_grower_cascade(grower, reason):
    grower["status"] = "SUSPENDED"
    grower["suspension_reason"] = reason
    db.touch(grower)
    for enrollment in db.sorted_rows(db.enrollments):
        if enrollment["grower_id"] != grower["id"] or enrollment["status"] != "ACTIVE":
            continue
        enrollment["status"] = "SUSPENDED"
        db.touch(enrollment)
        field = db.fields.get(enrollment["field_id"])
        if field is not None and field["status"] == "ENROLLED":
            field["status"] = "SUSPENDED"
            db.touch(field)
    return grower


def reinstate_grower_cascade(grower):
    grower["status"] = "ACTIVE"
    grower["suspension_reason"] = None
    db.touch(grower)
    for enrollment in db.sorted_rows(db.enrollments):
        if enrollment["grower_id"] != grower["id"] or enrollment["status"] != "SUSPENDED":
            continue
        enrollment["status"] = "ACTIVE"
        db.touch(enrollment)
        field = db.fields.get(enrollment["field_id"])
        if field is not None and field["status"] == "SUSPENDED":
            field["status"] = "ENROLLED"
            db.touch(field)
    return grower


def maybe_suspend_for_clawback(grower):
    if (
        grower["status"] == "ACTIVE"
        and grower["outstanding_clawback_cents"] >= calc.CLAWBACK_SUSPENSION_THRESHOLD_CENTS
    ):
        suspend_grower_cascade(grower, "Outstanding clawback balance exceeded programme threshold.")


# ---------------------------------------------------------------------------
# field release on exit / termination (section 3.1 and 3.9)
# ---------------------------------------------------------------------------
def release_field(enrollment):
    field = db.fields.get(enrollment["field_id"])
    if field is None or field["status"] != "ENROLLED":
        return
    for other in db.enrollments.values():
        if other["id"] == enrollment["id"]:
            continue
        if other["field_id"] != field["id"]:
            continue
        if other["status"] in ("ACTIVE", "SUSPENDED"):
            return
    field["status"] = "MAPPED"
    db.touch(field)
    grower = db.growers.get(field["grower_id"])
    if grower is not None:
        grower["total_enrolled_acres"] = Decimal(grower["total_enrolled_acres"]) - Decimal(
            field["mapped_acres"]
        )
        db.touch(grower)


# ---------------------------------------------------------------------------
# payment helpers
# ---------------------------------------------------------------------------
def enrollment_payments(enrollment_id):
    return [p for p in db.sorted_rows(db.grower_payments) if p["enrollment_id"] == enrollment_id]


def settled_cents(enrollment_id):
    total = 0
    for payment in enrollment_payments(enrollment_id):
        if payment["status"] == "PAID":
            total += payment["net_amount_cents"]
    return total


def add_accrual(enrollment, amount):
    enrollment["accrued_payment_cents"] = enrollment["accrued_payment_cents"] + amount
    db.touch(enrollment)


# ---------------------------------------------------------------------------
# permanence / registry helpers
# ---------------------------------------------------------------------------
def breach_enrollments_for_batches(batches, event):
    """Hops five and six of the reversal assessment cascade."""
    seen = []
    for batch in batches:
        enrollment = db.enrollments.get(batch["enrollment_id"])
        if enrollment is None or enrollment["id"] in seen:
            continue
        seen.append(enrollment["id"])
        enrollment["permanence_status"] = "BREACHED"
        db.touch(enrollment)
        for payment in enrollment_payments(enrollment["id"]):
            if payment["status"] != "ACCRUED":
                continue
            payment["status"] = "CLAWED_BACK"
            db.touch(payment)
            enrollment["accrued_payment_cents"] = (
                enrollment["accrued_payment_cents"] - payment["net_amount_cents"]
            )
            db.touch(enrollment)

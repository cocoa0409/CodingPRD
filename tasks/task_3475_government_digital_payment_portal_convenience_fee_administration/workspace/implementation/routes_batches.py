"""Settlement batches and treasury reconciliation (PRD section 3.5):
open / close (sweep) / submit / confirm / reconcile / exceptions."""
from datetime import date as _date
from datetime import timedelta

from flask import Blueprint, request

import clock
import envelope
import fees
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_date, as_int, as_str, body, req_field

bp = Blueprint("batches", __name__)

BATCH_READ_ROLES = {"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer"}
_EPOCH = _date(1970, 1, 1)


@bp.route("/portal/settlement-batches", methods=["POST"])
def create_batch():
    caller({"PlatformAdmin", "AgencyAdmin"})
    data = body()
    agency_id = as_str(req_field(data, "agency_id"), "agency_id")
    business_date = as_date(req_field(data, "business_date"), "business_date")
    helpers.get_agency(agency_id)
    # priority 5: only one OPEN batch per agency
    if helpers.find_open_batch(agency_id) is not None:
        raise_err(
            "ERR_BATCH_ALREADY_OPEN",
            409,
            "The agency already has an OPEN settlement batch",
        )
    rec = helpers.new_batch(agency_id, business_date)
    store.batches[rec["id"]] = rec
    return envelope.obj(serialize.batch(rec), 201)


@bp.route("/portal/settlement-batches/<rid>", methods=["GET"])
def get_batch(rid):
    caller(BATCH_READ_ROLES)
    return envelope.obj(serialize.batch(helpers.get_batch(rid)))


@bp.route("/portal/agencies/<rid>/settlement-batches", methods=["GET"])
def list_batches(rid):
    caller(BATCH_READ_ROLES)
    helpers.get_agency(rid)
    status = request.args.get("status")
    items = [b for b in store.batches.values() if b["agency_id"] == rid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["created_seq"]))
    return envelope.page([serialize.batch(b) for b in items], request.args)


@bp.route("/portal/settlement-batches/<rid>/close", methods=["POST"])
def close_batch(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_batch(rid)
    if rec["status"] != "OPEN":
        invalid_state("Only an OPEN batch can be closed (status %s)" % rec["status"])
    # Sweep: CAPTURED or RE_PRESENTED, not already in a batch, value_date on
    # or before the business date (inclusive: equality is swept in).
    members = [
        t
        for t in store.transactions.values()
        if t["agency_id"] == rec["agency_id"]
        and t["funds_status"] in ("CAPTURED", "RE_PRESENTED")
        and t["current_batch_id"] is None
        and t["value_date"] is not None
        and t["value_date"] <= rec["business_date"]
    ]
    members.sort(key=lambda t: (t["created_at"], t["created_seq"]))
    for t in members:
        t["funds_status"] = "SETTLED"
        t["current_batch_id"] = rec["id"]
        helpers.touch(t)
    rec["member_count"] = len(members)
    rec["gross_amount_cents"] = sum(t["amount_cents"] for t in members)
    rec["fees_withheld_cents"] = sum(t["charged_fee_cents"] for t in members)
    # finalized at close; may be negative
    rec["deposit_cents"] = (
        rec["gross_amount_cents"]
        - rec["refund_debits_cents"]
        - rec["return_debits_cents"]
        - rec["chargeback_debits_cents"]
    )
    rec["deposit_due_date"] = (
        max(t["value_date"] for t in members) if members else rec["business_date"]
    )
    rec["status"] = "CLOSED"
    helpers.touch(rec)
    return envelope.obj(serialize.batch(rec))


@bp.route("/portal/settlement-batches/<rid>/submit", methods=["POST"])
def submit_batch(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_batch(rid)
    if rec["status"] != "CLOSED":
        invalid_state("Only a CLOSED batch can be submitted (status %s)" % rec["status"])
    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = clock.now()
    helpers.touch(rec)
    return envelope.obj(serialize.batch(rec))


@bp.route("/portal/settlement-batches/<rid>/confirm-deposit", methods=["POST"])
def confirm_deposit(rid):
    caller({"TreasuryOfficer"})
    rec = helpers.get_batch(rid)
    data = body()
    actual = as_int(req_field(data, "actual_deposit_cents"), "actual_deposit_cents")
    if rec["status"] != "SUBMITTED":
        invalid_state(
            "Only a SUBMITTED batch can be deposit-confirmed (status %s)"
            % rec["status"]
        )
    rec["status"] = "CONFIRMED"
    rec["actual_deposit_cents"] = actual
    rec["confirmed_at"] = clock.now()
    helpers.touch(rec)
    return envelope.obj(serialize.batch(rec))


def _new_exception(batch_id, exc_type, expected, actual, detail):
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "batch_id": batch_id,
        "exception_type": exc_type,
        "expected_cents": expected,
        "actual_cents": actual,
        "detail": detail,
        "status": "OPEN",
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.exceptions[rec["id"]] = rec
    return rec


@bp.route("/portal/settlement-batches/<rid>/reconcile", methods=["POST"])
def reconcile_batch(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_batch(rid)
    if rec["status"] != "CONFIRMED":
        invalid_state(
            "Only a CONFIRMED batch can be reconciled (status %s)" % rec["status"]
        )
    mismatched = rec["actual_deposit_cents"] != rec["deposit_cents"]
    latest_ok = _date.fromisoformat(rec["deposit_due_date"]) + timedelta(
        days=fees.GRACE_DAYS
    )
    # confirmed exactly on the first day after the due date is NOT late
    late = rec["confirmed_at"].date() > latest_ok
    if mismatched:
        _new_exception(
            rec["id"],
            "AMOUNT_MISMATCH",
            rec["deposit_cents"],
            rec["actual_deposit_cents"],
            "Confirmed deposit %s differs from expected deposit %s"
            % (rec["actual_deposit_cents"], rec["deposit_cents"]),
        )
    if late:
        _new_exception(
            rec["id"],
            "DEPOSIT_LATE",
            (latest_ok - _EPOCH).days,
            None,
            "Deposit confirmed on %s, later than the due date %s plus a "
            "%d-day grace"
            % (rec["confirmed_at"].date().isoformat(), rec["deposit_due_date"], fees.GRACE_DAYS),
        )
    rec["status"] = "EXCEPTION" if (mismatched or late) else "RECONCILED"
    helpers.touch(rec)
    return envelope.obj(serialize.batch(rec))


@bp.route("/portal/settlement-batches/<rid>/exceptions", methods=["GET"])
def list_exceptions(rid):
    caller(BATCH_READ_ROLES)
    helpers.get_batch(rid)
    items = [e for e in store.exceptions.values() if e["batch_id"] == rid]
    # created_at ASC, then exception_type ASC — deterministic even when one
    # reconcile creates several rows under a frozen clock
    items.sort(key=lambda e: (e["created_at"], e["exception_type"], e["created_seq"]))
    return envelope.page([serialize.exception(e) for e in items], request.args)


@bp.route("/portal/reconciliation-exceptions/<rid>/resolve", methods=["POST"])
def resolve_exception(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_exception(rid)
    data = body()
    note = as_str(req_field(data, "resolution_note"), "resolution_note")
    if rec["status"] != "OPEN":
        invalid_state("Only an OPEN exception can be resolved")
    batch = helpers.get_batch(rec["batch_id"])
    if batch["status"] != "EXCEPTION":
        invalid_state("The parent batch is not in EXCEPTION status")
    rec["status"] = "RESOLVED"
    rec["resolution_note"] = note
    helpers.touch(rec)
    # bubble up: the last OPEN exception resolving reconciles the batch
    if helpers.open_exception_count(batch["id"]) == 0:
        batch["status"] = "RECONCILED"
        helpers.touch(batch)
    return envelope.obj(serialize.exception(rec))

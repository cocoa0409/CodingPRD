"""Blocking analytics and erroneous-blocking disputes (PRD 3.7)."""
import datetime
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_customer import load_customer
from views_provider import load_provider

bp = Blueprint("blocking", __name__)

EVENT_STATUSES = ("BLOCKED", "UPHELD", "REVERSED")
REASONS = ("ANALYTICS_SCORE", "NOTICE_MANDATE", "UNSIGNED_TRAFFIC")
DISPUTE_STATES = ("FILED", "UNDER_REVIEW", "UPHELD", "REVERSED", "WITHDRAWN")
OUTCOMES = ("UPHOLD", "REVERSE")
BLOCKING_SCORE_THRESHOLD = Decimal("0.6500")
BLOCKING_SUSPEND_THRESHOLD = Decimal("0.9500")
LIVE_DISPUTE_STATES = ("FILED", "UNDER_REVIEW", "UPHELD", "REVERSED")
DISPUTE_WINDOW_HOURS = 24

EVENT_READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER,
                    auth.FRAUD_ANALYST, auth.PROVIDER_ADMIN, auth.CALLER)
DISPUTE_READ_ROLES = EVENT_READ_ROLES


def load_event(event_id):
    row = db.blocking_events.get(event_id)
    if row is None:
        errors.fail(errors.ERR_BLOCKING_EVENT_NOT_FOUND,
                    "No blocking event with id %s" % event_id)
    return row


def load_dispute(dispute_id):
    row = db.disputes.get(dispute_id)
    if row is None:
        errors.fail(errors.ERR_DISPUTE_NOT_FOUND,
                    "No blocking dispute with id %s" % dispute_id)
    return row


def _bad_dispute_state(message):
    errors.fail(errors.ERR_DISPUTE_STATE_INVALID, message)


@bp.route("/rmd/blocking-events", methods=["POST"])
@auth.require(auth.FRAUD_ANALYST)
def record_block():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    customer_id = valid.req_str(data, "customer_id")
    calling_number = valid.req_str(data, "calling_number")
    score = valid.req_score(data, "analytics_score")
    reason = valid.req_enum(data, "reason", REASONS)
    valid.check_e164(calling_number)
    load_provider(provider_id)
    customer = load_customer(customer_id)

    if reason == "ANALYTICS_SCORE" and score < BLOCKING_SCORE_THRESHOLD:
        errors.fail(errors.ERR_SCORE_BELOW_BLOCKING_THRESHOLD,
                    "An ANALYTICS_SCORE block requires a score of at least "
                    "0.6500")
    if customer["provider_id"] != provider_id:
        errors.fail(errors.ERR_CUSTOMER_PROVIDER_MISMATCH,
                    "The customer belongs to another provider")

    triggered = (reason == "ANALYTICS_SCORE"
                 and score >= BLOCKING_SUSPEND_THRESHOLD)
    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "customer_id": customer_id,
        "calling_number": calling_number,
        "analytics_score": float(calc.round_half_up(score, 4)),
        "reason": reason,
        "status": "BLOCKED",
        "blocked_at": db.now(),
        "blocked_by_user_id": auth.acting_id(),
        "reversed_at": None,
        "triggered_suspension": bool(triggered),
    })
    db.blocking_events[row["id"]] = row

    if triggered and customer["origination_state"] == "ENABLED":
        derive.suspend_customer(customer, "BLOCKING_ANALYTICS", row["id"])
    derive.recompute_provider_by_id(provider_id)
    return envelope.created(ser.blocking_event(row))


@bp.route("/rmd/blocking-events/<event_id>", methods=["GET"])
@auth.require(*EVENT_READ_ROLES)
def read_event(event_id):
    row = load_event(event_id)
    auth.own(provider_id=row["provider_id"], customer_id=row["customer_id"])
    return envelope.ok(ser.blocking_event(row))


@bp.route("/rmd/blocking-events", methods=["GET"])
@auth.require(*EVENT_READ_ROLES)
def list_events():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("customer_id")
    status = valid.arg_enum("status", EVENT_STATUSES)

    rows = auth.scope_rows(db.blocking_events.values(),
                           provider_of=lambda r: r["provider_id"],
                           customer_of=lambda r: r["customer_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.collection(rows, ser.blocking_event, limit, offset)


# --- disputes --------------------------------------------------------------
@bp.route("/rmd/blocking-disputes", methods=["POST"])
@auth.require(auth.CALLER)
def file_dispute():
    data = valid.body()
    event_id = valid.req_str(data, "blocking_event_id")
    claim_note = valid.req_str(data, "claim_note")
    event = load_event(event_id)
    auth.own_customer(event["customer_id"])

    for other in db.disputes.values():
        if (other["blocking_event_id"] == event_id
                and other["state"] in LIVE_DISPUTE_STATES):
            errors.fail(errors.ERR_DUPLICATE_DISPUTE,
                        "This blocking event already carries a live dispute")

    filed_at = db.now()
    row = store.base_row()
    row.update({
        "blocking_event_id": event_id,
        "customer_id": auth.acting_id(),
        "claim_note": claim_note,
        "filed_at": filed_at,
        "resolution_deadline_at": filed_at + datetime.timedelta(
            hours=DISPUTE_WINDOW_HOURS),
        "state": "FILED",
        "resolution_note": None,
        "resolved_at": None,
        "resolved_by_user_id": None,
        "resolved_late": False,
    })
    db.disputes[row["id"]] = row
    return envelope.created(ser.dispute(row))


@bp.route("/rmd/blocking-disputes/<dispute_id>/review", methods=["POST"])
@auth.require(auth.FRAUD_ANALYST)
def review_dispute(dispute_id):
    row = load_dispute(dispute_id)
    if row["state"] != "FILED":
        _bad_dispute_state("Only a FILED dispute can be taken under review")
    row["state"] = "UNDER_REVIEW"
    touch(row)
    return envelope.ok(ser.dispute(row))


def _reverse_block(dispute, event):
    now = db.now()
    event["status"] = "REVERSED"
    event["reversed_at"] = now
    touch(event)

    customer = db.customers.get(event["customer_id"])
    if customer is not None:
        values = derive.customer_derived(customer)
        customer.update(values)
        restored = (customer["origination_state"] == "SUSPENDED"
                    and customer["suspension_cause"] == "BLOCKING_ANALYTICS"
                    and customer["suspension_source_id"] == event["id"])
        if restored:
            customer["origination_state"] = "ENABLED"
            customer["suspension_cause"] = None
            customer["suspension_source_id"] = None
        touch(customer)
        if restored:
            derive.cascade_reactivate_assignments(customer)
    derive.recompute_provider_by_id(event["provider_id"])


@bp.route("/rmd/blocking-disputes/<dispute_id>/resolve", methods=["POST"])
@auth.require(auth.FRAUD_ANALYST)
def resolve_dispute(dispute_id):
    data = valid.body()
    outcome = valid.req_enum(data, "outcome", OUTCOMES)
    note = valid.req_str(data, "resolution_note")
    row = load_dispute(dispute_id)
    event = db.blocking_events.get(row["blocking_event_id"])
    if event is not None and auth.acting_id() == event["blocked_by_user_id"]:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The blocking analyst may not resolve this dispute")
    if row["state"] != "UNDER_REVIEW":
        _bad_dispute_state("Only a dispute UNDER_REVIEW can be resolved")

    now = db.now()
    row["resolution_note"] = note
    row["resolved_at"] = now
    row["resolved_by_user_id"] = auth.acting_id()
    row["resolved_late"] = now > row["resolution_deadline_at"]
    row["state"] = "UPHELD" if outcome == "UPHOLD" else "REVERSED"
    touch(row)

    if event is not None:
        if outcome == "UPHOLD":
            event["status"] = "UPHELD"
            touch(event)
            derive.recompute_provider_by_id(event["provider_id"])
        else:
            _reverse_block(row, event)
    return envelope.ok(ser.dispute(row))


@bp.route("/rmd/blocking-disputes/<dispute_id>/withdraw", methods=["POST"])
@auth.require(auth.CALLER)
def withdraw_dispute(dispute_id):
    row = load_dispute(dispute_id)
    auth.own_customer(row["customer_id"])
    if row["state"] != "FILED":
        _bad_dispute_state("Only a FILED dispute can be withdrawn")
    row["state"] = "WITHDRAWN"
    row["resolved_at"] = db.now()
    touch(row)
    return envelope.ok(ser.dispute(row))


@bp.route("/rmd/blocking-disputes/<dispute_id>", methods=["GET"])
@auth.require(*DISPUTE_READ_ROLES)
def read_dispute(dispute_id):
    row = load_dispute(dispute_id)
    auth.own(provider_id=auth.dispute_provider_id(row),
             customer_id=row["customer_id"])
    return envelope.ok(ser.dispute(row))


@bp.route("/rmd/blocking-disputes", methods=["GET"])
@auth.require(*DISPUTE_READ_ROLES)
def list_disputes():
    limit, offset = envelope.pagination()
    event_id = valid.arg_str("blocking_event_id")
    customer_id = valid.arg_str("customer_id")
    state = valid.arg_enum("state", DISPUTE_STATES)

    rows = auth.scope_rows(db.disputes.values(),
                           provider_of=auth.dispute_provider_id,
                           customer_of=lambda r: r["customer_id"])
    if event_id is not None:
        rows = [r for r in rows if r["blocking_event_id"] == event_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return envelope.collection(rows, ser.dispute, limit, offset)

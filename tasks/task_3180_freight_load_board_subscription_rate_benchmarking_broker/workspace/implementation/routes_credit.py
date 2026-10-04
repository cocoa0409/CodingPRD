from datetime import timedelta

from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    check_org_active,
    get_broker,
    get_carrier,
    get_credit_event,
    get_dispute,
    new_resource,
    paginate,
    parse_limit_offset,
    recompute_broker_credit,
    require_fields,
    require_int,
    require_positive_int,
    sorted_by_created,
    suspend_broker,
    touch,
)
from util import DISPUTE_WINDOW_DAYS, iso_ms, parse_dt

bp = Blueprint("credit", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


@bp.post("/credit-report-events")
def create_credit_event():
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["broker_org_id", "invoice_amount_cents", "days_to_pay"])
    carrier = get_carrier(db, user_id)
    broker = get_broker(db, body["broker_org_id"])
    require_positive_int(body["invoice_amount_cents"], "invoice_amount_cents")
    require_int(body["days_to_pay"], "days_to_pay")
    if body["days_to_pay"] < 0:
        raise APIError("ERR_INVALID_REQUEST", 400, "days_to_pay must be non-negative")
    ev = new_resource(db, {
        "broker_org_id": broker["id"],
        "carrier_org_id": carrier["id"],
        "invoice_amount_cents": body["invoice_amount_cents"],
        "days_to_pay": body["days_to_pay"],
        "reported_at": iso_ms(db.clock),
        "status": "PUBLISHED",
    })
    db.credit_report_events[ev["id"]] = ev
    recompute_broker_credit(db, broker)
    touch(db, broker)
    return success(ev, 201)


@bp.get("/credit-report-events")
def list_credit_events():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.credit_report_events.values())
    for f in ("broker_org_id", "carrier_org_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/credit-report-events/<event_id>")
def get_credit_event_route(event_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(get_credit_event(db, event_id))


@bp.post("/credit-report-events/<event_id>/disputes")
def file_dispute(event_id):
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin",))
    ev = get_credit_event(db, event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["reason"])
    broker = get_broker(db, user_id)
    if ev["status"] != "PUBLISHED":
        raise APIError("ERR_CREDIT_EVENT_NOT_PUBLISHED", 409, "Event is not PUBLISHED")
    if ev["broker_org_id"] != broker["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting broker is not the broker named on the event")
    reported = parse_dt(ev["reported_at"])
    if reported is not None and db.clock > reported + timedelta(days=DISPUTE_WINDOW_DAYS):
        raise APIError("ERR_DISPUTE_WINDOW_EXPIRED", 422, "Dispute filed more than 90 days after reported_at")
    dispute = new_resource(db, {
        "credit_report_event_id": ev["id"],
        "reason": body["reason"],
        "rebuttal_count": 0,
        "status": "FILED",
    })
    db.credit_disputes[dispute["id"]] = dispute
    ev["status"] = "UNDER_DISPUTE"
    touch(db, ev)
    recompute_broker_credit(db, broker)
    touch(db, broker)
    return success(dispute, 201)


@bp.get("/credit-disputes")
def list_disputes():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.credit_disputes.values())
    for f in ("credit_report_event_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if d.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/credit-disputes/<dispute_id>")
def get_dispute_route(dispute_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(get_dispute(db, dispute_id))


@bp.post("/credit-disputes/<dispute_id>/start-review")
def start_review(dispute_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    d = get_dispute(db, dispute_id)
    if d["status"] not in ("FILED", "REBUTTED"):
        raise APIError("ERR_DISPUTE_INVALID_STATE", 409, "Dispute cannot move to UNDER_REVIEW from its current state")
    d["status"] = "UNDER_REVIEW"
    touch(db, d)
    return success(d)


@bp.post("/credit-disputes/<dispute_id>/rebut")
def rebut(dispute_id):
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin",))
    d = get_dispute(db, dispute_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["rebuttal_note"])
    broker = get_broker(db, user_id)
    ev = get_credit_event(db, d["credit_report_event_id"])
    if d["status"] != "UNDER_REVIEW":
        raise APIError("ERR_DISPUTE_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW")
    if ev["broker_org_id"] != broker["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting broker is not the broker named on the disputed event")
    if d["rebuttal_count"] >= 2:
        raise APIError("ERR_REBUTTAL_LIMIT_EXCEEDED", 409, "rebuttal_count already 2")
    d["rebuttal_count"] += 1
    d["status"] = "REBUTTED"
    touch(db, d)
    return success(d)


@bp.post("/credit-disputes/<dispute_id>/resolve")
def resolve(dispute_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    d = get_dispute(db, dispute_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("SUSTAIN", "REMOVE"):
        raise APIError("ERR_INVALID_REQUEST", 400, "outcome must be SUSTAIN or REMOVE")
    if d["status"] not in ("FILED", "UNDER_REVIEW", "REBUTTED"):
        raise APIError("ERR_DISPUTE_INVALID_STATE", 409, "Dispute cannot be resolved from its current state")
    ev = get_credit_event(db, d["credit_report_event_id"])
    broker = get_broker(db, ev["broker_org_id"])
    if outcome == "SUSTAIN":
        d["status"] = "RESOLVED_SUSTAIN"
        ev["status"] = "PUBLISHED"
    else:
        d["status"] = "RESOLVED_REMOVE"
        ev["status"] = "REMOVED"
    touch(db, d)
    touch(db, ev)
    recompute_broker_credit(db, broker)
    touch(db, broker)
    if outcome == "REMOVE" and broker["credit_score"] < 40 and broker["status"] == "ACTIVE":
        suspend_broker(db, broker, credit=True)
    return success(d)

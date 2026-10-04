"""Complaints: intake, forwarding, the response cycle, and reopen (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import web
from constants import (
    ALL_ROLES,
    COMPLAINT_CATEGORIES,
    REBUTTAL_CAP,
    REOPEN_WINDOW_DAYS,
    RESPONSE_KINDS,
    RESPONSE_WINDOW_SECONDS,
    ROLE_BUSINESS_REP,
    ROLE_BUREAU_ADMIN,
    ROLE_CONSUMER,
)
from errors import ApiError
from routes_core import get_business_or_404, serialize_business  # noqa: F401

bp = Blueprint("complaints", __name__)


def get_complaint_or_404(complaint_id):
    complaint = db.STORE.complaints.get(complaint_id)
    if complaint is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND")
    return complaint


def serialize_complaint(complaint):
    return db.serialize(complaint)


# ---------------------------------------------------------------------------
# POST /complaints
# ---------------------------------------------------------------------------
@bp.route("/complaints", methods=["POST"])
def create_complaint():
    user_id, role = web.authz({ROLE_CONSUMER})
    data = web.body()
    # priority 3: ownership on the payload consumer id
    consumer_id = data.get("consumer_id")
    if consumer_id is not None and consumer_id != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 4: body-id existence
    if consumer_id is not None and consumer_id not in db.STORE.consumers:
        raise ApiError("ERR_CONSUMER_NOT_FOUND")
    business_id = data.get("business_id")
    if business_id is not None and business_id not in db.STORE.businesses:
        raise ApiError("ERR_BUSINESS_NOT_FOUND")
    # priority 5: schema
    web.require_fields(data, "consumer_id", "business_id")
    category = web.require_enum(data, "category", COMPLAINT_CATEGORIES)
    description = web.require_string(data, "description")

    business = db.STORE.businesses[business_id]
    complaint = db.new_entity(
        "complaints",
        {
            "consumer_id": consumer_id,
            "business_id": business_id,
            "category": category,
            "description": description,
            "status": "RECEIVED",
            "filed_at": db.now(),
            "forwarded_at": None,
            "response_deadline_at": None,
            "last_unresolved_at": None,
            "resolution_outcome": None,
            "rebuttal_count": 0,
            "reopen_count": 0,
            "closed_at": None,
            "responses": [],
        },
    )
    # side effect: Business.complaints_open_count += 1 (live-derived value;
    # the noted counter change bumps the business) and the consumer's
    # complaints_filed_count reflects the new row
    db.touch(business)
    consumer = db.STORE.consumers.get(consumer_id)
    if consumer is not None:
        db.touch(consumer)
    return web.success_object(serialize_complaint(complaint), status=201)


# ---------------------------------------------------------------------------
# GET /complaints/{id}
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    web.authz(ALL_ROLES)
    complaint = get_complaint_or_404(complaint_id)
    return web.success_object(serialize_complaint(complaint), status=200)


# ---------------------------------------------------------------------------
# GET /complaints
# ---------------------------------------------------------------------------
@bp.route("/complaints", methods=["GET"])
def list_complaints():
    web.authz(ALL_ROLES)
    business_id = request.args.get("business_id")
    consumer_id = request.args.get("consumer_id")
    status = request.args.get("status")
    items = list(db.STORE.complaints.values())
    if business_id is not None:
        items = [c for c in items if c["business_id"] == business_id]
    if consumer_id is not None:
        items = [c for c in items if c["consumer_id"] == consumer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return web.paginated_entities(items, serialize_complaint)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/forward
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/forward", methods=["POST"])
def forward_complaint(complaint_id):
    web.authz({ROLE_BUREAU_ADMIN})
    complaint = get_complaint_or_404(complaint_id)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE")
    now = db.now()
    complaint["status"] = "FORWARDED"
    complaint["forwarded_at"] = now
    complaint["response_deadline_at"] = now + timedelta(
        seconds=RESPONSE_WINDOW_SECONDS
    )
    db.touch(complaint)
    return web.success_object(serialize_complaint(complaint), status=200)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/responses
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/responses", methods=["POST"])
def append_response(complaint_id):
    user_id, role = web.authz({ROLE_BUSINESS_REP, ROLE_CONSUMER})
    complaint = get_complaint_or_404(complaint_id)
    data = web.body()
    # priority 5: schema
    kind = web.require_enum(data, "kind", RESPONSE_KINDS)
    response_body = web.require_string(data, "body")
    # kind-level authorization: BUSINESS_RESPONSE is the BusinessRep verb,
    # the CONSUMER_* kinds belong to the filing Consumer
    if kind == "BUSINESS_RESPONSE" and role != ROLE_BUSINESS_REP:
        raise ApiError("ERR_UNAUTHORIZED")
    if kind != "BUSINESS_RESPONSE" and role != ROLE_CONSUMER:
        raise ApiError("ERR_UNAUTHORIZED")
    # priority 3: ownership
    if role == ROLE_BUSINESS_REP and user_id != complaint["business_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    if role == ROLE_CONSUMER and user_id != complaint["consumer_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")

    now = db.now()
    status = complaint["status"]
    business = db.STORE.businesses.get(complaint["business_id"])

    if kind == "BUSINESS_RESPONSE":
        # priority 7 then 10: from-state, then the inclusive response window
        if status not in ("FORWARDED", "CONSUMER_REBUTTED"):
            raise ApiError("ERR_COMPLAINT_INVALID_STATE")
        deadline = complaint["response_deadline_at"]
        if deadline is not None and now > deadline:
            raise ApiError("ERR_RESPONSE_WINDOW_EXPIRED")
        on_time = deadline is None or now <= deadline
        complaint["responses"].append(
            {
                "kind": kind,
                "body": response_body,
                "received_at": now,
                "on_time": on_time,
            }
        )
        complaint["status"] = "RESPONSE_RECEIVED"
        db.touch(complaint)
        return web.success_object(serialize_complaint(complaint), status=201)

    # consumer-side kinds all require RESPONSE_RECEIVED
    if status != "RESPONSE_RECEIVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE")

    if kind == "CONSUMER_REBUTTAL":
        if complaint["rebuttal_count"] >= REBUTTAL_CAP:
            raise ApiError("ERR_REBUTTAL_LIMIT_REACHED")
        complaint["rebuttal_count"] += 1
        complaint["responses"].append(
            {"kind": kind, "body": response_body, "received_at": now, "on_time": True}
        )
        complaint["status"] = "CONSUMER_REBUTTED"
        db.touch(complaint)
        return web.success_object(serialize_complaint(complaint), status=201)

    if kind == "CONSUMER_ACCEPT":
        complaint["responses"].append(
            {"kind": kind, "body": response_body, "received_at": now, "on_time": True}
        )
        complaint["status"] = "RESOLVED"
        complaint["resolution_outcome"] = "CONSUMER_ACCEPTED"
        complaint["closed_at"] = now
        db.touch(complaint)
        # side effects: counter rebalance + provisional regeneration
        if business is not None:
            domain.regenerate_provisional(business)
        return web.success_object(serialize_complaint(complaint), status=201)

    # CONSUMER_REJECT
    complaint["responses"].append(
        {"kind": kind, "body": response_body, "received_at": now, "on_time": True}
    )
    complaint["status"] = "UNRESOLVED"
    complaint["resolution_outcome"] = "CONSUMER_REJECTED"
    # stamped on the FIRST entry into UNRESOLVED only; later returns
    # (mediation decline/expiry, repeat cycles) never refresh it
    if complaint["last_unresolved_at"] is None:
        complaint["last_unresolved_at"] = now
    db.touch(complaint)
    if business is not None:
        domain.regenerate_provisional(business)
    return web.success_object(serialize_complaint(complaint), status=201)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/reopen
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/reopen", methods=["POST"])
def reopen_complaint(complaint_id):
    web.authz({ROLE_BUREAU_ADMIN})
    complaint = get_complaint_or_404(complaint_id)
    # priority 7: from-state
    if complaint["status"] not in ("RESOLVED", "UNANSWERED"):
        raise ApiError("ERR_COMPLAINT_INVALID_STATE")
    # priority 10: reopen window
    now = db.now()
    closed_at = complaint["closed_at"]
    if closed_at is None or now > closed_at + timedelta(days=REOPEN_WINDOW_DAYS):
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED")
    complaint["reopen_count"] += 1
    complaint["resolution_outcome"] = None
    complaint["closed_at"] = None
    complaint["forwarded_at"] = now
    complaint["response_deadline_at"] = now + timedelta(
        seconds=RESPONSE_WINDOW_SECONDS
    )
    complaint["status"] = "FORWARDED"
    db.touch(complaint)
    business = db.STORE.businesses.get(complaint["business_id"])
    if business is not None:
        domain.regenerate_provisional(business)
    return web.success_object(serialize_complaint(complaint), status=200)

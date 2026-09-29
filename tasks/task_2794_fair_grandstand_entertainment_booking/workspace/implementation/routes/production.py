"""The production advance and its rider lines (PRD section 3.8)."""

import ledgers
import lookup
import schema
from authz import ROLE_FAIR_OPS, ROLE_PRODUCTION, ROLE_SETTLEMENT, ROLE_TALENT_BUYER, roles
from db import db, new_id, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint
from response import collection, object_response
from routes.bookings import require_booking_status

bp = Blueprint("production", __name__)

READ_ROLES = (ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_PRODUCTION, ROLE_SETTLEMENT)


def require_advance_status(advance, allowed):
    if advance.get("status") not in allowed:
        raise ApiError("ERR_INVALID_ADVANCE_STATE")


def booking_of_advance(advance):
    return db.bookings.get(advance.get("booking_id"))


def advance_of_item(item):
    return db.advances.get(item.get("production_advance_id"))


def seed_rider_item(advance_id):
    """The critical STAGING line born with the advance, identified by creation order."""
    items = ledgers.rider_items_of_advance(advance_id)
    for item in items:
        if item.get("category") == "STAGING" and item.get("is_critical"):
            return item
    return items[0] if items else None


# ---------------------------------------------------------------------------
# advances
# ---------------------------------------------------------------------------

@bp.get("/production-advances/<identifier>")
@roles(*READ_ROLES)
def read_advance(identifier):
    return object_response(public(lookup.get_advance(identifier)))


@bp.get("/production-advances")
@roles(*READ_ROLES)
def list_advances():
    limit, offset = schema.pagination()
    booking_id = schema.q_str("booking_id")
    status = schema.q_enum("status", schema.ADVANCE_STATUSES)
    if booking_id is not None:
        lookup.get_booking(booking_id)
    rows = []
    for advance in db.advances.values():
        if booking_id is not None and advance.get("booking_id") != booking_id:
            continue
        if status is not None and advance.get("status") != status:
            continue
        rows.append(advance)
    return collection(rows, limit, offset)


@bp.post("/production-advances/<identifier>/complete")
@roles(ROLE_PRODUCTION)
def complete_advance(identifier):
    advance = lookup.get_advance(identifier)
    require_advance_status(advance, ("ADVANCE_IN_REVIEW",))

    items = ledgers.rider_items_of_advance(advance["id"])
    for item in items:
        if item.get("status") == "REQUESTED":
            raise ApiError("ERR_ADVANCE_HAS_OPEN_ITEMS")
    seed = seed_rider_item(advance["id"])
    if seed is not None and seed.get("status") not in ("APPROVED", "SUBSTITUTED"):
        raise ApiError("ERR_ADVANCE_HAS_OPEN_ITEMS")

    advance["status"] = "ADVANCE_COMPLETE"
    advance["blocked_reason_code"] = None
    ledgers.recompute_advance_ledgers(advance)
    touch(advance)
    return object_response(public(advance), 200)


# ---------------------------------------------------------------------------
# rider lines
# ---------------------------------------------------------------------------

@bp.post("/production-advances/<identifier>/rider-items")
@roles(ROLE_PRODUCTION)
def create_rider_item(identifier):
    payload = schema.body()
    category = schema.f_enum(payload, "category", schema.RIDER_CATEGORIES)
    description = schema.f_str(payload, "description")
    requested_cost_cents = schema.f_cents(payload, "requested_cost_cents")
    is_critical = schema.f_bool(payload, "is_critical", default=False)
    artist_recoupable = schema.f_bool(payload, "artist_recoupable", default=False)

    advance = lookup.get_advance(identifier)
    booking = booking_of_advance(advance)
    if booking is None:
        raise ApiError("ERR_SHOW_BOOKING_NOT_FOUND")
    require_booking_status(booking, ("DATE_HELD", "ANNOUNCED"))
    require_advance_status(
        advance, ("ADVANCE_PENDING", "ADVANCE_IN_REVIEW", "ADVANCE_BLOCKED")
    )

    record = {
        "id": new_id(),
        "production_advance_id": advance["id"],
        "category": category,
        "description": description,
        "requested_cost_cents": requested_cost_cents,
        "is_critical": bool(is_critical),
        "artist_recoupable": bool(artist_recoupable),
        "status": "REQUESTED",
        "approved_cost_cents": 0,
    }
    stamp_new(record)
    db.rider_items[record["id"]] = record

    if advance.get("status") == "ADVANCE_PENDING":
        advance["status"] = "ADVANCE_IN_REVIEW"
    touch(advance)
    return object_response(public(record), 201)


@bp.get("/production-advances/<identifier>/rider-items")
@roles(*READ_ROLES)
def list_rider_items(identifier):
    limit, offset = schema.pagination()
    category = schema.q_enum("category", schema.RIDER_CATEGORIES)
    status = schema.q_enum("status", schema.RIDER_STATUSES)
    advance = lookup.get_advance(identifier)
    rows = []
    for item in ledgers.rider_items_of_advance(advance["id"]):
        if category is not None and item.get("category") != category:
            continue
        if status is not None and item.get("status") != status:
            continue
        rows.append(item)
    return collection(rows, limit, offset)


@bp.get("/rider-items/<identifier>")
@roles(*READ_ROLES)
def read_rider_item(identifier):
    return object_response(public(lookup.get_rider_item(identifier)))


@bp.post("/rider-items/<identifier>/rule")
@roles(ROLE_PRODUCTION)
def rule_rider_item(identifier):
    payload = schema.body()
    decision = schema.f_enum(payload, "decision", schema.DECISIONS)
    substituted_cost_cents = schema.f_cents(payload, "substituted_cost_cents", default=None)
    if decision == "SUBSTITUTED" and substituted_cost_cents is None:
        schema.bad("substituted_cost_cents is required when decision is SUBSTITUTED.")

    item = lookup.get_rider_item(identifier)
    advance = advance_of_item(item)
    if advance is None:
        raise ApiError("ERR_PRODUCTION_ADVANCE_NOT_FOUND")
    require_advance_status(advance, ("ADVANCE_IN_REVIEW", "ADVANCE_BLOCKED"))

    if decision == "SUBSTITUTED":
        if substituted_cost_cents > int(item.get("requested_cost_cents", 0)):
            schema.bad("substituted_cost_cents must not exceed requested_cost_cents.")

    was = item.get("status")
    critical = bool(item.get("is_critical"))
    if decision == "APPROVED":
        item["approved_cost_cents"] = int(item.get("requested_cost_cents", 0))
    elif decision == "SUBSTITUTED":
        item["approved_cost_cents"] = int(substituted_cost_cents)
    else:
        item["approved_cost_cents"] = 0
    item["status"] = decision
    touch(item)

    if decision == "DENIED" and critical and was == "REQUESTED":
        advance["status"] = "ADVANCE_BLOCKED"
        advance["blocked_reason_code"] = "DENIED_CRITICAL_ITEM"
    elif (
        decision == "SUBSTITUTED"
        and critical
        and was == "DENIED"
        and advance.get("status") == "ADVANCE_BLOCKED"
    ):
        advance["status"] = "ADVANCE_IN_REVIEW"
        advance["blocked_reason_code"] = None

    ledgers.recompute_advance_ledgers(advance)
    touch(advance)
    return object_response(public(item), 200)

"""Deliverable scheduling, submission and the approval cascade."""

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import ALL_ROLES, require
from envelope import created, ok, paginated, read_pagination
from errors import ApiError
from store import db, new_record, touch
from validation import parse_datetime

bp = Blueprint("deliverables", __name__)

MISMATCH = "ERR_BOOKING_ENGAGEMENT_MISMATCH"


@bp.post("/deliverables")
def create_deliverable():
    require("TalentAgent")
    payload = V.body()
    engagement_id = V.id_field(payload, "engagement_id")
    dtype = V.enum_field(payload, "type", calc.DELIVERABLE_TYPES)
    due_raw, _due = V.date_field(payload, "due_date")
    disclosure_required = V.bool_field(payload, "disclosure_required", required=False, default=True)
    booking_id = V.id_field(payload, "booking_id", required=False)
    production_slot_id = V.id_field(payload, "production_slot_id", required=False)
    shoot_start_raw, shoot_start = V.datetime_field(payload, "shoot_start_at", required=False)
    shoot_end_raw, shoot_end = V.datetime_field(payload, "shoot_end_at", required=False)
    if shoot_start is not None and shoot_end is not None and shoot_end <= shoot_start:
        V.bad("shoot_end_at must be strictly after shoot_start_at")

    engagement = domain.must_get("engagements", engagement_id)
    booking = domain.must_get("appearance_bookings", booking_id) if booking_id else None
    slot = domain.must_get("production_slots", production_slot_id) if production_slot_id else None

    if engagement["contract_status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "engagement is not open for deliverables")

    # Reference coherence, unforgiving per deliverable type.
    if dtype == "APPEARANCE":
        if booking is None or production_slot_id or shoot_start_raw or shoot_end_raw:
            raise ApiError(MISMATCH, "an APPEARANCE deliverable carries only a booking_id")
        if booking["engagement_id"] != engagement_id:
            raise ApiError(MISMATCH, "the booking belongs to another engagement")
    elif dtype == "SHOOT":
        if slot is None or shoot_start_raw is None or shoot_end_raw is None or booking_id:
            raise ApiError(MISMATCH, "a SHOOT deliverable carries a slot and a shoot window")
    else:
        if booking_id or production_slot_id or shoot_start_raw or shoot_end_raw:
            raise ApiError(MISMATCH, "a SOCIAL_POST deliverable carries no references")

    if dtype == "SHOOT":
        window_start = parse_datetime(slot["window_start_at"], "window_start_at")
        window_end = parse_datetime(slot["window_end_at"], "window_end_at")
        if shoot_start < window_start or shoot_end > window_end:
            raise ApiError("ERR_SLOT_WINDOW_VIOLATION",
                           "the reservation falls outside the slot window")
        if domain.slot_capacity_exceeded(slot, shoot_start, shoot_end):
            raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED", "the slot capacity would be exceeded")

    deliverable = new_record({
        "engagement_id": engagement_id,
        "type": dtype,
        "due_date": due_raw,
        "booking_id": booking_id,
        "production_slot_id": production_slot_id,
        "shoot_start_at": shoot_start_raw,
        "shoot_end_at": shoot_end_raw,
        "disclosure_required": disclosure_required,
        "asset_url": None,
        "weight": calc.DELIVERABLE_WEIGHT[dtype],
        "line_value_cents": None,
        "revision_count": 0,
        "status": "PENDING",
    })
    db.deliverables[deliverable["id"]] = deliverable

    if dtype == "SHOOT":
        domain.refresh_reserved_count(slot)
        touch(slot)

    return created(deliverable)


@bp.get("/deliverables/<deliverable_id>")
def get_deliverable(deliverable_id):
    require(ALL_ROLES)
    return ok(domain.must_get("deliverables", deliverable_id))


@bp.get("/deliverables")
def list_deliverables():
    require(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.deliverables.values())
    for field in ("engagement_id", "booking_id", "production_slot_id", "status", "type"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    return paginated(rows, limit, offset)


@bp.post("/deliverables/<deliverable_id>/submit")
def submit_deliverable(deliverable_id):
    caller = require("Athlete")
    deliverable = domain.must_get("deliverables", deliverable_id)
    payload = V.body()
    asset_url = V.str_field(payload, "asset_url")

    engagement = db.engagements[deliverable["engagement_id"]]
    if caller.user_id != engagement["athlete_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the athlete on this engagement")

    if engagement["contract_status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "engagement is not ACTIVE")
    if deliverable["status"] not in ("PENDING", "REVISION_REQUESTED"):
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE", "deliverable cannot be submitted")

    deliverable["asset_url"] = asset_url
    deliverable["status"] = "SUBMITTED"
    touch(deliverable)
    return ok(deliverable)


@bp.post("/deliverables/<deliverable_id>/review")
def review_deliverable(deliverable_id):
    caller = require("BrandRep")
    deliverable = domain.must_get("deliverables", deliverable_id)
    payload = V.body()
    decision = V.enum_field(payload, "decision", calc.REVIEW_DECISIONS)
    V.str_field(payload, "revision_note", required=False)

    engagement = db.engagements[deliverable["engagement_id"]]
    if caller.user_id != engagement["brand_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the brand on this engagement")

    if engagement["contract_status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "engagement is not ACTIVE")
    if deliverable["status"] != "SUBMITTED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE", "deliverable is not SUBMITTED")

    if decision == "REQUEST_REVISION":
        deliverable["status"] = "REVISION_REQUESTED"
        deliverable["revision_count"] += 1
        touch(deliverable)
        return ok(deliverable)

    if deliverable["disclosure_required"]:
        compliant = [r for r in domain.deliverable_disclosures(deliverable["id"])
                     if r["status"] == "COMPLIANT"]
        if not compliant:
            raise ApiError("ERR_DISCLOSURE_NOT_COMPLIANT",
                           "no COMPLIANT disclosure record on file for this deliverable")

    deliverable["status"] = "APPROVED"
    touch(deliverable)

    domain.refresh_approved_deliverable_count(engagement)
    contract_changed = False
    if engagement["approved_deliverable_count"] >= engagement["required_deliverable_count"]:
        engagement["contract_status"] = "COMPLETED"
        domain.open_settlement(engagement)
        contract_changed = True
    touch(engagement)
    if contract_changed:
        domain.sync_athlete_after_contract_change(engagement)
    return ok(deliverable)


@bp.get("/deliverables/<deliverable_id>/disclosure-records")
def list_deliverable_disclosures(deliverable_id):
    require(ALL_ROLES)
    deliverable = domain.must_get("deliverables", deliverable_id)
    limit, offset = read_pagination()
    rows = domain.deliverable_disclosures(deliverable["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, limit, offset)

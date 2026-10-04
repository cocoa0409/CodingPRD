"""Complaint routes."""
from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_STATE, not_found
from middleware import require_roles
from response import success
from services.helpers import (
    body_json, require_fields, require_string, require_enum, stamp_common, touch,
    parse_clock,
)
from services.calculations import complaint_weighted_score
from services.cascades import maybe_suspend_or_revoke

bp = Blueprint("complaints", __name__)

CATEGORIES = ("WORKMANSHIP", "COMMUNICATION", "PROPERTY_DAMAGE", "CONTRACT_DISPUTE")


@bp.post("/program/complaints")
def create_complaint():
    require_roles("Claimant", "ProgramAdmin")
    data = body_json()
    require_fields(data, ["contractor_id", "category"])
    contractor_id = require_string(data, "contractor_id")
    category = require_enum(data, "category", CATEGORIES)
    with db.lock:
        contractor = db.contractors.get(contractor_id)
        if contractor is None:
            raise not_found("Contractor")
        comp = stamp_common({
            "contractor_id": contractor_id,
            "category": category,
            "filed_at": db.clock,
            "substantiated_at": None,
            "status": "FILED",
        })
        db.complaints[comp["id"]] = comp
    return success(comp, status=201)


@bp.post("/program/complaints/<cid>/substantiate")
def substantiate_complaint(cid):
    require_roles("ProgramAdmin")
    with db.lock:
        comp = db.complaints.get(cid)
        if comp is None:
            raise not_found("Complaint")
        if comp["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, 409, "Complaint is not FILED")
        contractor = db.contractors.get(comp["contractor_id"])
        comp["status"] = "SUBSTANTIATED"
        comp["substantiated_at"] = db.clock
        touch(comp)
        # standing recompute, in order: workmanship -5, lifetime +1, weighted recompute
        contractor["workmanship_score"] = max(0, contractor["workmanship_score"] - 5)
        contractor["lifetime_substantiated_count"] += 1
        clock_dt = parse_clock(db.clock)
        contractor["complaint_score_24mo"] = complaint_weighted_score(
            db, contractor["id"], clock_dt
        )
        touch(contractor)
        maybe_suspend_or_revoke(db, contractor)
    return success(comp)


@bp.post("/program/complaints/<cid>/dismiss")
def dismiss_complaint(cid):
    require_roles("ProgramAdmin")
    with db.lock:
        comp = db.complaints.get(cid)
        if comp is None:
            raise not_found("Complaint")
        if comp["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, 409, "Complaint is not FILED")
        comp["status"] = "DISMISSED"
        touch(comp)
    return success(comp)

from flask import Blueprint

import constants as C
import validators as V
from auth import authorize
from domain import (
    apply_changes, audit_score, serialize_subcontractor, subcontractor_terminate_cascade,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import db, new_record, ordered, require

bp = Blueprint("subcontractors", __name__)


@bp.post("/subcontractors")
def create_subcontractor():
    authorize([C.ROLE_STATION_MANAGER])
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    legal_name = V.req_string(payload, "legal_name")
    parent_id = V.opt_string(payload, "parent_subcontractor_id")

    station = require(db.stations, station_id, "Station")
    parent = None
    if parent_id is not None:
        parent = require(db.subcontractors, parent_id, "Subcontractor")
        if parent["station_id"] != station["id"]:
            raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    sub = new_record("Subcontractor", {
        "station_id": station["id"],
        "parent_subcontractor_id": parent["id"] if parent else None,
        "legal_name": legal_name,
        "tier": "TIER_2" if parent else "TIER_1",
        "status": "PENDING_VETTING",
    })
    db.subcontractors[sub["id"]] = sub
    return respond_object(serialize_subcontractor(sub), 201)


@bp.get("/subcontractors/<subcontractor_id>")
def read_subcontractor(subcontractor_id):
    authorize(C.ALL_ROLES)
    sub = require(db.subcontractors, subcontractor_id, "Subcontractor")
    return respond_object(serialize_subcontractor(sub))


@bp.get("/subcontractors")
def list_subcontractors():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.subcontractors.values(), {
        "station_id": "station_id",
        "parent_subcontractor_id": "parent_subcontractor_id",
        "status": "status",
    })
    return paginate(ordered(records), serialize_subcontractor)


@bp.post("/subcontractors/<subcontractor_id>/oversight-decisions")
def subcontractor_oversight(subcontractor_id):
    authorize([C.ROLE_STATION_MANAGER])
    sub = require(db.subcontractors, subcontractor_id, "Subcontractor")
    payload = V.body()
    decision = V.req_enum(payload, "decision", C.SUBCONTRACTOR_DECISIONS)
    V.opt_string(payload, "note")

    status = sub["status"]
    if decision == "APPROVE":
        if status != "PENDING_VETTING":
            raise ApiError("ERR_INVALID_STATE")
        if sub["tier"] == "TIER_2":
            parent = db.subcontractors.get(sub["parent_subcontractor_id"])
            if parent is None or parent["status"] != "APPROVED":
                raise ApiError("ERR_SUBCONTRACTOR_NOT_APPROVED")
        apply_changes(sub, {"status": "APPROVED"})
    elif decision == "PLACE_ON_PROBATION":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(sub, {"status": "PROBATION"})
    elif decision == "REINSTATE":
        if status != "PROBATION":
            raise ApiError("ERR_INVALID_STATE")
        if audit_score(sub) < C.REINSTATE_MIN_AUDIT_SCORE:
            raise ApiError("ERR_INVALID_STATE", "audit_compliance_score is below 40.00.")
        apply_changes(sub, {"status": "APPROVED"})
    elif decision == "SUSPEND":
        if status not in ("APPROVED", "PROBATION"):
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(sub, {"status": "SUSPENDED"})
    else:  # TERMINATE
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(sub, {"status": "TERMINATED"})
        subcontractor_terminate_cascade(sub)

    return respond_object(serialize_subcontractor(sub))

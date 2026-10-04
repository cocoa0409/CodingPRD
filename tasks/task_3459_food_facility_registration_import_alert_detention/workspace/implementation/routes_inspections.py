"""Foreign facility inspections (PRD section 3.8).

Inspection: SCHEDULED -> COMPLETED (scheduling inspector only) or SCHEDULED ->
REFUSED_BY_FACILITY (the facility itself; fires the three-link cascade:
suspension, for-cause detention of PENDING entries, COMPROMISED notices).
"""
from flask import Blueprint

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, ok_list, json_body
from errors import ApiError
from pagination import page_params, paginate

bp = Blueprint("inspections", __name__)


def _get_inspection_or_404(inspection_id):
    i = db.inspections.get(inspection_id)
    if i is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND")
    return i


@bp.post("/registry/inspections")
@require_roles("FieldInspector")
def create_inspection(caller_id, caller_role):
    body = json_body()
    facility_id = body.get("facility_id")
    facility = db.facilities.get(facility_id) if isinstance(facility_id, str) else None
    # Tier 8: the inspection target must be a FOREIGN facility.
    if facility_id is not None and (
        facility is None or facility["facility_kind"] != "FOREIGN"
    ):
        raise ApiError("ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY")
    start = db.parse_dt(body.get("scheduled_start_at"))
    end = db.parse_dt(body.get("scheduled_end_at"))
    # Tier 9: half-open [start, end) overlap among this inspector's SCHEDULED
    # inspections; adjacency (new start == existing end) is allowed.
    if start is not None and end is not None and end > start:
        for other in db.inspections.values():
            if other["inspector_user_id"] != caller_id or other["status"] != "SCHEDULED":
                continue
            if start < other["scheduled_end_at"] and other["scheduled_start_at"] < end:
                raise ApiError("ERR_INSPECTION_SCHEDULE_OVERLAP")
    # Tier 12: request shape.
    if not isinstance(facility_id, str) or not facility_id:
        raise ApiError("ERR_INVALID_REQUEST", "facility_id is required")
    if start is None or end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_start_at and scheduled_end_at must be ISO-8601 datetimes",
        )
    if not (end > start):
        raise ApiError(
            "ERR_INVALID_REQUEST", "scheduled_end_at must be strictly after scheduled_start_at"
        )

    i = db.new_common()
    i.update(
        {
            "facility_id": facility_id,
            "inspector_user_id": caller_id,
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "status": "SCHEDULED",
            "findings_violation_count": None,
        }
    )
    db.inspections[i["id"]] = i
    return ok(serialize.inspection(i), 201)


@bp.get("/registry/facilities/<fid>/inspections")
@require_roles(*ALL_ROLES)
def list_facility_inspections(fid, caller_id, caller_role):
    if fid not in db.facilities:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    limit, offset = page_params()
    items = sorted(
        (i for i in db.inspections.values() if i["facility_id"] == fid), key=db.sort_key
    )
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.inspection(i) for i in page], total, limit, offset)


@bp.post("/registry/inspections/<iid>/complete")
@require_roles("FieldInspector")
def complete_inspection(iid, caller_id, caller_role):
    # Tier 4: existence.
    i = _get_inspection_or_404(iid)
    # Tier 3: only the scheduling inspector may complete it.
    if i["inspector_user_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only while SCHEDULED.
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_OPEN")
    # Tier 12: findings count must be a non-negative integer.
    findings = json_body().get("findings_violation_count")
    if not services.is_int(findings) or findings < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "findings_violation_count must be an integer >= 0"
        )
    now = db.now()
    i["status"] = "COMPLETED"
    i["findings_violation_count"] = findings
    db.touch(i, now)
    facility = db.facilities.get(i["facility_id"])
    if facility is not None:
        facility["violation_count"] += findings
        db.touch(facility, now)
    return ok(serialize.inspection(i))


@bp.post("/registry/inspections/<iid>/refuse-entry")
@require_roles("FacilityOwner")
def refuse_entry_inspection(iid, caller_id, caller_role):
    # Tier 4: existence.
    i = _get_inspection_or_404(iid)
    # Tier 3: the facility itself records the refusal.
    if i["facility_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only while SCHEDULED.
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_OPEN")

    now = db.now()
    i["status"] = "REFUSED_BY_FACILITY"
    db.touch(i, now)
    facility = db.facilities.get(i["facility_id"])
    facility_id = i["facility_id"]
    # Cascade link 1: REGISTERED facility -> SUSPENDED (an EXPIRED facility
    # stays EXPIRED; links 2 and 3 still fire).
    if facility is not None and facility["registration_status"] == "REGISTERED":
        facility["registration_status"] = "SUSPENDED"
        db.touch(facility, now)
    # Cascade link 2: every PENDING entry of the facility is detained for
    # cause (review_status untouched; detained_under_alert_id null).
    for e in sorted(db.entries.values(), key=db.sort_key):
        if e["facility_id"] == facility_id and e["disposition_status"] == "PENDING":
            services.detain_entry(e, None, now)
    # Cascade link 3: every still-CONFIRMED prior notice becomes COMPROMISED.
    for p in sorted(db.prior_notices.values(), key=db.sort_key):
        if p["facility_id"] == facility_id and p["status"] == "CONFIRMED":
            p["status"] = "COMPROMISED"
            db.touch(p, now)
    return ok(serialize.inspection(i))

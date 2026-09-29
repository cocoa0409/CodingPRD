"""Workers and their credentials."""

from flask import Blueprint

import services as svc
from core import (
    ALL_ROLES,
    all_rows,
    auth,
    bad_window,
    body_dict,
    conflict,
    invalid,
    lookup,
    new_record,
    now,
    pagination,
    q_bool,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
    respond,
    respond_list,
    touch,
    update,
    v_bool,
    v_int,
    v_str,
    MISSING,
)
from serialize import certification_json, cert_status, staff_member_json

bp = Blueprint("workforce", __name__)

EMPLOYMENT_TYPES = ("PART_TIME_EMPLOYEE", "CONTRACTED")
MEMBER_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED", "TERMINATED")
CERT_TYPES = (
    "ACCESSIBILITY_SERVICES",
    "EVACUATION_PROCEDURES",
    "CODE_OF_CONDUCT",
    "ELEVATOR_OPERATION",
)
CERT_STATUSES = ("VALID", "EXPIRED", "REVOKED")

READ_ROLES = (
    "GuestExperienceDirector",
    "StaffingCoordinator",
    "GuestServicesSupervisor",
)

DECLARED_STATUS_MOVES = (
    ("ACTIVE", "PROBATION"),
    ("PROBATION", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("PROBATION", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
)

RELIABILITY_PROBATION_FLOOR = 65


# ---------------------------------------------------------------------------
# staff members
# ---------------------------------------------------------------------------

@bp.post("/staff-members")
def create_staff_member():
    auth("StaffingCoordinator")
    body = body_dict()
    full_name = req_str(body, "full_name")
    employment_type = req_enum(body, "employment_type", EMPLOYMENT_TYPES)
    seniority_date = req_dt(body, "seniority_date")
    rate = req_int(body, "hourly_rate_cents", minimum=0)
    pool = body.get("in_backfill_pool", MISSING)
    pool = True if pool is MISSING else v_bool(pool, "in_backfill_pool")
    row = new_record(
        "staff_members",
        {
            "full_name": full_name,
            "employment_type": employment_type,
            "seniority_date": seniority_date,
            "hourly_rate_cents": rate,
            "in_backfill_pool": pool,
            "status": "ACTIVE",
            "reliability_score": 100,
            "season_reliability_score": 100,
            "no_show_strikes": 0,
            "completed_assignment_count": 0,
            "last_status_reason": None,
        },
    )
    return respond(staff_member_json(row), 201)


@bp.get("/staff-members/<member_id>")
def read_staff_member(member_id):
    auth(*ALL_ROLES)
    return respond(staff_member_json(lookup("staff_members", member_id)))


@bp.get("/staff-members")
def list_staff_members():
    auth(*READ_ROLES)
    status = q_enum("status", MEMBER_STATUSES)
    employment_type = q_enum("employment_type", EMPLOYMENT_TYPES)
    pool = q_bool("in_backfill_pool")
    limit, offset = pagination()
    rows = all_rows("staff_members")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if employment_type is not None:
        rows = [r for r in rows if r["employment_type"] == employment_type]
    if pool is not None:
        rows = [r for r in rows if r["in_backfill_pool"] is pool]
    rows = sorted(rows, key=lambda r: (r["seniority_date"], r["created_at"], r["_seq"]))
    window = rows[offset:offset + limit]
    return respond_list(
        [staff_member_json(r) for r in window], limit, offset, len(rows)
    )


@bp.patch("/staff-members/<member_id>")
def update_staff_member(member_id):
    auth("StaffingCoordinator")
    body = body_dict()
    changes = {}
    if "full_name" in body:
        changes["full_name"] = v_str(body["full_name"], "full_name")
    if "hourly_rate_cents" in body:
        changes["hourly_rate_cents"] = v_int(
            body["hourly_rate_cents"], "hourly_rate_cents", minimum=0
        )
    if "in_backfill_pool" in body:
        changes["in_backfill_pool"] = v_bool(body["in_backfill_pool"], "in_backfill_pool")
    # "status" is deliberately not writable here; it moves only through the
    # dedicated standing action, so it is ignored rather than applied.
    row = lookup("staff_members", member_id)
    # A rate change is forward-looking: no assignment is repriced here.
    if not update(row, **changes):
        touch(row)
    return respond(staff_member_json(row))


@bp.post("/staff-members/<member_id>/status-change")
def change_staff_member_status(member_id):
    auth("StaffingCoordinator")
    body = body_dict()
    target = req_enum(body, "target_status", MEMBER_STATUSES)
    reason = req_str(body, "reason")
    member = lookup("staff_members", member_id)
    current = member["status"]
    if target == current:
        raise invalid("target_status equals the worker's current standing.")
    if current == "TERMINATED":
        raise conflict(
            "ERR_STAFF_MEMBER_NOT_ACTIVE",
            "A TERMINATED worker admits no further standing change.",
        )
    if (current, target) not in DECLARED_STATUS_MOVES:
        raise conflict(
            "ERR_STAFF_MEMBER_NOT_ACTIVE",
            "%s -> %s is not a declared standing transition." % (current, target),
        )
    if (
        current == "PROBATION"
        and target == "ACTIVE"
        and member["reliability_score"] < RELIABILITY_PROBATION_FLOOR
    ):
        raise conflict(
            "ERR_STAFF_MEMBER_NOT_ACTIVE",
            "Reinstatement from PROBATION requires reliability_score >= %d."
            % RELIABILITY_PROBATION_FLOOR,
        )

    changes = {"status": target, "last_status_reason": reason}
    if target == "ACTIVE":
        changes["in_backfill_pool"] = True
    else:
        changes["in_backfill_pool"] = False
    update(member, **changes)
    if target in ("SUSPENDED", "TERMINATED") and current in ("ACTIVE", "PROBATION"):
        svc.remove_member_from_floor(member)
    return respond(staff_member_json(member))


@bp.get("/staff-members/<member_id>/certifications")
def list_member_certifications(member_id):
    auth(*ALL_ROLES)
    status = q_enum("status", CERT_STATUSES)
    limit, offset = pagination()
    member = lookup("staff_members", member_id)
    rows = svc.certs_of_member(member["id"])
    if status is not None:
        rows = [r for r in rows if cert_status(r) == status]
    window = rows[offset:offset + limit]
    return respond_list(
        [certification_json(r) for r in window], limit, offset, len(rows)
    )


# ---------------------------------------------------------------------------
# certifications
# ---------------------------------------------------------------------------

@bp.post("/certifications")
def create_certification():
    auth("StaffingCoordinator")
    body = body_dict()
    member_id = req_str(body, "staff_member_id")
    cert_type = req_enum(body, "cert_type", CERT_TYPES)
    issued_on = req_dt(body, "issued_on")
    expires_on = req_dt(body, "expires_on")
    if expires_on <= issued_on:
        raise bad_window("expires_on must be strictly after issued_on.")
    lookup("staff_members", member_id)
    row = new_record(
        "certifications",
        {
            "staff_member_id": member_id,
            "cert_type": cert_type,
            "issued_on": issued_on,
            "expires_on": expires_on,
            "revoked_at": None,
        },
    )
    return respond(certification_json(row), 201)


@bp.get("/certifications/<cert_id>")
def read_certification(cert_id):
    auth(*ALL_ROLES)
    return respond(certification_json(lookup("certifications", cert_id)))


@bp.get("/certifications")
def list_certifications():
    auth(*ALL_ROLES)
    member_id = q_str("staff_member_id")
    cert_type = q_enum("cert_type", CERT_TYPES)
    status = q_enum("status", CERT_STATUSES)
    limit, offset = pagination()
    rows = all_rows("certifications")
    if member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == member_id]
    if cert_type is not None:
        rows = [r for r in rows if r["cert_type"] == cert_type]
    if status is not None:
        rows = [r for r in rows if cert_status(r) == status]
    window = rows[offset:offset + limit]
    return respond_list(
        [certification_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/certifications/<cert_id>/revoke")
def revoke_certification(cert_id):
    auth("StaffingCoordinator")
    body = body_dict()
    req_str(body, "reason")
    row = lookup("certifications", cert_id)
    # Forward-looking only: no assignment or bid is retro-cancelled.
    if not update(row, revoked_at=now()):
        touch(row)
    return respond(certification_json(row))

"""Routes: facility spaces and reservations."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, require_member_owner, success_object, paginate,
    get_body, require_fields, parse_datetime,
)

bp = Blueprint("facilities", __name__)

SPACE_FIELDS = ["id", "branch_id", "name", "kind", "capacity", "dropin_capacity",
                "created_at", "updated_at", "version"]
RESERVATION_FIELDS = ["id", "space_id", "branch_id", "session_id", "reservation_type",
                      "start_at", "end_at", "buffer_minutes", "renter_member_id",
                      "status", "created_at", "updated_at", "version"]

SPACE_KINDS = {"POOL", "GYM", "STUDIO", "CHILDCARE_ROOM"}
RESERVATION_TYPES = {"PROGRAM", "RENTAL", "MAINTENANCE", "BLACKOUT"}
BUFFER_BY_TYPE = {"PROGRAM": 15, "RENTAL": 30, "MAINTENANCE": 0, "BLACKOUT": 0}
READ_ROLES_SPACE = ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                    "FrontDesk", "Member"]


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@bp.route("/spaces", methods=["POST"])
def create_space():
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin"])
    body = get_body()
    require_fields(body, ["branch_id", "name", "kind", "capacity", "dropin_capacity"])
    if body["branch_id"] not in db.STORES["branches"]:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    if body["kind"] not in SPACE_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid space kind")
    if body["dropin_capacity"] > body["capacity"]:
        raise ApiError("ERR_INVALID_REQUEST", "dropin_capacity cannot exceed capacity")
    rec = db.new_record("spaces", {
        "branch_id": body["branch_id"],
        "name": body["name"],
        "kind": body["kind"],
        "capacity": body["capacity"],
        "dropin_capacity": body["dropin_capacity"],
    })
    return success_object(db.serialize(rec, SPACE_FIELDS), 201)


@bp.route("/spaces/<spaceId>", methods=["GET"])
def get_space(spaceId):
    role, _ = auth()
    require_role(role, READ_ROLES_SPACE)
    rec = db.get("spaces", spaceId)
    return success_object(db.serialize(rec, SPACE_FIELDS))


@bp.route("/spaces", methods=["GET"])
def list_spaces():
    role, _ = auth()
    require_role(role, READ_ROLES_SPACE)
    items = db.all_records("spaces")
    branch_id = request.args.get("branch_id")
    kind = request.args.get("kind")
    if branch_id:
        items = [s for s in items if s["branch_id"] == branch_id]
    if kind:
        items = [s for s in items if s["kind"] == kind]
    return paginate([db.serialize(s, SPACE_FIELDS) for s in items])


@bp.route("/spaces/<spaceId>/reservations", methods=["GET"])
def list_space_reservations(spaceId):
    role, _ = auth()
    require_role(role, READ_ROLES_SPACE)
    db.get("spaces", spaceId)
    items = [r for r in db.all_records("reservations") if r["space_id"] == spaceId]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([db.serialize(r, RESERVATION_FIELDS) for r in items])


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@bp.route("/reservations", methods=["POST"])
def create_reservation():
    role, user_id = auth()
    require_role(role, ["ProgramCoordinator", "BranchDirector", "AssociationAdmin", "Member"])
    body = get_body()
    require_fields(body, ["space_id", "reservation_type", "start_at", "end_at"])
    space = db.STORES["spaces"].get(body["space_id"])
    if space is None:
        raise ApiError("ERR_SPACE_NOT_FOUND", f"Space {body['space_id']} not found")
    rtype = body["reservation_type"]
    if rtype not in RESERVATION_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid reservation_type")
    if rtype == "BLACKOUT" and role != "AssociationAdmin":
        raise ApiError("ERR_UNAUTHORIZED", "BLACKOUT reservations require AssociationAdmin")
    session_id = body.get("session_id")
    if session_id is not None and session_id not in db.STORES["sessions"]:
        raise ApiError("ERR_SESSION_NOT_FOUND", "session_id not found")
    renter_member_id = body.get("renter_member_id")
    if renter_member_id is not None and renter_member_id not in db.STORES["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "renter_member_id not found")
    start_at = parse_datetime(body["start_at"])
    end_at = parse_datetime(body["end_at"])
    if start_at is None or end_at is None or end_at <= start_at:
        raise ApiError("ERR_TIME_RANGE_INVALID", "end_at must be after start_at")
    rec = db.new_record("reservations", {
        "space_id": space["id"],
        "branch_id": space["branch_id"],
        "session_id": session_id,
        "reservation_type": rtype,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "buffer_minutes": BUFFER_BY_TYPE[rtype],
        "renter_member_id": renter_member_id,
        "status": "REQUESTED",
    })
    return success_object(db.serialize(rec, RESERVATION_FIELDS), 201)


@bp.route("/reservations/<reservationId>", methods=["GET"])
def get_reservation(reservationId):
    role, _ = auth()
    require_role(role, READ_ROLES_SPACE)
    rec = db.get("reservations", reservationId)
    return success_object(db.serialize(rec, RESERVATION_FIELDS))


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    role, _ = auth()
    require_role(role, READ_ROLES_SPACE)
    items = db.all_records("reservations")
    for param in ("space_id", "branch_id", "session_id", "renter_member_id", "status"):
        value = request.args.get(param)
        if value:
            items = [r for r in items if r.get(param) == value]
    return paginate([db.serialize(r, RESERVATION_FIELDS) for r in items])


def _buffered(rec):
    start = parse_datetime(rec["start_at"]) - timedelta(minutes=rec["buffer_minutes"])
    end = parse_datetime(rec["end_at"]) + timedelta(minutes=rec["buffer_minutes"])
    return start, end


@bp.route("/reservations/<reservationId>/approve", methods=["POST"])
def approve_reservation(reservationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("reservations", reservationId)
    if rec["status"] in ("DENIED", "CANCELLED", "COMPLETED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Reservation is terminal")
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only REQUESTED reservations can be approved")
    my_start, my_end = _buffered(rec)
    for other in db.STORES["reservations"].values():
        if other["id"] == rec["id"] or other["space_id"] != rec["space_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        o_start, o_end = _buffered(other)
        # touching endpoints allowed: overlap requires strict inequality
        if my_start < o_end and o_start < my_end:
            raise ApiError("ERR_SPACE_CONFLICT",
                           "Reservation overlaps an APPROVED reservation (buffers included)")
    rec["status"] = "APPROVED"
    db.touch(rec, bump=False)
    return success_object(db.serialize(rec, RESERVATION_FIELDS))


@bp.route("/reservations/<reservationId>/deny", methods=["POST"])
def deny_reservation(reservationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("reservations", reservationId)
    if rec["status"] in ("DENIED", "CANCELLED", "COMPLETED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Reservation is terminal")
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only REQUESTED reservations can be denied")
    rec["status"] = "DENIED"
    db.touch(rec, bump=False)
    return success_object(db.serialize(rec, RESERVATION_FIELDS))


@bp.route("/reservations/<reservationId>/cancel", methods=["POST"])
def cancel_reservation(reservationId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "ProgramCoordinator"])
    rec = db.get("reservations", reservationId)
    if rec["status"] in ("DENIED", "CANCELLED", "COMPLETED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Reservation is terminal")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only APPROVED reservations can be cancelled")
    rec["status"] = "CANCELLED"
    db.touch(rec, bump=False)
    return success_object(db.serialize(rec, RESERVATION_FIELDS))

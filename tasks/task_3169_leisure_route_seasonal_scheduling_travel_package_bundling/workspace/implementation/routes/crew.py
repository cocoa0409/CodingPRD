"""Crew: bases, members, assignments."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_enum,
    touch,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate
from routes.flight_instances import _get_flight_or_404

bp = Blueprint("crew", __name__)

CREW_ROLES = {"CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT"}


def _get_base_or_404(base_id):
    return get_or_404(db.crew_bases, base_id, "ERR_CREW_BASE_NOT_FOUND", "CrewBase")


def _get_member_or_404(member_id):
    return get_or_404(
        db.crew_members, member_id, "ERR_CREW_MEMBER_NOT_FOUND", "CrewMember"
    )


def _get_assignment_or_404(assignment_id):
    return get_or_404(
        db.crew_assignments,
        assignment_id,
        "ERR_ASSIGNMENT_NOT_FOUND",
        "CrewAssignment",
    )


@bp.route("/crew-bases", methods=["POST"])
def create_base():
    require_role("CrewScheduler")
    data = body()
    station_id = require_field(data, "base_station_id", str)
    code = require_field(data, "base_code", str)
    if station_id not in db.stations:
        raise ApiError("ERR_STATION_NOT_FOUND", "Station id does not exist", 404)
    ent = new_entity(
        {
            "base_station_id": station_id,
            "base_code": code,
            "base_status": "ACTIVE",
        }
    )
    db.crew_bases[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/crew-bases", methods=["GET"])
def list_bases():
    require_any_authenticated()
    items = list(db.crew_bases.values())
    sid = request.args.get("base_station_id")
    if sid:
        items = [b for b in items if b["base_station_id"] == sid]
    status = request.args.get("base_status")
    if status:
        items = [b for b in items if b["base_status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/crew-bases/<base_id>", methods=["GET"])
def get_base(base_id):
    require_any_authenticated()
    ent = _get_base_or_404(base_id)
    return ok(ent)


@bp.route("/crew-bases/<base_id>/members", methods=["POST"])
def create_member(base_id):
    require_role("CrewScheduler")
    base = _get_base_or_404(base_id)
    data = body()
    emp = require_field(data, "employee_number", str)
    role = require_enum(data, "crew_role", CREW_ROLES)
    ent = new_entity(
        {
            "crew_base_id": base_id,
            "employee_number": emp,
            "crew_role": role,
            "member_status": "ACTIVE",
        }
    )
    db.crew_members[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/crew-bases/<base_id>/members", methods=["GET"])
def list_members_for_base(base_id):
    require_any_authenticated()
    _get_base_or_404(base_id)
    items = [m for m in db.crew_members.values() if m["crew_base_id"] == base_id]
    status = request.args.get("member_status")
    if status:
        items = [m for m in items if m["member_status"] == status]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/crew-members", methods=["GET"])
def list_members_flat():
    require_any_authenticated()
    items = list(db.crew_members.values())
    bid = request.args.get("crew_base_id")
    if bid:
        items = [m for m in items if m["crew_base_id"] == bid]
    status = request.args.get("member_status")
    if status:
        items = [m for m in items if m["member_status"] == status]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/crew-members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_any_authenticated()
    ent = _get_member_or_404(member_id)
    return ok(ent)


@bp.route("/flight-instances/<flight_id>/crew-assignments", methods=["POST"])
def create_assignment(flight_id):
    require_role("CrewScheduler")
    flight = _get_flight_or_404(flight_id)
    data = body()
    member_id = require_field(data, "crew_member_id", str)
    member = db.crew_members.get(member_id)
    if member is None:
        raise ApiError(
            "ERR_CREW_MEMBER_NOT_FOUND", "CrewMember id does not exist", 404
        )
    base = db.crew_bases.get(member["crew_base_id"])
    route = db.routes.get(flight["route_id"])
    if base is None or base["base_station_id"] != route["origin_station_id"]:
        raise ApiError(
            "ERR_CREW_BASE_MISMATCH",
            "Crew member's base station differs from the route origin station",
            422,
        )
    if member["member_status"] != "ACTIVE" or base["base_status"] != "ACTIVE":
        raise ApiError(
            "ERR_CREW_MEMBER_INACTIVE",
            "Crew member or base not ACTIVE",
            422,
        )
    ent = new_entity(
        {
            "flight_instance_id": flight_id,
            "crew_member_id": member_id,
            "assignment_status": "ASSIGNED",
        }
    )
    db.crew_assignments[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/flight-instances/<flight_id>/crew-assignments", methods=["GET"])
def list_assignments_for_flight(flight_id):
    require_any_authenticated()
    _get_flight_or_404(flight_id)
    items = [
        a
        for a in db.crew_assignments.values()
        if a["flight_instance_id"] == flight_id
    ]
    status = request.args.get("assignment_status")
    if status:
        items = [a for a in items if a["assignment_status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route(
    "/flight-instances/<flight_id>/crew-assignments/<assignment_id>",
    methods=["DELETE"],
)
def release_assignment(flight_id, assignment_id):
    require_role("CrewScheduler")
    _get_flight_or_404(flight_id)
    assignment = _get_assignment_or_404(assignment_id)
    if assignment["flight_instance_id"] != flight_id:
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_FOUND", "CrewAssignment id does not exist", 404
        )
    if assignment["assignment_status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ASSIGNED",
            "Release requires ASSIGNED crew assignment",
            409,
        )
    assignment["assignment_status"] = "RELEASED"
    touch(assignment)
    return ok(assignment)


@bp.route("/crew-assignments", methods=["GET"])
def list_assignments_flat():
    require_any_authenticated()
    items = list(db.crew_assignments.values())
    fid = request.args.get("flight_instance_id")
    if fid:
        items = [a for a in items if a["flight_instance_id"] == fid]
    mid = request.args.get("crew_member_id")
    if mid:
        items = [a for a in items if a["crew_member_id"] == mid]
    status = request.args.get("assignment_status")
    if status:
        items = [a for a in items if a["assignment_status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/crew-assignments/<assignment_id>", methods=["GET"])
def get_assignment_flat(assignment_id):
    require_any_authenticated()
    ent = _get_assignment_or_404(assignment_id)
    return ok(ent)

"""Pole-attachment requests (PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("poles", __name__)

READ_ROLES = ("ProgramManager", "UtilityOperator", "InstallCoordinator")


def _zone_of(pole):
    return db.build_zones.get(pole["build_zone_id"])


@bp.post("/pole-attachment-requests")
def create_pole_request():
    auth.gate(("ProgramManager",))
    data = shape.body()
    zone = listing.resolve(data, "build_zone_id", "build_zones")
    shape.req_id(data, "build_zone_id")
    utility_owner = shape.req_str(data, "utility_owner", 1, 120)
    pole_count = shape.req_int(data, "pole_count", 1)
    row = new_row(
        {
            "build_zone_id": zone["id"],
            "utility_owner": utility_owner,
            "pole_count": pole_count,
            "status": "REQUESTED",
            "make_ready_cost_cents": 0,
            "survey_completed_at": None,
            "denial_reason": None,
            "attached_at": None,
        }
    )
    insert("pole_requests", row)
    return envelope.created(serialize.pole_request(row))


@bp.get("/pole-attachment-requests/<pole_id>")
def read_pole_request(pole_id):
    auth.gate(READ_ROLES)
    row = must_find("pole_requests", pole_id)
    return envelope.ok(serialize.pole_request(row))


@bp.get("/pole-attachment-requests")
def list_pole_requests():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("pole_requests")),
        (
            listing.fk("build_zone_id", "build_zone_id", "build_zones"),
            listing.enum("status", "status", calc.POLE_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.pole_request)


@bp.post("/pole-attachment-requests/<pole_id>/survey")
def survey(pole_id):
    auth.gate(("UtilityOperator",))
    pole = must_find("pole_requests", pole_id)
    data = shape.body()
    quote = shape.req_int(data, "make_ready_cost_cents", 0)
    if pole["status"] != "REQUESTED":
        raise ApiError(
            "ERR_POLE_REQUEST_STATE_INVALID", "only a requested attachment can be surveyed"
        )
    pole["status"] = "SURVEYED"
    pole["make_ready_cost_cents"] = quote
    pole["survey_completed_at"] = now()
    bump(pole)
    return envelope.ok(serialize.pole_request(pole))


@bp.post("/pole-attachment-requests/<pole_id>/decision")
def decide(pole_id):
    _user_id, role = auth.gate(("ProgramManager", "UtilityOperator"))
    pole = must_find("pole_requests", pole_id)
    data = shape.body()
    decision = shape.req_enum(data, "decision", calc.POLE_DECISIONS)
    if decision == "ACCEPT" and role != "ProgramManager":
        raise ApiError("ERR_FORBIDDEN_ROLE", "only a ProgramManager may accept a quote")
    if decision == "DENY" and role != "UtilityOperator":
        raise ApiError("ERR_FORBIDDEN_ROLE", "only a UtilityOperator may deny an attachment")
    reason = shape.opt_enum(data, "denial_reason", calc.POLE_DENIAL_REASONS)
    if decision == "DENY" and reason is None:
        shape.bad("denial_reason", "is required for a denial")
    if pole["status"] != "SURVEYED":
        raise ApiError(
            "ERR_POLE_REQUEST_STATE_INVALID", "only a surveyed attachment can be decided"
        )
    zone = _zone_of(pole)
    if decision == "ACCEPT":
        pole["status"] = "ACCEPTED"
        bump(pole)
        if zone is not None:
            bump(zone)
    else:
        pole["status"] = "DENIED"
        pole["denial_reason"] = reason
        bump(pole)
        if zone is not None:
            if zone["construction_status"] == "IN_CONSTRUCTION":
                cascades.suspend_zone(zone, "POLE_DENIED")
            else:
                bump(zone)
    return envelope.ok(serialize.pole_request(pole))


@bp.post("/pole-attachment-requests/<pole_id>/attachment")
def attachment(pole_id):
    auth.gate(("UtilityOperator",))
    pole = must_find("pole_requests", pole_id)
    if pole["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_POLE_REQUEST_STATE_INVALID",
            "only an accepted attachment can be confirmed attached",
        )
    pole["status"] = "ATTACHED"
    pole["attached_at"] = now()
    bump(pole)
    zone = _zone_of(pole)
    if zone is not None:
        bump(zone)
    return envelope.ok(serialize.pole_request(pole))

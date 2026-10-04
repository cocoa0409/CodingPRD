"""Territory and door-knock contact routes (§3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_string, require_enum, parse_dt,
    get_or_404, stamp_new, touch, paginate, sort_by_created_at,
)
from response import success_object, success_list

bp = Blueprint("territories", __name__)
PREFIX = "/branch-office/territories"

OUTCOMES = {"NO_ANSWER", "PITCHED", "APPOINTMENT_SET", "CLIENT_CONVERTED"}


@bp.route(PREFIX, methods=["POST"])
def create_territory():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["community_name", "household_capacity"])
    community = require_string(body, "community_name")
    cap = body["household_capacity"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise err("ERR_INVALID_REQUEST", "household_capacity must be an integer >= 1.")
    territory = stamp_new({
        "community_name": community,
        "household_capacity": cap,
        "assigned_advisor_id": None,
        "assignment_start": None,
        "assignment_end": None,
        "status": "OPEN",
    })
    db.territories[territory["id"]] = territory
    return success_object(territory, 201)


@bp.route(PREFIX, methods=["GET"])
def list_territories():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    items = list(db.territories.values())
    assigned = request.args.get("assigned_advisor_id")
    if assigned:
        items = [t for t in items if t.get("assigned_advisor_id") == assigned]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<tid>", methods=["GET"])
def get_territory(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    return success_object(get_or_404(db.territories, tid, "Territory"))


@bp.route(f"{PREFIX}/<tid>/assign", methods=["POST"])
def assign_territory(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    territory = get_or_404(db.territories, tid, "Territory")
    body = body_json()
    require_fields(body, ["advisor_id", "assignment_start"])
    advisor = get_or_404(db.advisors, body["advisor_id"], "Advisor")
    start = parse_dt(body["assignment_start"], "assignment_start")
    end = None
    if body.get("assignment_end") is not None:
        end = parse_dt(body["assignment_end"], "assignment_end")
        if end <= start:
            raise err("ERR_INVALID_REQUEST", "assignment_end must be after assignment_start.")
    # state: territory must be OPEN (assignment from ASSIGNED is not a defined transition)
    if territory.get("status") == "RETIRED":
        raise err("ERR_INVALID_STATE", "Territory is RETIRED.")
    if territory.get("status") == "ASSIGNED":
        # re-assignment: new half-open interval must not intersect current one
        cur_start = parse_dt(territory["assignment_start"], "assignment_start")
        cur_end = (parse_dt(territory["assignment_end"], "assignment_end")
                   if territory.get("assignment_end") else None)
        # overlap of [start, end) and [cur_start, cur_end); adjacency allowed
        new_end = end
        if cur_end is None and new_end is None:
            overlap = True
        elif cur_end is None:
            overlap = new_end > cur_start
        elif new_end is None:
            overlap = cur_end > start
        else:
            overlap = (start < cur_end) and (cur_start < new_end)
        if overlap:
            raise err("ERR_TERRITORY_OVERLAP", "New assignment interval intersects the current one.")
    territory["assigned_advisor_id"] = advisor["id"]
    territory["assignment_start"] = db.iso_format(start)
    territory["assignment_end"] = db.iso_format(end) if end else None
    territory["status"] = "ASSIGNED"
    touch(territory)
    return success_object(territory)


@bp.route(f"{PREFIX}/<tid>/retire", methods=["POST"])
def retire_territory(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    territory = get_or_404(db.territories, tid, "Territory")
    if territory.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an unassigned (OPEN) territory may be retired.")
    territory["status"] = "RETIRED"
    touch(territory)
    return success_object(territory)


@bp.route(f"{PREFIX}/<tid>/contacts", methods=["POST"])
def create_contact(tid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    territory = get_or_404(db.territories, tid, "Territory")
    body = body_json()
    require_fields(body, ["household_address", "contact_outcome", "contacted_at"])
    address = require_string(body, "household_address")
    outcome = require_enum(body, "contact_outcome", OUTCOMES)
    contacted = parse_dt(body["contacted_at"], "contacted_at")
    # capacity first (priority 11), then window (priority 12)
    active = [c for c in db.contacts.values()
              if c.get("territory_id") == tid and not c.get("archived")]
    if len(active) >= territory.get("household_capacity", 0):
        raise err("ERR_TERRITORY_CAPACITY", "Territory is at household capacity.")
    if territory.get("status") != "ASSIGNED" or territory.get("assignment_start") is None:
        raise err("ERR_CONTACT_OUTSIDE_WINDOW", "Territory has no current assignment window.")
    win_start = parse_dt(territory["assignment_start"], "assignment_start")
    win_end = (parse_dt(territory["assignment_end"], "assignment_end")
               if territory.get("assignment_end") else None)
    if contacted < win_start or (win_end is not None and contacted >= win_end):
        raise err("ERR_CONTACT_OUTSIDE_WINDOW", "contacted_at is outside the assignment window.")
    for c in active:
        if c.get("household_address") == address:
            raise err("ERR_DUPLICATE", "household_address already exists in this territory.")
    contact = stamp_new({
        "territory_id": tid,
        "household_address": address,
        "contact_outcome": outcome,
        "contacted_at": db.iso_format(contacted),
        "archived": False,
    }, with_version=False)
    db.contacts[contact["id"]] = contact
    return success_object(contact, 201)


@bp.route(f"{PREFIX}/<tid>/contacts", methods=["GET"])
def list_contacts(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.territories, tid, "Territory")
    include_archived = request.args.get("include_archived", "").lower() == "true"
    items = [c for c in db.contacts.values() if c.get("territory_id") == tid]
    if not include_archived:
        items = [c for c in items if not c.get("archived")]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)

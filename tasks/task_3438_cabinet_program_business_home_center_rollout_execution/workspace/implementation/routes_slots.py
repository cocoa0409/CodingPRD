"""ProductionSlot endpoints (PRD 3.4)."""
from flask import Blueprint, request

from auth import get_body, require_roles
from db import new_entity, store
from envelope import ok, paginate
from errors import api_error
from util import parse_week, week_of

bp = Blueprint("slots", __name__)

PLANT_CODES = ("PLANT_EAST", "PLANT_WEST", "PLANT_SOUTH")
READ_ROLES = ("PlatformAdmin", "ProgramManager", "PlantScheduler")


def serialize(slot):
    return dict(slot)


@bp.route("/cabinet/production-slots", methods=["POST"])
def create_slot():
    require_roles("PlantScheduler")
    body = get_body()
    plant_code = body.get("plant_code")
    family_code = body.get("family_code")
    week = body.get("week")
    capacity_units = body.get("capacity_units")
    if plant_code not in PLANT_CODES:
        raise api_error("ERR_INVALID_REQUEST",
                        "plant_code must be PLANT_EAST, PLANT_WEST or PLANT_SOUTH")
    if not isinstance(family_code, str) or not family_code:
        raise api_error("ERR_INVALID_REQUEST", "family_code is required")
    if parse_week(week) is None:
        raise api_error("ERR_INVALID_REQUEST", "week must be an ISO week 'YYYY-Www'")
    if isinstance(capacity_units, bool) or not isinstance(capacity_units, int) or capacity_units <= 0:
        raise api_error("ERR_INVALID_REQUEST", "capacity_units must be a positive integer")
    if parse_week(week) < parse_week(week_of(store.clock)):
        raise api_error("ERR_SLOT_WEEK_PAST",
                        "a slot may not be opened for a week before the current one")
    for existing in store.slots.values():
        if (existing["plant_code"] == plant_code
                and existing["family_code"] == family_code
                and existing["week"] == week):
            raise api_error("ERR_SLOT_EXISTS",
                            "a slot already exists for (plant_code, family_code, week)")
    slot = new_entity()
    slot.update({
        "plant_code": plant_code,
        "family_code": family_code,
        "week": week,
        "capacity_units": capacity_units,
        "committed_units": 0,
        "status": "OPEN",
    })
    store.slots[slot["id"]] = slot
    return ok(serialize(slot), 201)


@bp.route("/cabinet/production-slots", methods=["GET"])
def list_slots():
    require_roles(*READ_ROLES)
    plant_code = request.args.get("plant_code")
    family_code = request.args.get("family_code")
    week = request.args.get("week")
    status = request.args.get("status")
    items = [s for s in store.slots.values()
             if (plant_code is None or s["plant_code"] == plant_code)
             and (family_code is None or s["family_code"] == family_code)
             and (week is None or s["week"] == week)
             and (status is None or s["status"] == status)]
    items = sorted(items, key=lambda s: s["created_at"])
    page, meta = paginate([serialize(s) for s in items])
    return ok(page, 200, meta)

"""VenueSlot routes."""
from flask import Blueprint, request
from store import store, fresh, parse_dt
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request, raise_err, ERR_VENUE_SLOT_CONFLICT
from services import venue_conflict

bp = Blueprint("venues", __name__)

ROLES = ["ProgramDirector", "CastingDirector", "Registrar"]


@bp.post("/venue-slots")
def create_slot():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["venue_name", "start_utc", "end_utc", "capacity"])
    if not isinstance(body.get("capacity"), int) or isinstance(body.get("capacity"), bool):
        invalid_request("capacity must be an integer")
    start = parse_dt(body["start_utc"])
    end = parse_dt(body["end_utc"])
    if venue_conflict(start, end, body["venue_name"]):
        raise_err(ERR_VENUE_SLOT_CONFLICT, "slot conflicts with an existing RESERVED/BOOKED slot or violates turnover buffer")
    slot = fresh({
        "venue_name": body["venue_name"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "capacity": body["capacity"],
        "status": "AVAILABLE",
    })
    store.venue_slots[slot["id"]] = slot
    return success_obj(slot, 201)


@bp.get("/venue-slots")
def list_slots():
    auth(ROLES)
    limit, offset = pagination_params()
    items = list(store.venue_slots.values())
    if request.args.get("venue_name"):
        items = [x for x in items if x["venue_name"] == request.args["venue_name"]]
    if request.args.get("status"):
        items = [x for x in items if x["status"] == request.args["status"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/venue-slots/<slotId>")
def get_slot(slotId):
    auth(ROLES)
    slot = store.venue_slots.get(slotId)
    if not slot:
        not_found("venue slot not found")
    return success_obj(slot)

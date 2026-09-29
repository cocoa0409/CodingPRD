"""Park register — PRD 3.1."""
from auth import ALL_ROLES, fetch, guard
from envelope import created, listing, ok
from router import route
from shape import body, req_enum, req_int, req_str
from store import db, insert

REGION_CODES = ("NW", "NE", "SW", "SE")
PARK_STATUSES = ("OPERATING", "CLOSED")


@route("/parks", methods=["POST"])
def parks_create():
    guard("ProgramAdministrator")
    data = body()
    row = {
        "name": req_str(data, "name"),
        "region_code": req_enum(data, "region_code", REGION_CODES),
        "annual_visitation": req_int(data, "annual_visitation", minimum=0),
        "comparable_lodging_rate_cents": req_int(data, "comparable_lodging_rate_cents", minimum=1),
        "comparable_meal_rate_cents": req_int(data, "comparable_meal_rate_cents", minimum=1),
        "comparable_activity_rate_cents": req_int(data, "comparable_activity_rate_cents", minimum=1),
        "open_closure_window_count": 0,
        "status": "OPERATING",
    }
    return created(insert(db.parks, row))


@route("/parks", methods=["GET"])
def parks_list():
    guard(*ALL_ROLES)
    return listing(db.parks, ("region_code", "status"))


@route("/parks/<park_id>", methods=["GET"])
def parks_read(park_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.parks, park_id, "ERR_PARK_NOT_FOUND"))

"""Assessment center endpoints (PRD 3.4)."""
from flask import Blueprint

import constants as C
import errors as E
import serializers as ser
from response import ok
from store import DB, new_id, stamp_new
from validation import auth_headers, require_role, body, req_field, as_int

bp = Blueprint("centers", __name__)


@bp.post("/assessment-centers")
def create_center():
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    data = body()
    name = req_field(data, "name")
    region_code = req_field(data, "region_code")
    slot_capacity = as_int(req_field(data, "slot_capacity"), "slot_capacity")
    if slot_capacity < 1:
        E.fail(E.ERR_INVALID_REQUEST, 400, "slot_capacity must be at least 1")
    center = {
        "id": new_id(),
        "name": name,
        "region_code": region_code,
        "slot_capacity": slot_capacity,
    }
    stamp_new(center)
    DB.centers[center["id"]] = center
    return ok(ser.center(center), 201)


@bp.get("/assessment-centers/<center_id>")
def get_center(center_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    center = DB.centers.get(center_id)
    if center is None:
        E.fail(E.ERR_CENTER_NOT_FOUND, 404, "Center not found: %s" % center_id)
    return ok(ser.center(center))

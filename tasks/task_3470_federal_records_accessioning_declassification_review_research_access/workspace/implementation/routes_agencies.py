"""Agency endpoints (PRD §3.1).

POST /records/agencies        PlatformAdmin, 201
GET  /records/agencies/{id}   all roles except Anonymous, 200
"""
from flask import Blueprint

import constants as C
from envelope import ok_object
from errors import err
from helpers import get_agency
from store import DB, new_id, ts3
from validation import get_auth, get_body, req_str, require_role

bp = Blueprint("agencies", __name__)


@bp.post("/records/agencies")
def create_agency():
    _uid, role = get_auth()                       # rung 1
    require_role(role, ["PlatformAdmin"])         # rung 2
    body = get_body()
    # rung 12 (uniqueness) precedes rung 15 (shape) in the ladder; evaluate
    # the duplicate check as soon as a usable agency_code is present.
    code_raw = body.get("agency_code")
    if isinstance(code_raw, str) and code_raw != "" and any(
        a["agency_code"] == code_raw for a in DB.agencies.values()
    ):
        raise err("ERR_AGENCY_CODE_EXISTS", "agency_code already registered")
    agency_code = req_str(body, "agency_code")    # rung 15
    name = req_str(body, "name")
    now = ts3(DB.now())
    agency = {
        "id": new_id(),
        "agency_code": agency_code,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.agencies[agency["id"]] = agency
    return ok_object(agency, 201)


@bp.get("/records/agencies/<agency_id>")
def get_one_agency(agency_id):
    _uid, role = get_auth()                       # rung 1
    require_role(role, C.ALL_READ_ROLES)          # rung 2
    return ok_object(get_agency(agency_id))       # rung 3

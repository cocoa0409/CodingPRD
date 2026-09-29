"""Water body inventory (PRD 3.1)."""

from flask import Blueprint

import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, serialize, touch
from validate import (arg_filter, opt_enum, opt_ref, read_body, req_enum,
                      req_state_code, req_str, require_auth)

bp = Blueprint("water_bodies", __name__)

CLASSES = ("LAKE", "RESERVOIR", "RIVER", "CANAL")
TIERS = ("HIGH", "MODERATE", "LOW")
STATUSES = ("CLEAN", "SUSPECT", "CONFIRMED_INFESTED")


def _cycle_check(start_id, parent_id):
    """Following the drainage chain must never return to start_id."""
    if parent_id is None:
        return
    if parent_id == start_id:
        raise ApiError("ERR_WATER_BODY_CYCLE")
    seen = set()
    cursor = parent_id
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        if cursor == start_id:
            raise ApiError("ERR_WATER_BODY_CYCLE")
        node = db.water_bodies.get(cursor)
        if node is None:
            return
        cursor = node["downstream_of_water_body_id"]


@bp.post("/water-bodies")
def create_water_body():
    require_auth(("ProgramAdmin",))
    body = read_body()
    name = req_str(body, "name")
    state_code = req_state_code(body, "state_code")
    water_body_class = req_enum(body, "water_body_class", CLASSES)
    risk_tier = opt_enum(body, "risk_tier", TIERS, "MODERATE")
    infestation = opt_enum(body, "infestation_status", STATUSES, "CLEAN")
    parent_id = opt_ref(body, "downstream_of_water_body_id")

    if parent_id is not None:
        services.water_body_or_404(parent_id)

    row = base_row()
    _cycle_check(row["id"], parent_id)
    row.update({
        "name": name,
        "state_code": state_code,
        "water_body_class": water_body_class,
        "risk_tier": risk_tier,
        "infestation_status": infestation,
        "downstream_of_water_body_id": parent_id,
        "detection_count": 0,
        "live_detection_count": 0,
    })
    db.water_bodies[row["id"]] = row
    return created(serialize(row))


@bp.get("/water-bodies/<wid>")
def get_water_body(wid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.water_body_or_404(wid)))


@bp.get("/water-bodies")
def list_water_bodies():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "downstream_of_water_body_id": arg_filter("downstream_of_water_body_id"),
        "risk_tier": arg_filter("risk_tier"),
        "infestation_status": arg_filter("infestation_status"),
        "state_code": arg_filter("state_code"),
    }
    rows = [r for r in db.water_bodies.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.patch("/water-bodies/<wid>")
def correct_water_body(wid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    risk_tier = opt_enum(body, "risk_tier", TIERS)
    parent_supplied = "downstream_of_water_body_id" in body
    parent_id = opt_ref(body, "downstream_of_water_body_id")

    row = services.water_body_or_404(wid)
    if parent_supplied and parent_id is not None:
        services.water_body_or_404(parent_id)
    if parent_supplied:
        _cycle_check(row["id"], parent_id)
        row["downstream_of_water_body_id"] = parent_id
    if risk_tier is not None:
        row["risk_tier"] = risk_tier
    touch(row)
    return ok(serialize(row))

"""Territories (PRD §3.2): OPEN -> ASSIGNED -> OPEN is a deliberate cycle."""
from flask import Blueprint

from constants import MAX_TERRITORIES_PER_LICENSEE, POPULATION_TIERS, TERRITORY_STATUSES
from db import store
from errors import err
from middleware import auth, require_role
from routes.licensees import get_licensee
from services.engine import revoke_territory
from util import (
    get_body, new_record, ok_object, req_enum, req_str, serialize, touch,
)
from util import now_dt

bp = Blueprint("territories", __name__)


def get_territory(tid):
    t = store.territories.get(tid)
    if t is None:
        err("ERR_TERRITORY_NOT_FOUND", "unknown territory id")
    return t


@bp.route("/api/territories", methods=["POST"])
def create_territory():
    _uid, role = auth()
    data = get_body()
    region_code = req_str(data, "region_code")
    population_tier = req_enum(data, "population_tier", POPULATION_TIERS)
    require_role(role, ["PlatformAdmin"])
    if any(t["region_code"] == region_code for t in store.territories.values()):
        err("ERR_VALIDATION", "region_code must be unique")
    rec = new_record()
    rec.update({
        "region_code": region_code,
        "population_tier": population_tier,
        "status": "OPEN",
        "assigned_licensee_id": None,
        "assigned_at": None,
        "revoked_at": None,
    })
    store.territories[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/territories/<tid>", methods=["GET"])
def fetch_territory(tid):
    auth()
    return ok_object(serialize(get_territory(tid)), 200)


@bp.route("/api/territories/<tid>/transition", methods=["POST"])
def transition_territory(tid):
    _uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", TERRITORY_STATUSES)
    licensee_id = data.get("licensee_id")
    if to_state == "ASSIGNED" and not isinstance(licensee_id, str):
        err("ERR_VALIDATION", "licensee_id is required when assigning")
    require_role(role, ["PlatformAdmin"])
    terr = get_territory(tid)

    if to_state == "ASSIGNED":
        lic = get_licensee(licensee_id)  # body FK existence, after the path id
        if lic["status"] != "ACTIVE":
            err("ERR_LICENSEE_NOT_ACTIVE", "territory assign requires an ACTIVE licensee")
        if terr["status"] != "OPEN":
            err("ERR_REGION_ALREADY_ASSIGNED", "territory is not OPEN")
        held = sum(
            1 for t in store.territories.values()
            if t["assigned_licensee_id"] == lic["id"] and t["status"] == "ASSIGNED"
        )
        if held >= MAX_TERRITORIES_PER_LICENSEE:
            err("ERR_MAX_TERRITORIES_EXCEEDED", "licensee already holds 3 territories")
        bumped = set()
        terr["status"] = "ASSIGNED"
        terr["assigned_licensee_id"] = lic["id"]
        terr["assigned_at"] = now_dt()
        touch(terr, bumped)
        return ok_object(serialize(terr), 200)

    # to_state == "OPEN": manual revocation; cascade cancels affected appointments.
    if terr["status"] != "ASSIGNED":
        err("ERR_INVALID_TRANSITION", "only an ASSIGNED territory can be revoked to OPEN")
    bumped = set()
    revoke_territory(terr, bumped)
    return ok_object(serialize(terr), 200)

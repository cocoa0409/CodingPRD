"""Agency and Building endpoints (PRD section 3.1)."""
from flask import Blueprint

from envelope import success
from errors import ApiError
from middleware import ALL_ROLES, body, is_int, require_auth
from store import DB, make_entity, pub

bp = Blueprint("agencies_buildings", __name__)


@bp.route("/leasing/agencies", methods=["POST"])
def create_agency():
    require_auth(["GSAAdmin"])
    b = body()
    bureau_code = b.get("bureau_code")
    name = b.get("name")
    if not isinstance(bureau_code, str) or bureau_code == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "bureau_code is required")
    if not isinstance(name, str) or name == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "name is required")
    for a in DB["agencies"].values():
        if a["bureau_code"] == bureau_code:
            raise ApiError("ERR_INVALID_REQUEST", 400, "bureau_code must be unique across agencies")
    e = make_entity()
    e.update({"bureau_code": bureau_code, "name": name, "status": "ACTIVE"})
    DB["agencies"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/agencies/<aid>", methods=["GET"])
def get_agency(aid):
    require_auth(ALL_ROLES)
    a = DB["agencies"].get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND", 404, "Agency not found")
    return success(pub(a))


@bp.route("/leasing/buildings", methods=["POST"])
def create_building():
    require_auth(["GSAAdmin"])
    b = body()
    for f in ("building_name", "address", "region_code"):
        if not isinstance(b.get(f), str) or b.get(f) == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, f + " is required")
    if b.get("ownership_type") not in ("FEDERALLY_OWNED", "LEASED_STOCK"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "ownership_type must be FEDERALLY_OWNED or LEASED_STOCK")
    if not is_int(b.get("security_capability")) or not (1 <= b["security_capability"] <= 5):
        raise ApiError("ERR_INVALID_REQUEST", 400, "security_capability must be an integer in 1..5")
    if not is_int(b.get("total_sf")) or b["total_sf"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "total_sf must be an integer > 0")
    e = make_entity()
    e.update({
        "building_name": b["building_name"],
        "address": b["address"],
        "region_code": b["region_code"],
        "ownership_type": b["ownership_type"],
        "security_capability": b["security_capability"],
        "total_sf": b["total_sf"],
        "available_sf": b["total_sf"],
        "status": "ACTIVE",
    })
    DB["buildings"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/buildings/<bid>", methods=["GET"])
def get_building(bid):
    require_auth(ALL_ROLES)
    e = DB["buildings"].get(bid)
    if not e:
        raise ApiError("ERR_NOT_FOUND", 404, "Building not found")
    return success(pub(e))

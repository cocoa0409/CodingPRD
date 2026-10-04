"""Platform catalog: POST /battery-ecosystem/battery-platforms."""
from flask import Blueprint

import db
from constants import API_PREFIX, CHEMISTRY_FAMILIES, INTERFACE_KEYS
from errors import fail
from helpers import authorize, body, ok_object, parse_dt, present, req_int, req_str
from services import make_entity
from views import view_platform

bp = Blueprint("platforms", __name__)


@bp.route(f"{API_PREFIX}/battery-platforms", methods=["POST"])
def create_platform():
    authorize(["PlatformAdmin"])
    data = body()
    # Priority 5: request shape
    code = req_str(data, "code")
    interface_key = req_str(data, "interface_key")
    if interface_key not in INTERFACE_KEYS:
        fail("ERR_VALIDATION", "interface_key must be INTERFACE_A or INTERFACE_B")
    chemistry_family = req_str(data, "chemistry_family")
    if chemistry_family not in CHEMISTRY_FAMILIES:
        fail("ERR_VALIDATION", "chemistry_family must be LION_NMC or LFP")
    bcy = req_int(data, "backward_commitment_years", minimum=0)
    fcg = req_int(data, "forward_commitment_generations", minimum=0)
    announce = None
    if present(data, "sunset_announce_date"):
        announce = parse_dt(data["sunset_announce_date"], "sunset_announce_date")
    sunset = None
    if present(data, "sunset_date"):
        sunset = parse_dt(data["sunset_date"], "sunset_date")
    if announce is not None and sunset is not None and announce > sunset:
        fail("ERR_VALIDATION", "sunset_announce_date must be on or before sunset_date")
    # Priority 11: uniqueness of platform code
    for p in db.STORE["platforms"].values():
        if p["code"] == code:
            fail("ERR_DUPLICATE_SKU", "A platform with this code already exists")
    platform = make_entity(
        {
            "code": code,
            "interface_key": interface_key,
            "chemistry_family": chemistry_family,
            "backward_commitment_years": bcy,
            "forward_commitment_generations": fcg,
            "sunset_announce_date": announce,
            "sunset_date": sunset,
            "status": "ACTIVE",
        }
    )
    db.STORE["platforms"][platform["id"]] = platform
    return ok_object(view_platform(platform), 201)

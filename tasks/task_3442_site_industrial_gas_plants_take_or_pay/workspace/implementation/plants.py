"""Dedicated on-site plants (PRD 3.3): create, advance, list, get."""
from flask import Blueprint, request

from helpers import (authenticate, require_role, json_body, respond,
                     v_str, v_int, v_num, by_created, paginate)
from store import db, base_entity, pub, touch, ApiError
from domain import live_plant_for_contract

bp = Blueprint("plants", __name__)


@bp.route("/gas-supply/onsite-plants", methods=["POST"])
def create_plant():
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    body = json_body()
    # Tier 3: body-referenced contract must exist
    cid = body.get("contract_id")
    contract = None
    if isinstance(cid, str):
        contract = db["contracts"].get(cid)
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", 404,
                           "SupplyContract not found")
    # Tier 4: contract must be ACTIVE
    if contract is not None and contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409,
                       "Plant creation requires an ACTIVE contract")
    # Tier 7: mode must be ONSITE_PLANT, then one-live-plant uniqueness
    if contract is not None and contract["mode"] != "ONSITE_PLANT":
        raise ApiError("ERR_MODE_MISMATCH", 422,
                       "Plant creation requires an ONSITE_PLANT contract")
    if contract is not None and live_plant_for_contract(contract["id"]) is not None:
        raise ApiError("ERR_PLANT_ALREADY_EXISTS", 409,
                       "A non-DECOMMISSIONED plant already exists for this "
                       "contract")
    # Tier 9 structural
    contract_id = v_str(body, "contract_id")
    name = v_str(body, "name")
    nameplate = v_int(body, "nameplate_capacity_nm3h", min_value=1)
    capital = v_int(body, "capital_cost_cents", min_value=0)
    kwh = v_num(body, "power_kwh_per_nm3", min_value=0)
    if contract is None:
        contract = db["contracts"][contract_id]
    ent = base_entity()
    ent.update({
        "contract_id": contract_id,
        "customer_id": contract["customer_id"],
        "name": name,
        "nameplate_capacity_nm3h": nameplate,
        "capital_cost_cents": capital,
        "power_kwh_per_nm3": kwh,
        "status": "PROPOSED",
        "effective_capacity_nm3h": 0,
    })
    db["plants"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/onsite-plants/<plantId>", methods=["GET"])
def get_plant(plantId):
    authenticate()
    ent = db["plants"].get(plantId)
    if ent is None:
        raise ApiError("ERR_PLANT_NOT_FOUND", 404, "OnsitePlant not found")
    return respond(pub(ent))


@bp.route("/gas-supply/onsite-plants", methods=["GET"])
def list_plants():
    authenticate()
    items = list(db["plants"].values())
    for f in ("customer_id", "contract_id"):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    items = by_created(items)
    page, meta = paginate(items)
    return respond([pub(p) for p in page], "array", 200, meta)


_ADVANCE = {
    "PROPOSED": "UNDER_CONSTRUCTION",
    "UNDER_CONSTRUCTION": "COMMISSIONING",
    "COMMISSIONING": "OPERATING",
}


@bp.route("/gas-supply/onsite-plants/<plantId>/advance", methods=["POST"])
def advance_plant(plantId):
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    ent = db["plants"].get(plantId)
    if ent is None:
        raise ApiError("ERR_PLANT_NOT_FOUND", 404, "OnsitePlant not found")
    nxt = _ADVANCE.get(ent["status"])
    if nxt is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Plant cannot advance from %s" % ent["status"])
    ent["status"] = nxt
    if nxt == "OPERATING":
        ent["effective_capacity_nm3h"] = ent["nameplate_capacity_nm3h"]
    touch(ent)
    return respond(pub(ent))

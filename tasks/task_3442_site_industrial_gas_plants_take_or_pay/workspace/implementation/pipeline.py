"""Pipeline networks and firm capacity connections (PRD 3.4)."""
from flask import Blueprint, request

from helpers import (authenticate, require_role, json_body, respond,
                     v_str, v_int, v_enum, as_int, by_created, paginate)
from store import db, base_entity, pub, touch, ApiError

bp = Blueprint("pipeline", __name__)


def _reserved_sum(network_id):
    return sum(c["reserved_flow_nm3h"] for c in db["connections"].values()
               if c["network_id"] == network_id and c["status"] == "ACTIVE")


def _network_view(n):
    view = pub(n)
    reserved = _reserved_sum(n["id"])
    view["reserved_capacity_nm3h"] = reserved
    view["available_capacity_nm3h"] = n["nameplate_capacity_nm3h"] - reserved
    return view


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
@bp.route("/gas-supply/pipeline-networks", methods=["POST"])
def create_network():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    name = v_str(body, "name")
    nameplate = v_int(body, "nameplate_capacity_nm3h", min_value=1)
    ent = base_entity()
    ent.update({"name": name, "nameplate_capacity_nm3h": nameplate})
    db["networks"][ent["id"]] = ent
    return respond(_network_view(ent), "object", 201)


@bp.route("/gas-supply/pipeline-networks/<networkId>", methods=["GET"])
def get_network(networkId):
    authenticate()
    ent = db["networks"].get(networkId)
    if ent is None:
        raise ApiError("ERR_NETWORK_NOT_FOUND", 404, "PipelineNetwork not found")
    return respond(_network_view(ent))


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
@bp.route("/gas-supply/pipeline-connections", methods=["POST"])
def create_connection():
    _uid, role = authenticate()
    require_role(role, {"PipelineDispatcher"})
    body = json_body()
    # Tier 3: body-referenced entities (network before contract)
    net = None
    nid = body.get("network_id")
    if isinstance(nid, str):
        net = db["networks"].get(nid)
        if net is None:
            raise ApiError("ERR_NETWORK_NOT_FOUND", 404,
                           "PipelineNetwork not found")
    contract = None
    cid = body.get("contract_id")
    if isinstance(cid, str):
        contract = db["contracts"].get(cid)
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", 404,
                           "SupplyContract not found")
    # Tier 4: contract must be DRAFT or ACTIVE
    if contract is not None and contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Connection requires a DRAFT or ACTIVE contract")
    # Tier 7: capacity admission (exact fit allowed), then purpose/mode match
    flow = as_int(body.get("reserved_flow_nm3h"))
    if net is not None and flow is not None:
        available = net["nameplate_capacity_nm3h"] - _reserved_sum(net["id"])
        if flow > available:
            raise ApiError("ERR_PIPELINE_CAPACITY_EXCEEDED", 409,
                           "reserved_flow_nm3h exceeds available capacity")
    purpose_raw = body.get("purpose")
    if contract is not None and purpose_raw in ("PRIMARY", "BACKUP"):
        need = "PIPELINE" if purpose_raw == "PRIMARY" else "ONSITE_PLANT"
        if contract["mode"] != need:
            raise ApiError("ERR_MODE_MISMATCH", 422,
                           "%s purpose requires a %s contract"
                           % (purpose_raw, need))
    # Tier 9 structural
    network_id = v_str(body, "network_id")
    contract_id = v_str(body, "contract_id")
    flow = v_int(body, "reserved_flow_nm3h", min_value=1)
    purpose = v_enum(body, "purpose", ("PRIMARY", "BACKUP"))
    if net is None:
        net = db["networks"][network_id]
    ent = base_entity()
    ent.update({
        "network_id": network_id,
        "contract_id": contract_id,
        "reserved_flow_nm3h": flow,
        "purpose": purpose,
        "status": "ACTIVE",
    })
    db["connections"][ent["id"]] = ent
    touch(net)  # reservation aggregates are derived from live connections
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/pipeline-connections/<connectionId>", methods=["GET"])
def get_connection(connectionId):
    authenticate()
    ent = db["connections"].get(connectionId)
    if ent is None:
        raise ApiError("ERR_CONNECTION_NOT_FOUND", 404,
                       "PipelineConnection not found")
    return respond(pub(ent))


@bp.route("/gas-supply/pipeline-connections", methods=["GET"])
def list_connections():
    authenticate()
    items = list(db["connections"].values())
    for f in ("network_id", "contract_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [c for c in items if c.get(f) == val]
    items = by_created(items)
    page, meta = paginate(items)
    return respond([pub(c) for c in page], "array", 200, meta)


@bp.route("/gas-supply/pipeline-connections/<connectionId>/release",
          methods=["POST"])
def release_connection(connectionId):
    _uid, role = authenticate()
    require_role(role, {"PipelineDispatcher"})
    ent = db["connections"].get(connectionId)
    if ent is None:
        raise ApiError("ERR_CONNECTION_NOT_FOUND", 404,
                       "PipelineConnection not found")
    if ent["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ACTIVE connection can be released")
    ent["status"] = "RELEASED"
    touch(ent)
    net = db["networks"].get(ent["network_id"])
    if net is not None:
        touch(net)
    return respond(pub(ent))

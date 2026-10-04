"""ShoeModel and Component endpoints (PRD 3.3)."""
from flask import Blueprint, request

import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_enum, req_int, req_number, req_bool

bp = Blueprint("models", __name__)


def get_model(mid):
    m = DB["models"].get(mid)
    if m is None:
        raise ApiError("ERR_MODEL_NOT_FOUND", "model id does not resolve")
    return m


@bp.post("/footwear/models")
@require_roles("SourcingManager")
def create_model(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema): bom component FKs first.
    bom = b.get("bom_lines")
    if isinstance(bom, list):
        for entry in bom:
            if isinstance(entry, dict):
                cid = entry.get("component_id")
                if cid is not None and cid not in DB["components"]:
                    raise ApiError(
                        "ERR_COMPONENT_NOT_FOUND",
                        "bom_lines entry component_id does not resolve",
                    )
    style = req_str(b, "style_code")
    policy = req_enum(b, "production_policy", constants.PRODUCTION_POLICIES)
    base_price = req_int(b, "base_price_cents", min_v=1)
    basis = req_int(b, "import_cost_basis_cents", min_v=1)
    if not isinstance(bom, list) or len(bom) < 1:
        raise ApiError("ERR_INVALID_REQUEST", "bom_lines must contain at least one line")
    lines = []
    for i, entry in enumerate(bom):
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "bom_lines[%d] must be an object" % i)
        cid = req_str(entry, "component_id")
        q = req_number(entry, "quantity_per_pair", gt=0)
        sr = req_enum(entry, "sourcing_requirement", constants.SOURCING_REQUIREMENTS)
        cost = req_int(entry, "planned_unit_cost_cents", min_v=0)
        dom = req_bool(entry, "planned_is_domestic")
        lines.append({
            "component_id": cid,
            "quantity_per_pair": q,
            "sourcing_requirement": sr,
            "planned_unit_cost_cents": cost,
            "planned_is_domestic": dom,
        })
    smin = req_int(b, "standard_stitching_minutes", min_v=0)
    lmin = req_int(b, "standard_lasting_minutes", min_v=0)
    amin = req_int(b, "standard_assembly_minutes", min_v=0)
    # Family 9 (structural): style_code uniqueness.
    if any(m["style_code"] == style for m in DB["models"].values()):
        raise ApiError("ERR_STYLE_CODE_EXISTS", "style_code already in use")
    m = base_fields()
    m.update({
        "style_code": style,
        "production_policy": policy,
        "base_price_cents": base_price,
        "import_cost_basis_cents": basis,
        "bom_lines": lines,
        "standard_stitching_minutes": smin,
        "standard_lasting_minutes": lmin,
        "standard_assembly_minutes": amin,
        "domestic_unit_cost_cents": None,
        "domestic_price_cents": None,
        "status": "ACTIVE",
    })
    DB["models"][m["id"]] = m
    return ok_obj(serializers.pub(m), 201)


@bp.get("/footwear/models")
@require_roles(*constants.ALL_ROLES)
def list_models(_uid, _role):
    items = sorted_items(DB["models"])
    policy = request.args.get("production_policy")
    status = request.args.get("status")
    if policy is not None:
        items = [m for m in items if m["production_policy"] == policy]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response([serializers.pub(m) for m in items])


@bp.get("/footwear/models/<mid>")
@require_roles(*constants.ALL_ROLES)
def get_one_model(mid, _uid, _role):
    return ok_obj(serializers.pub(get_model(mid)))


@bp.post("/footwear/models/<mid>/discontinue")
@require_roles("SourcingManager")
def discontinue_model(mid, _uid, _role):
    m = get_model(mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE model can be discontinued")
    if any(r["model_id"] == mid and r["status"] in constants.OPEN_RUN_STATES
           for r in DB["runs"].values()):
        raise ApiError("ERR_MODEL_HAS_OPEN_RUNS", "model has runs still in flight")
    if any(c["model_id"] == mid and c["status"] == "PUBLISHED"
           for c in DB["claims"].values()):
        raise ApiError("ERR_MODEL_HAS_PUBLISHED_CLAIMS", "model has a PUBLISHED claim")
    m["status"] = "DISCONTINUED"
    touch(m)
    for c in DB["claims"].values():
        if c["model_id"] == mid and c["status"] in ("DRAFT", "SUBSTANTIATED", "CHALLENGED"):
            c["status"] = "REVOKED"
            touch(c)
    return ok_obj(serializers.pub(m))


@bp.post("/footwear/components")
@require_roles("SourcingManager")
def create_component(_uid, _role):
    b = body()
    name = req_str(b, "component_name")
    ctype = req_enum(b, "component_type", constants.COMPONENT_TYPES)
    c = base_fields()
    c.update({"component_name": name, "component_type": ctype})
    DB["components"][c["id"]] = c
    return ok_obj(serializers.pub(c), 201)

"""Complexes: create/read, capacity projection, the weekly operations
checkpoint, and house creation/listing under a complex (PRD §3.1, §2.4)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from calc import capacity_projection
from db import STORE, set_dt, stamp_new, touch
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import get_complex, list_response
from ops import run_ops as execute_run_ops
from serialize import serialize_complex, serialize_house
from util import HOUSING_STYLES, REGIONS, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("complexes", __name__)


@bp.route("/api/complexes", methods=["POST"])
def create_complex():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    values, _raws = validate_payload(
        get_body(),
        {
            "name": {"kind": "string", "required": True},
            "region_code": {"kind": "enum", "required": True, "enum": REGIONS},
            "mill_receiving_tons_per_day": {
                "kind": "int", "required": True, "gt": 0,
            },
        },
    )
    cx = {
        "name": values["name"],
        "region_code": values["region_code"],
        "mill_receiving_tons_per_day": values["mill_receiving_tons_per_day"],
        "biosecurity_posture": "NORMAL",
        "corn_inventory_tons": 0,
        "corn_organic_inventory_tons": 0,
        "soy_inventory_tons": 0,
        "soy_organic_inventory_tons": 0,
        "ungraded_conventional_dozen": 0,
        "ungraded_cage_free_dozen": 0,
        "ungraded_organic_dozen": 0,
        "ops_run_index": 0,
    }
    stamp_new(cx)
    set_dt(cx, "last_ops_run_at", STORE.clock)
    STORE.complexes[cx["id"]] = cx
    return success_object(serialize_complex(cx), 201)


@bp.route("/api/complexes/<cid>", methods=["GET"])
def read_complex(cid):
    authenticate()
    return success_object(serialize_complex(get_complex(cid)))


@bp.route("/api/complexes/<cid>/capacity-projection", methods=["GET"])
def capacity_projection_endpoint(cid):
    authenticate()
    cx = get_complex(cid)
    raw = request.args.get("week_offset")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "week_offset is required")
    try:
        week_offset = int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "week_offset must be an integer")
    if week_offset < 0 or week_offset > 52:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "week_offset must be within 0..52"
        )
    per = capacity_projection(cx["id"], week_offset)
    return success_object(
        {
            "week_offset": week_offset,
            "conventional_dozen": per["CONVENTIONAL"],
            "cage_free_dozen": per["CAGE_FREE"],
            "organic_dozen": per["ORGANIC"],
            "total_dozen": sum(per.values()),
        }
    )


@bp.route("/api/complexes/<cid>/run-ops", methods=["POST"])
def run_ops_endpoint(cid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "ComplexManager"})
    cx = get_complex(cid)
    validate_payload(get_body(), {})
    execute_run_ops(cx)
    return success_object(serialize_complex(cx))


@bp.route("/api/complexes/<cid>/houses", methods=["POST"])
def create_house(cid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    cx = get_complex(cid)
    values, _raws = validate_payload(
        get_body(),
        {
            "house_code": {"kind": "string", "required": True},
            "housing_style": {
                "kind": "enum", "required": True, "enum": HOUSING_STYLES,
            },
            "capacity_hens": {"kind": "int", "required": True, "gt": 0},
        },
    )
    house = {
        "complex_id": cx["id"],
        "house_code": values["house_code"],
        "housing_style": values["housing_style"],
        "capacity_hens": values["capacity_hens"],
        "hen_inventory": 0,
        "downtime_until": None,
        "_dt_downtime_until": None,
    }
    stamp_new(house)
    STORE.houses[house["id"]] = house
    touch(cx)  # creating a house bumps the owning complex's version
    return success_object(serialize_house(house), 201)


@bp.route("/api/complexes/<cid>/houses", methods=["GET"])
def list_houses(cid):
    authenticate()
    cx = get_complex(cid)
    items = [h for h in STORE.houses.values() if h["complex_id"] == cx["id"]]
    style = request.args.get("housing_style")
    if style is not None:
        items = [h for h in items if h["housing_style"] == style]
    return list_response(items, serialize_house)

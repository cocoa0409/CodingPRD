"""Variety endpoints: register, get, release, recall, list recall orders."""
from flask import Blueprint

import constants
import store
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_VARIETY_NOT_FOUND,
)
from helpers import (
    as_dt,
    as_enum,
    as_int,
    as_str,
    body,
    dump,
    opt_field,
    paginate,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("varieties", __name__)

ANY_ROLE = constants.ROLES


def get_variety_or_404(variety_id):
    v = store.db["varieties"].get(variety_id)
    if v is None:
        raise err(ERR_VARIETY_NOT_FOUND, "No variety with the given id")
    return v


@bp.route("/licensing/varieties", methods=["POST"])
@require_roles("BreedingManager")
def create_variety():
    b = body()
    variety_code = as_str(req_field(b, "variety_code"), "variety_code")
    berry_type = as_enum(req_field(b, "berry_type"), "berry_type", constants.BERRY_TYPES)
    name = as_str(req_field(b, "name"), "name")
    for v in store.db["varieties"].values():
        if v["variety_code"] == variety_code:
            raise err(ERR_INVALID_REQUEST, "variety_code must be unique across all varieties")
    rec = store.init_record({
        "variety_code": variety_code,
        "berry_type": berry_type,
        "name": name,
        "status": "DEVELOPMENT",
        "released_at": None,
        "recalled_at": None,
    })
    store.db["varieties"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/varieties/<varietyId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_variety(varietyId):
    return success(dump(get_variety_or_404(varietyId)))


@bp.route("/licensing/varieties/<varietyId>/release", methods=["POST"])
@require_roles("BreedingManager")
def release_variety(varietyId):
    v = get_variety_or_404(varietyId)
    if v["status"] != "DEVELOPMENT":
        raise err(ERR_INVALID_STATE, "Variety is not in DEVELOPMENT")
    v["status"] = "RELEASED"
    v["released_at"] = store.clock_now()
    store.touch(v)
    return success(dump(v))


@bp.route("/licensing/varieties/<varietyId>/recall", methods=["POST"])
@require_roles("BreedingManager")
def recall_variety(varietyId):
    v = get_variety_or_404(varietyId)
    b = body()
    reason = as_str(req_field(b, "reason"), "reason")
    destroy_before = as_dt(req_field(b, "destroy_before"), "destroy_before")
    comp = opt_field(b, "compensation_per_plant_cents", constants.DEFAULT_COMPENSATION_PER_PLANT_CENTS)
    comp = as_int(comp, "compensation_per_plant_cents", min_value=0)
    if v["status"] != "RELEASED":
        raise err(ERR_INVALID_STATE, "Variety is not in RELEASED")
    v["status"] = "RECALLED"
    v["recalled_at"] = store.clock_now()
    store.touch(v)
    order = store.init_record({
        "variety_id": v["id"],
        "reason": reason,
        "destroy_before": destroy_before,
        "compensation_per_plant_cents": comp,
        "status": "ISSUED",
        "plantings_recalled_count": 0,
        "total_compensation_cents": 0,
        "enforced_at": None,
    })
    store.db["recall_orders"][order["id"]] = order
    return success(dump(order), code=201)


@bp.route("/licensing/varieties/<varietyId>/recall-orders", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_recall_orders(varietyId):
    get_variety_or_404(varietyId)
    items = [
        o for o in store.db["recall_orders"].values() if o["variety_id"] == varietyId
    ]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)

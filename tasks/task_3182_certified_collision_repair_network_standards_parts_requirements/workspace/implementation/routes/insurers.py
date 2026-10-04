"""Insurer relation endpoints."""
from flask import Blueprint, request

from db import db, serialize
from util import (ApiError, bump, get_json, ok, paginate, sort_by_created,
                  new_common)
from routes.shops import require_roles, get_shop_or_404

bp = Blueprint("insurers", __name__)

ROLES_LIST = {"NetworkAdmin", "NetworkAuditor", "ShopManager", "InsurerRep"}
ROLES_READ_ONE = {"NetworkAdmin", "InsurerRep"}


def get_relation_or_404(rel_id):
    rel = db.insurer_relations.get(rel_id)
    if not rel:
        raise ApiError("ERR_NOT_FOUND", 404, "Insurer relation not found")
    return rel


def _steering_for(shop, status):
    return status == "ACTIVE" and shop["certification_status"] in ("CERTIFIED", "PROBATION")


@bp.post("/network/shops/<shop_id>/insurer-relations")
def create_relation(shop_id):
    require_roles("NetworkAdmin")
    shop = get_shop_or_404(shop_id)
    body = get_json()
    insurer_code = body.get("insurer_code")
    discount = body.get("discount_pct_bps")
    if not isinstance(insurer_code, str) or not insurer_code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "insurer_code is required")
    if not isinstance(discount, int) or isinstance(discount, bool) \
            or discount < 0 or discount > 2000:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "discount_pct_bps must be an integer in 0..2000")
    if any(r["shop_id"] == shop["id"] and r["insurer_code"] == insurer_code
           for r in db.insurer_relations.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "insurer_code must be unique per shop")
    rel = new_common()
    rel.update({
        "shop_id": shop["id"],
        "insurer_code": insurer_code,
        "steering_enabled": _steering_for(shop, "ACTIVE"),
        "discount_pct_bps": discount,
        "status": "ACTIVE",
    })
    db.insurer_relations[rel["id"]] = rel
    return ok(serialize(rel), 201)


@bp.get("/network/shops/<shop_id>/insurer-relations")
def list_relations(shop_id):
    require_roles(*ROLES_LIST)
    get_shop_or_404(shop_id)
    status = request.args.get("status")
    insurer_code = request.args.get("insurer_code")
    items = [r for r in db.insurer_relations.values() if r["shop_id"] == shop_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if insurer_code is not None:
        items = [r for r in items if r["insurer_code"] == insurer_code]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@bp.get("/network/insurer-relations/<rel_id>")
def get_relation(rel_id):
    require_roles(*ROLES_READ_ONE)
    return ok(serialize(get_relation_or_404(rel_id)))


@bp.get("/network/insurer-relations/<rel_id>/repair-orders")
def list_relation_orders(rel_id):
    require_roles(*ROLES_READ_ONE)
    get_relation_or_404(rel_id)
    items = sort_by_created([o for o in db.repair_orders.values()
                             if o["insurer_relation_id"] == rel_id])
    page, meta = paginate(items)
    return ok([serialize(o) for o in page], 200, meta)


@bp.post("/network/insurer-relations/<rel_id>/suspend")
def suspend_relation(rel_id):
    require_roles("NetworkAdmin")
    rel = get_relation_or_404(rel_id)
    if rel["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Relation is not ACTIVE")
    rel["status"] = "SUSPENDED"
    rel["steering_enabled"] = False
    bump(rel)
    return ok(serialize(rel))


@bp.post("/network/insurer-relations/<rel_id>/reinstate")
def reinstate_relation(rel_id):
    require_roles("NetworkAdmin")
    rel = get_relation_or_404(rel_id)
    if rel["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Relation is not SUSPENDED")
    shop = db.shops.get(rel["shop_id"])
    if not shop or shop["certification_status"] not in ("CERTIFIED", "PROBATION"):
        raise ApiError("ERR_SHOP_NOT_CERTIFIED", 422,
                       "Shop posture does not allow steering reinstatement")
    rel["status"] = "ACTIVE"
    rel["steering_enabled"] = _steering_for(shop, "ACTIVE")
    bump(rel)
    return ok(serialize(rel))


@bp.post("/network/insurer-relations/<rel_id>/terminate")
def terminate_relation(rel_id):
    require_roles("NetworkAdmin")
    rel = get_relation_or_404(rel_id)
    if rel["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only ACTIVE or SUSPENDED relations can be terminated")
    rel["status"] = "TERMINATED"
    rel["steering_enabled"] = False
    bump(rel)
    return ok(serialize(rel))

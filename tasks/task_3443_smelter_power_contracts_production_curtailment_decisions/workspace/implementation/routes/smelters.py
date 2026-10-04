"""Smelter onboarding, read, and the seven per-smelter list endpoints."""
from flask import Blueprint

from auth import require_roles
from constants import REGION_CODES, ROLES
from db import STORE, new_id, stamp_new
from envelope import ok_list, ok_object
from errors import raise_err
from serializers import (
    agreement_json,
    contract_json,
    hedge_json,
    labor_agreement_json,
    permit_json,
    production_plan_json,
    potline_json,
    smelter_json,
)
from util import as_enum, as_int, as_number, as_str, get_body, parse_pagination, req

bp = Blueprint("smelters", __name__, url_prefix="/smelter-ops")


def get_smelter_or_404(smelter_id):
    smelter = STORE["smelters"].get(smelter_id)
    if smelter is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    return smelter


@bp.post("/smelters")
@require_roles("PlatformAdmin")
def create_smelter():
    body = get_body()
    name = as_str(req(body, "name"), "name")
    region = as_enum(req(body, "region_code"), "region_code", REGION_CODES)
    capacity = as_number(req(body, "rated_capacity_tpd"), "rated_capacity_tpd")
    if capacity <= 0:
        raise_err("ERR_INVALID_REQUEST", "rated_capacity_tpd must be > 0.")
    headcount = as_int(req(body, "labor_headcount"), "labor_headcount")
    if headcount < 0:
        raise_err("ERR_INVALID_REQUEST", "labor_headcount must be >= 0.")
    rec = stamp_new(
        {
            "id": new_id(),
            "name": name,
            "region_code": region,
            "rated_capacity_tpd": capacity,
            "labor_headcount": headcount,
        }
    )
    STORE["smelters"][rec["id"]] = rec
    return ok_object(smelter_json(rec), 201)


@bp.get("/smelters/<smelter_id>")
@require_roles(*ROLES)
def get_smelter(smelter_id):
    return ok_object(smelter_json(get_smelter_or_404(smelter_id)))


def _list_child(smelter_id, store_key, serializer):
    get_smelter_or_404(smelter_id)
    limit, offset = parse_pagination()
    items = [r for r in STORE[store_key].values() if r.get("smelter_id") == smelter_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = items[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, len(items))


@bp.get("/smelters/<smelter_id>/potlines")
@require_roles(*ROLES)
def list_potlines(smelter_id):
    return _list_child(smelter_id, "potlines", potline_json)


@bp.get("/smelters/<smelter_id>/power-contracts")
@require_roles(*ROLES)
def list_power_contracts(smelter_id):
    return _list_child(smelter_id, "power_contracts", contract_json)


@bp.get("/smelters/<smelter_id>/hedge-positions")
@require_roles(*ROLES)
def list_hedge_positions(smelter_id):
    return _list_child(smelter_id, "hedge_positions", hedge_json)


@bp.get("/smelters/<smelter_id>/alumina-agreements")
@require_roles(*ROLES)
def list_alumina_agreements(smelter_id):
    return _list_child(smelter_id, "alumina_agreements", agreement_json)


@bp.get("/smelters/<smelter_id>/environmental-permits")
@require_roles(*ROLES)
def list_environmental_permits(smelter_id):
    return _list_child(smelter_id, "environmental_permits", permit_json)


@bp.get("/smelters/<smelter_id>/labor-agreements")
@require_roles(*ROLES)
def list_labor_agreements(smelter_id):
    return _list_child(smelter_id, "labor_agreements", labor_agreement_json)


@bp.get("/smelters/<smelter_id>/production-plans")
@require_roles(*ROLES)
def list_production_plans(smelter_id):
    return _list_child(smelter_id, "production_plans", production_plan_json)

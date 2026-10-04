"""Store registration, store fetch, and store-scoped SiteEvaluation and
PlacementAgreement create/list endpoints (PRD 3.1, 3.2)."""
from flask import Blueprint

import calc
from envelope import ok
from errors import ApiError
from serializers import ser_agreement, ser_evaluation, ser_store
from state import DB, base_entity
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("stores", __name__)

def _get_store(sid):
    s = DB["stores"].get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Store %s not found" % sid)
    return s


@bp.post("/cold-chain/stores")
def create_store():
    uid, role = auth()
    v = fields(body(), [
        ("name", "str", True, {}),
        ("region", "str", True, {}),
        ("demographic_index", "int", True, {"min": 0, "max": 100}),
        ("weekly_category_velocity_index", "int", True, {"min": 0, "max": 100}),
        ("competitor_density_index", "int", True, {"min": 0, "max": 100}),
        ("available_sqft", "int", True, {"gt0": True}),
        ("distance_miles_from_plant", "num", True, {"min": 0}),
    ])
    require_role(role, ["PlatformAdmin"])
    s = base_entity()
    s.update({
        "name": v["name"], "region": v["region"],
        "demographic_index": v["demographic_index"],
        "weekly_category_velocity_index": v["weekly_category_velocity_index"],
        "competitor_density_index": v["competitor_density_index"],
        "available_sqft": v["available_sqft"],
        "distance_miles_from_plant": v["distance_miles_from_plant"],
    })
    DB["stores"][s["id"]] = s
    return ok(ser_store(s), "object", 201)


@bp.get("/cold-chain/stores/<sid>")
def get_store(sid):
    auth()
    return ok(ser_store(_get_store(sid)), "object", 200)


@bp.post("/cold-chain/stores/<sid>/site-evaluations")
def create_evaluation(sid):
    uid, role = auth()
    v = fields(body(), [
        ("model_variant", "enum", True, {"values": ["DEMOGRAPHIC_LED", "VELOCITY_LED"]}),
        ("chiller_model", "enum", True, {"values": ["STANDARD", "COMPACT"]}),
        ("forecast_weekly_units", "num", True, {"gt0": True, "one_decimal": True}),
        ("allocated_sqft", "int", True, {"gt0": True}),
    ])
    require_role(role, ["PlacementManager"])
    store = _get_store(sid)
    foot = calc.footprint_score(v["allocated_sqft"])
    comp = calc.composite_score(v["model_variant"], store["demographic_index"],
                                store["weekly_category_velocity_index"], foot,
                                store["competitor_density_index"])
    quote = calc.install_quote(v["chiller_model"], v["allocated_sqft"],
                               store["distance_miles_from_plant"])
    payback = calc.payback_months(v["forecast_weekly_units"], quote)
    eligible = (comp >= calc.SCORE_ELIGIBILITY_MIN
                and payback is not None and payback <= calc.PAYBACK_MAX_MONTHS)
    e = base_entity()
    e.update({
        "store_id": sid,
        "model_variant": v["model_variant"],
        "chiller_model": v["chiller_model"],
        "forecast_weekly_units": v["forecast_weekly_units"],
        "allocated_sqft": v["allocated_sqft"],
        "footprint_score": foot,
        "composite_score": float(comp),
        "install_quote_cents": quote,
        "payback_months": (float(payback) if payback is not None else None),
        "verdict": "ELIGIBLE" if eligible else "INELIGIBLE",
    })
    DB["evaluations"][e["id"]] = e
    return ok(ser_evaluation(e), "object", 201)


@bp.get("/cold-chain/stores/<sid>/site-evaluations")
def list_evaluations(sid):
    auth()
    limit, offset = pagination()
    _get_store(sid)
    items = [e for e in DB["evaluations"].values() if e["store_id"] == sid]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_evaluation(e) for e in sliced], "array", 200, meta)


@bp.post("/cold-chain/stores/<sid>/placement-agreements")
def create_agreement(sid):
    uid, role = auth()
    v = fields(body(), [
        ("allocated_sqft", "int", True, {"gt0": True}),
        ("max_capex_cents", "int", True, {"gt0": True}),
        ("term_months", "int", True, {"min": 1, "max": 120}),
    ])
    require_role(role, ["PlacementManager"])
    _get_store(sid)
    a = base_entity()
    a.update({
        "store_id": sid,
        "allocated_sqft": v["allocated_sqft"],
        "max_capex_cents": v["max_capex_cents"],
        "term_months": v["term_months"],
        "status": "PROPOSED",
        "signed_at": None,
        "terminated_at": None,
    })
    DB["agreements"][a["id"]] = a
    return ok(ser_agreement(a), "object", 201)


@bp.get("/cold-chain/stores/<sid>/placement-agreements")
def list_agreements(sid):
    auth()
    limit, offset = pagination()
    _get_store(sid)
    items = [a for a in DB["agreements"].values() if a["store_id"] == sid]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_agreement(a) for a in sliced], "array", 200, meta)

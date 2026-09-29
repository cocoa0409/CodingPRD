"""Stock-keeping-unit endpoints (PRD 3.2) and the redesign projection (PRD 3.9)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, VERIFIER, endpoint, must,
                  new_row, require_producer_owner, touch)
from envelope import ok, ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("skus", __name__)


def parse_component(raw, label):
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "%s must be a JSON object." % label)
    material = v.req_enum(raw, "material_type", v.MATERIAL_TYPES)
    weight = v.req_decimal(raw, "unit_weight_grams", 2, minimum=0)
    recyclability = v.req_enum(raw, "recyclability_class", v.RECYCLABILITY_CLASSES)
    pcr = v.req_int(raw, "pcr_content_pct", minimum=0, maximum=100)
    reusable = v.req_bool(raw, "is_reusable")
    return {
        "material_type": material,
        "unit_weight_grams": weight,
        "recyclability_class": recyclability,
        "pcr_content_pct": pcr,
        "is_reusable": reusable,
    }


def next_seq(sku):
    highest = 0
    for comp in sku["components"]:
        if int(comp["component_seq"]) > highest:
            highest = int(comp["component_seq"])
    return highest + 1


@bp.post("/epr/skus")
@endpoint([OFFICER])
def create_sku():
    body = v.body()
    producer_id = v.req_str(body, "producer_id")
    gtin = v.req_str(body, "gtin")
    name = v.req_str(body, "name")
    category = v.req_enum(body, "product_category", v.PRODUCT_CATEGORIES)
    units = v.req_int(body, "units_sold_annual_estimate", minimum=0)
    must("producers", producer_id)
    require_producer_owner(producer_id)
    for existing in store.values("skus"):
        if existing["producer_id"] == producer_id and existing["gtin"] == gtin:
            fail("ERR_INVALID_REQUEST", "gtin '%s' already exists for this producer." % gtin)
    row = new_row(
        "skus",
        {
            "producer_id": producer_id,
            "gtin": gtin,
            "name": name,
            "product_category": category,
            "units_sold_annual_estimate": units,
            "components": [],
            "unit_packaging_weight_grams": calc.ZERO_GRAMS,
            "status": "DRAFT",
            "revision_count": 0,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/skus/<sid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def get_sku(sid):
    return ok_entity(must("skus", sid))


@bp.get("/epr/skus")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def list_skus():
    producer_id = str_filter("producer_id")
    status = enum_filter("status", v.SKU_STATUSES)
    category = enum_filter("product_category", v.PRODUCT_CATEGORIES)
    rows = store.values("skus")
    if producer_id is not None:
        rows = [r for r in rows if r["producer_id"] == producer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["product_category"] == category]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/skus/<sid>/components")
@endpoint([OFFICER])
def append_component(sid):
    body = v.body()
    component = parse_component(body, "The request body")
    sku = must("skus", sid)
    require_producer_owner(sku["producer_id"])
    component["component_seq"] = next_seq(sku)
    component["status"] = "ACTIVE"
    sku["components"].append(component)
    calc.recompute_sku_weight(sku)
    touch(sku)
    return ok_entity(sku)


@bp.post("/epr/skus/<sid>/activate")
@endpoint([OFFICER])
def activate_sku(sid):
    sku = must("skus", sid)
    require_producer_owner(sku["producer_id"])
    if sku["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The stock keeping unit is not in DRAFT.")
    if not calc.active_components(sku):
        fail("ERR_SKU_HAS_NO_COMPONENTS")
    sku["status"] = "ACTIVE"
    calc.recompute_sku_weight(sku)
    touch(sku)
    producer = store.get("producers", sku["producer_id"])
    calc.recompute_producer_weight(producer)
    calc.mark_determination_stale(producer)
    return ok_entity(sku)


@bp.post("/epr/skus/<sid>/revise-packaging")
@endpoint([OFFICER])
def revise_packaging(sid):
    body = v.body()
    raw_components = v.req_list(body, "components", allow_empty=False)
    v.req_str(body, "reason")
    replacements = [
        parse_component(raw, "components[%d]" % index)
        for index, raw in enumerate(raw_components)
    ]
    sku = must("skus", sid)
    require_producer_owner(sku["producer_id"])
    if sku["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The stock keeping unit is not ACTIVE.")
    for comp in sku["components"]:
        if comp["status"] == "ACTIVE":
            comp["status"] = "SUPERSEDED"
    seq = next_seq(sku)
    for comp in replacements:
        comp["component_seq"] = seq
        comp["status"] = "ACTIVE"
        sku["components"].append(comp)
        seq += 1
    calc.recompute_sku_weight(sku)
    sku["revision_count"] = int(sku["revision_count"]) + 1
    touch(sku)
    producer = store.get("producers", sku["producer_id"])
    calc.recompute_producer_weight(producer)
    calc.mark_determination_stale(producer)
    return ok_entity(sku)


@bp.post("/epr/skus/<sid>/redesign-projection")
@endpoint([OFFICER, REGULATOR])
def redesign_projection(sid):
    body = v.body()
    program_id = v.req_str(body, "state_program_id")
    schedule_id = v.req_str(body, "fee_schedule_id")
    tier_basis = v.req_decimal(body, "tier_basis_kg", 3, minimum=0)
    units_basis = v.req_enum(body, "units_basis", v.UNITS_BASES)
    projected_units = v.opt_int(body, "projected_units", minimum=0)
    raw_components = v.req_list(body, "candidate_components")
    candidates = [
        parse_component(raw, "candidate_components[%d]" % index)
        for index, raw in enumerate(raw_components)
    ]
    if units_basis == "PROJECTED_UNITS" and projected_units is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'projected_units' is required when units_basis is PROJECTED_UNITS.",
        )
    sku = must("skus", sid)
    program = must("state_programs", program_id)
    schedule = must("fee_schedules", schedule_id)
    require_producer_owner(sku["producer_id"])
    if units_basis == "BASELINE_UNITS":
        units = int(sku["units_sold_annual_estimate"])
    else:
        units = int(projected_units)
    payload = calc.redesign_projection(
        sku, program, schedule, tier_basis, units, candidates
    )
    return ok(payload)

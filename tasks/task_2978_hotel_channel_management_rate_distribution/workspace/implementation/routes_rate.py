"""Rate plans, derivation chains and repricing (PRD 3.2)."""

from flask import Blueprint

import calc
import cascade
import guards
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import get, put, rows, where

bp = Blueprint("rate", __name__)

INTERNAL = shape.INTERNAL_ROLES
RATE_CLASSES = ("PUBLIC", "NEGOTIATED", "OPAQUE", "PACKAGE")
OFFSET_KINDS = ("NONE", "PERCENT", "AMOUNT")
PLAN_STATES = ("DRAFT", "ACTIVE", "CLOSED")


@bp.post("/distribution/properties/<pid>/rate-plans")
def create_rate_plan(pid):
    shape.auth("RevenueManager")
    prop = must("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    body = shape.body_obj()
    code = shape.v_string(body, "code", required=True, minlen=2, maxlen=16,
                          pattern=r"^[A-Z0-9-]+$")
    rate_class = shape.v_enum(body, "rate_class", RATE_CLASSES, required=True)
    floor = shape.v_int(body, "floor_amount_cents", required=True, lo=1000, hi=1000000)
    ceiling = shape.v_int(body, "ceiling_amount_cents", required=True, lo=1000,
                          hi=1000000)
    base = shape.v_int(body, "base_amount_cents", lo=1000, hi=1000000)
    parent_id = shape.v_string(body, "parent_rate_plan_id")
    offset_kind = shape.v_enum(body, "offset_kind", OFFSET_KINDS, default="NONE")
    offset_bp = shape.v_int(body, "offset_bp", lo=-5000, hi=5000)
    offset_amount = shape.v_int(body, "offset_amount_cents", lo=-500000, hi=500000)
    inclusion = shape.v_int(body, "package_inclusion_cents", default=0, lo=0, hi=200000)
    member_only = shape.v_bool(body, "member_only", default=False)
    account_code = shape.v_string(body, "negotiated_account_code", minlen=2, maxlen=16,
                                 pattern=r"^[A-Z0-9-]+$")
    if ceiling < floor:
        fail("ERR_INVALID_REQUEST",
             "Field 'ceiling_amount_cents' must be at least 'floor_amount_cents'.")
    if parent_id is None:
        if base is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'base_amount_cents' is required for a standalone plan.")
    else:
        if base is not None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'base_amount_cents' is forbidden on a derived plan.")
    if offset_kind == "PERCENT" and offset_bp is None:
        fail("ERR_INVALID_REQUEST", "Field 'offset_bp' is required for a PERCENT offset.")
    if offset_kind == "AMOUNT" and offset_amount is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'offset_amount_cents' is required for an AMOUNT offset.")
    if rate_class == "NEGOTIATED" and account_code is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'negotiated_account_code' is required for a NEGOTIATED plan.")
    parent = None
    if parent_id is not None:
        parent = get("rate_plans", parent_id)
        if parent is None:
            fail("ERR_RATE_PLAN_NOT_FOUND")
    for existing in where("rate_plans", property_id=prop["id"]):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Rate plan code %s already exists on this property." % code)
    depth = calc.derivation_depth(parent)
    if depth > calc.MAX_DERIVATION_DEPTH:
        fail("ERR_DERIVATION_DEPTH_EXCEEDED")
    rec = store.base_record()
    rec.update({
        "property_id": prop["id"],
        "code": code,
        "rate_class": rate_class,
        "parent_rate_plan_id": parent_id,
        "base_amount_cents": base,
        "offset_kind": offset_kind,
        "offset_bp": offset_bp,
        "offset_amount_cents": offset_amount,
        "floor_amount_cents": floor,
        "ceiling_amount_cents": ceiling,
        "package_inclusion_cents": inclusion,
        "member_only": member_only,
        "negotiated_account_code": account_code,
        "plan_state": "DRAFT",
        "derivation_depth": depth,
        "resolved_base_amount_cents": None,
    })
    rec["resolved_base_amount_cents"] = calc.resolve_base_amount(rec)
    put("rate_plans", rec)
    return created(serialize.rate_plan_out(rec))


@bp.post("/distribution/rate-plans/<rid>/activate")
def activate_rate_plan(rid):
    shape.auth("RevenueManager")
    plan = must("rate_plans", rid, "ERR_RATE_PLAN_NOT_FOUND")
    if plan["plan_state"] != "DRAFT":
        fail("ERR_RATE_PLAN_STATE_INVALID")
    if plan["parent_rate_plan_id"] is not None:
        parent = get("rate_plans", plan["parent_rate_plan_id"])
        if parent is None or parent["plan_state"] != "ACTIVE":
            fail("ERR_RATE_PLAN_STATE_INVALID")
    plan["plan_state"] = "ACTIVE"
    calc.rederive_family(plan)
    store.bump(plan)
    return ok(serialize.rate_plan_out(plan))


@bp.patch("/distribution/rate-plans/<rid>")
def reprice_rate_plan(rid):
    shape.auth("RevenueManager")
    plan = must("rate_plans", rid, "ERR_RATE_PLAN_NOT_FOUND")
    body = shape.body_obj()
    echo = shape.v_int(body, "expected_rate_plan_version", required=True, lo=0)
    base = shape.v_int(body, "base_amount_cents", lo=1000, hi=1000000, nullable=False)
    offset_bp = shape.v_int(body, "offset_bp", lo=-5000, hi=5000, nullable=False)
    offset_amount = shape.v_int(body, "offset_amount_cents", lo=-500000, hi=500000,
                                nullable=False)
    floor = shape.v_int(body, "floor_amount_cents", lo=1000, hi=1000000, nullable=False)
    ceiling = shape.v_int(body, "ceiling_amount_cents", lo=1000, hi=1000000,
                          nullable=False)
    inclusion = shape.v_int(body, "package_inclusion_cents", lo=0, hi=200000,
                            nullable=False)
    resulting_floor = floor if floor is not None else plan["floor_amount_cents"]
    resulting_ceiling = ceiling if ceiling is not None else plan["ceiling_amount_cents"]
    if resulting_ceiling < resulting_floor:
        fail("ERR_INVALID_REQUEST",
             "Field 'ceiling_amount_cents' must be at least 'floor_amount_cents'.")
    if echo != plan["version"]:
        fail("ERR_STALE_RATE_PLAN_VERSION")
    if plan["plan_state"] != "ACTIVE":
        fail("ERR_RATE_PLAN_STATE_INVALID")
    if base is not None:
        plan["base_amount_cents"] = base
    if offset_bp is not None:
        plan["offset_bp"] = offset_bp
    if offset_amount is not None:
        plan["offset_amount_cents"] = offset_amount
    if floor is not None:
        plan["floor_amount_cents"] = floor
    if ceiling is not None:
        plan["ceiling_amount_cents"] = ceiling
    if inclusion is not None:
        plan["package_inclusion_cents"] = inclusion
    calc.rederive_family(plan)
    cascade.rate_batch(plan)
    store.bump(plan)
    return ok(serialize.rate_plan_out(plan))


@bp.post("/distribution/rate-plans/<rid>/close")
def close_rate_plan(rid):
    shape.auth("RevenueManager")
    plan = must("rate_plans", rid, "ERR_RATE_PLAN_NOT_FOUND")
    if plan["plan_state"] != "ACTIVE":
        fail("ERR_RATE_PLAN_STATE_INVALID")
    plan["plan_state"] = "CLOSED"
    for mapping in refs.mappings_of_plan(plan["id"]):
        if mapping["mapping_state"] in ("DRAFT", "VERIFIED", "ERRORED"):
            cascade.disable_mapping(mapping)
    store.bump(plan)
    return ok(serialize.rate_plan_out(plan))


@bp.get("/distribution/rate-plans")
def list_rate_plans():
    shape.auth(*INTERNAL)
    property_id = shape.q_id("property_id")
    parent_id = shape.q_id("parent_rate_plan_id")
    rate_class = shape.q_enum("rate_class", RATE_CLASSES)
    plan_state = shape.q_enum("plan_state", PLAN_STATES)
    records = rows("rate_plans")
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    if parent_id is not None:
        records = [r for r in records if r["parent_rate_plan_id"] == parent_id]
    if rate_class is not None:
        records = [r for r in records if r["rate_class"] == rate_class]
    if plan_state is not None:
        records = [r for r in records if r["plan_state"] == plan_state]
    return page(serialize.rate_plan_out, records)


@bp.get("/distribution/rate-plans/<rid>")
def read_rate_plan(rid):
    shape.auth(*INTERNAL)
    plan = must("rate_plans", rid, "ERR_RATE_PLAN_NOT_FOUND")
    return ok(serialize.rate_plan_out(plan))

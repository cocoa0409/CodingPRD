"""Seasoning batch endpoints: create, start-bake, qa-release (PRD 3.6)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize, check_sod
from errors import err
from validate import paginate_params, parse_body, validate

bp = Blueprint("seasoning", __name__)

OIL_TYPES = ["SOYBEAN", "CANOLA", "FLAXSEED"]


@bp.route("/foundry/seasoning-batches", methods=["POST"])
def create_seasoning_batch():
    _uid, role = authenticate()
    authorize(role, ["SeasoningLead"])
    vals = validate(
        parse_body(),
        [
            {"name": "production_order_id", "kind": "string"},
            {"name": "oil_type", "kind": "enum", "values": OIL_TYPES},
            {"name": "coating_count", "kind": "integer", "ge": 1, "le": 3},
            {"name": "planned_bake_start", "kind": "datetime"},
            {"name": "planned_bake_end", "kind": "datetime"},
            {"name": "unit_ids", "kind": "str_array"},
        ],
    )
    if vals["planned_bake_end"] <= vals["planned_bake_start"]:
        raise err("ERR_INVALID_REQUEST", "planned_bake_end must be > planned_bake_start")
    order = domain.get_or_404("orders", vals["production_order_id"])
    units = [domain.get_or_404("units", u) for u in vals["unit_ids"]]
    if order["state"] not in ("POURING", "FINISHING", "SEASONING"):
        raise err(
            "ERR_INVALID_STATE_TRANSITION", "order is not in POURING, FINISHING or SEASONING"
        )
    for u in units:
        if u["state"] != "FINISHED":
            raise err("ERR_INVALID_STATE_TRANSITION", "every unit must be FINISHED")
    _idx, _tier, posture = domain.order_derived(order)
    if posture == "FROZEN":
        raise err("ERR_ORDER_FROZEN", "order posture is FROZEN")
    if posture == "RESTRICTED":
        raise err("ERR_ORDER_RESTRICTED", "order posture is RESTRICTED")

    unit_count = len(vals["unit_ids"])
    s1, e1 = vals["planned_bake_start"], vals["planned_bake_end"]
    overlapping_load = 0
    for sb in store.db["seasoning"].values():
        if sb["state"] not in ("COATING", "BAKING"):
            continue
        s2, e2 = sb["planned_bake_start"], sb["planned_bake_end"]
        if s1 < e2 and s2 < e1:
            overlapping_load += sb["unit_count"]
    if unit_count + overlapping_load > calc.OVEN_CAPACITY:
        raise err("ERR_OVEN_CAPACITY_EXCEEDED", "overlapping batches exceed oven capacity 12")

    if unit_count == 0 or unit_count > calc.OVEN_CAPACITY:
        raise err("ERR_UNITS_NOT_SAME_ORDER", "unit_ids must be non-empty and at most 12")
    for u in units:
        if u["production_order_id"] != order["id"]:
            raise err("ERR_UNITS_NOT_SAME_ORDER", "unit belongs to a different order")

    ent = store.make_entity()
    ent.update(
        {
            "production_order_id": order["id"],
            "oil_type": vals["oil_type"],
            "coating_count": vals["coating_count"],
            "unit_ids": list(vals["unit_ids"]),
            "unit_count": unit_count,
            "planned_bake_start": s1,
            "planned_bake_end": e1,
            "oven_id": "OVEN_1",
            "state": "COATING",
            "actual_bake_temp_f": None,
            "oil_lot_number": None,
            "coa_reference": None,
            "bake_recorded_by": None,
            "bake_duration_min": None,
            "cure_score": None,
            "food_safety_verified": None,
            "released_by": None,
        }
    )
    store.db["seasoning"][ent["id"]] = ent

    seen = set()
    for u in units:
        if u["id"] in seen or u["state"] != "FINISHED":
            continue
        seen.add(u["id"])
        u["state"] = "SEASONING_QUEUED"
        u["seasoning_batch_id"] = ent["id"]
        store.touch(u)

    if order["state"] in ("POURING", "FINISHING"):
        order["state"] = "SEASONING"
    store.touch(order)
    return envelope.success(serialize.seasoning_batch(ent), status=201)


@bp.route("/foundry/seasoning-batches", methods=["GET"])
def list_seasoning_batches():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["seasoning"].values())
    order_id = request.args.get("production_order_id")
    state = request.args.get("state")
    if order_id is not None:
        items = [s for s in items if s["production_order_id"] == order_id]
    if state is not None:
        items = [s for s in items if s["state"] == state]
    return envelope.list_payload(items, serialize.seasoning_batch, limit, offset)


@bp.route("/foundry/seasoning-batches/<sid>", methods=["GET"])
def get_seasoning_batch(sid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    sb = domain.get_or_404("seasoning", sid)
    return envelope.success(serialize.seasoning_batch(sb))


@bp.route("/foundry/seasoning-batches/<sid>/start-bake", methods=["POST"])
def start_bake(sid):
    uid, role = authenticate()
    authorize(role, ["SeasoningLead"])
    vals = validate(
        parse_body(),
        [
            {"name": "actual_bake_temp_f", "kind": "number"},
            {"name": "oil_lot_number", "kind": "string", "nonempty": True},
            {"name": "coa_reference", "kind": "string", "nonempty": True},
        ],
    )
    sb = domain.get_or_404("seasoning", sid)
    if sb["state"] != "COATING":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not COATING")
    sb["actual_bake_temp_f"] = vals["actual_bake_temp_f"]
    sb["oil_lot_number"] = vals["oil_lot_number"]
    sb["coa_reference"] = vals["coa_reference"]
    sb["bake_recorded_by"] = uid
    sb["state"] = "BAKING"
    store.touch(sb)
    return envelope.success(serialize.seasoning_batch(sb))


@bp.route("/foundry/seasoning-batches/<sid>/qa-release", methods=["POST"])
def qa_release(sid):
    uid, role = authenticate()
    authorize(role, ["QualityInspector"])
    sb = domain.try_get("seasoning", sid)
    if sb is not None:
        check_sod(uid, sb["bake_recorded_by"])
    vals = validate(
        parse_body(),
        [
            {"name": "bake_duration_min", "kind": "integer"},
            {"name": "food_safety_verified", "kind": "boolean"},
            {"name": "decision", "kind": "enum", "values": ["RELEASE", "FAIL"]},
        ],
    )
    if sb is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"seasoning batch not found: {sid}")
    if sb["state"] != "BAKING":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not BAKING")

    score = calc.cure_score(sb["oil_type"], sb["actual_bake_temp_f"], vals["bake_duration_min"])

    if vals["decision"] == "RELEASE":
        if vals["food_safety_verified"] is not True:
            raise err("ERR_FOOD_SAFETY_INCOMPLETE", "food_safety_verified must be true")
        if score < calc.CURE_RELEASE_THRESHOLD:
            raise err("ERR_CURE_PROFILE_VIOLATION", "cure_score below 70")

    sb["bake_duration_min"] = vals["bake_duration_min"]
    sb["food_safety_verified"] = vals["food_safety_verified"]
    sb["cure_score"] = score
    sb["released_by"] = uid

    order = store.db["orders"][sb["production_order_id"]]
    if vals["decision"] == "RELEASE":
        sb["state"] = "RELEASED"
        transitioned = 0
        for unit_id in sb["unit_ids"]:
            u = store.db["units"].get(unit_id)
            if u is not None and u["state"] == "SEASONING_QUEUED":
                u["state"] = "SEASONED"
                store.touch(u)
                transitioned += 1
        order["good_units"] += transitioned
        product = store.db["products"][order["product_id"]]
        rec = domain.inventory_for_product(product["id"])
        if rec is not None and transitioned:
            rec["on_hand_units"] += transitioned
            store.touch(rec)
    else:
        sb["state"] = "FAILED"
        for unit_id in sb["unit_ids"]:
            u = store.db["units"].get(unit_id)
            if u is not None and u["state"] == "SEASONING_QUEUED":
                u["state"] = "FINISHED"
                u["seasoning_batch_id"] = None
                store.touch(u)
    store.touch(sb)
    return envelope.success(serialize.seasoning_batch(sb))

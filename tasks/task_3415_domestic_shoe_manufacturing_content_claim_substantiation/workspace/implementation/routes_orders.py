"""CustomOrder endpoints (PRD 3.7): submit, list, get, accept, schedule,
cancel, fulfill."""
from flask import Blueprint, request

import calcs
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_int, opt_str

bp = Blueprint("orders", __name__)


def get_order(oid):
    o = DB["orders"].get(oid)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "custom order id does not resolve")
    return o


@bp.post("/footwear/custom-orders")
@require_roles("CustomProgramCustomer", "ProductionPlanner")
def create_order(_uid, _role):
    b = body()
    # Family 3 (identity scoping): customer callers must own buyer_ref.
    if _role == "CustomProgramCustomer" and b.get("buyer_ref") != _uid:
        raise ApiError(
            "ERR_BUYER_REF_MISMATCH",
            "a CustomProgramCustomer may submit orders only with buyer_ref equal to X-User-ID",
        )
    # Family 4 (existence) precedes family 5 (schema).
    mid = b.get("model_id")
    if mid is not None and mid not in DB["models"]:
        raise ApiError("ERR_MODEL_NOT_FOUND", "model id does not resolve")
    mid = req_str(b, "model_id")
    buyer = req_str(b, "buyer_ref")
    colorway = req_str(b, "colorway")
    size = req_str(b, "size")
    monogram = opt_str(b, "monogram")
    qty = req_int(b, "quantity_units", min_v=1, max_v=constants.MAX_CUSTOM_ORDER_UNITS)
    model = DB["models"][mid]
    # Family 6 (state) then family 7 (regulatory).
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", "the model must be ACTIVE")
    if model["production_policy"] == "IMPORT_ONLY":
        raise ApiError(
            "ERR_CUSTOM_REQUIRES_DOMESTIC",
            "the custom program is domestic-only; the model is IMPORT_ONLY",
        )
    o = base_fields()
    o.update({
        "model_id": mid,
        "buyer_ref": buyer,
        "colorway": colorway,
        "size": size,
        "monogram": monogram,
        "quantity_units": qty,
        "quoted_price_cents": None,
        "production_run_id": None,
        "production_status": "SUBMITTED",
    })
    DB["orders"][o["id"]] = o
    return ok_obj(serializers.pub(o), 201)


@bp.get("/footwear/custom-orders")
@require_roles(*constants.ALL_ROLES)
def list_orders(_uid, _role):
    items = sorted_items(DB["orders"])
    mid = request.args.get("model_id")
    rid = request.args.get("production_run_id")
    status = request.args.get("production_status")
    buyer = request.args.get("buyer_ref")
    if mid is not None:
        items = [o for o in items if o["model_id"] == mid]
    if rid is not None:
        items = [o for o in items if o["production_run_id"] == rid]
    if status is not None:
        items = [o for o in items if o["production_status"] == status]
    if buyer is not None:
        items = [o for o in items if o["buyer_ref"] == buyer]
    return list_response([serializers.pub(o) for o in items])


@bp.get("/footwear/custom-orders/<oid>")
@require_roles(*constants.ALL_ROLES)
def get_one_order(oid, _uid, _role):
    return ok_obj(serializers.pub(get_order(oid)))


@bp.post("/footwear/custom-orders/<oid>/accept")
@require_roles("ProductionPlanner")
def accept_order(oid, _uid, _role):
    o = get_order(oid)
    if o["production_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "order must be SUBMITTED to accept")
    model = DB["models"][o["model_id"]]
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", "the order's model must be ACTIVE")
    o["quoted_price_cents"] = calcs.custom_order_price(o, model)
    o["production_status"] = "ACCEPTED"
    touch(o)
    return ok_obj(serializers.pub(o))


@bp.post("/footwear/custom-orders/<oid>/schedule")
@require_roles("ProductionPlanner")
def schedule_order(oid, _uid, _role):
    o = get_order(oid)
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    rid = b.get("production_run_id")
    if rid is not None and rid not in DB["runs"]:
        raise ApiError("ERR_RUN_NOT_FOUND", "production run id does not resolve")
    rid = req_str(b, "production_run_id")
    run = DB["runs"][rid]
    # Family 6 (state).
    if o["production_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "order must be ACCEPTED to schedule")
    if run["status"] != "MATERIAL_RESERVED":
        raise ApiError("ERR_RUN_NOT_READY", "the run must be MATERIAL_RESERVED")
    # Family 7 (regulatory): the custom program never runs overseas.
    factory = DB["factories"][run["factory_id"]]
    if factory["location_type"] != "DOMESTIC":
        raise ApiError(
            "ERR_CUSTOM_REQUIRES_DOMESTIC",
            "custom orders may be scheduled only onto runs at DOMESTIC factories",
        )
    # Family 9 (structural): run type, then model match.
    if run["run_type"] != "CUSTOM_BATCH":
        raise ApiError("ERR_NOT_A_CUSTOM_RUN", "the run's run_type must be CUSTOM_BATCH")
    if run["model_id"] != o["model_id"]:
        raise ApiError("ERR_MODEL_MISMATCH", "the run's model_id must equal the order's model_id")
    # Family 11 (fiscal): order slots, equality allowed.
    used = sum(
        x["quantity_units"] for x in DB["orders"].values()
        if x["production_run_id"] == run["id"]
        and x["production_status"] in ("SCHEDULED", "IN_PRODUCTION")
    )
    if used + o["quantity_units"] > run["planned_units"]:
        raise ApiError(
            "ERR_RUN_ORDER_CAPACITY_EXCEEDED",
            "the run's scheduled plus in-production order units would exceed planned_units",
        )
    o["production_run_id"] = run["id"]
    o["production_status"] = "SCHEDULED"
    touch(o)
    return ok_obj(serializers.pub(o))


@bp.post("/footwear/custom-orders/<oid>/cancel")
@require_roles("ProductionPlanner", "CustomProgramCustomer")
def cancel_order(oid, _uid, _role):
    o = get_order(oid)
    # Family 3 (identity scoping) on the resolved order.
    if _role == "CustomProgramCustomer" and o["buyer_ref"] != _uid:
        raise ApiError(
            "ERR_BUYER_REF_MISMATCH",
            "a CustomProgramCustomer may cancel only orders whose buyer_ref equals X-User-ID",
        )
    if o["production_status"] not in ("SUBMITTED", "ACCEPTED", "SCHEDULED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only SUBMITTED, ACCEPTED, or SCHEDULED orders can be cancelled",
        )
    # Cancelling a SCHEDULED order frees its slot; slot accounting is derived,
    # so no counter write (production_run_id is retained per the state machine).
    o["production_status"] = "CANCELLED"
    touch(o)
    return ok_obj(serializers.pub(o))


@bp.post("/footwear/custom-orders/<oid>/fulfill")
@require_roles("ProductionPlanner")
def fulfill_order(oid, _uid, _role):
    o = get_order(oid)
    if o["production_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "order must be IN_PRODUCTION to fulfill")
    run = DB["runs"].get(o["production_run_id"])
    if run is None or run["status"] != "COMPLETED":
        raise ApiError("ERR_RUN_NOT_COMPLETED", "the linked run must be COMPLETED")
    o["production_status"] = "FULFILLED"
    touch(o)
    return ok_obj(serializers.pub(o))

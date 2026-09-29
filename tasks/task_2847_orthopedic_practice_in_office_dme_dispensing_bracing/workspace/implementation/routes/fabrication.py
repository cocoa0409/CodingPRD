"""Custom fabrication: supplier events, the fitter's check and turnaround scoring."""
from flask import Blueprint, request

import guards
from calc import final_score, projected_score, refresh_supplier_rollup
from common import (authorize, body_json, enum_arg, fail, need_enum, now,
                    opt_str, paginate, respond_list, respond_object, whole_days)
from store import (FAB_EVENTS, FAB_STATUSES, FITTING_CHECK_OUTCOMES, db,
                   fab_order_json, lookup, sort_created, touch)

bp = Blueprint("fabrication", __name__)

FAB_READ_ROLES = ["PracticeAdmin", "InventoryManager", "DmeFitter"]
ADJUSTMENT_ROUND_LIMIT = 2

ACCEPT_ORDER_FROM = ("SUBMITTED", "ADJUSTMENT_REQUESTED", "SUPPLIER_HOLD")


@bp.get("/dme/custom-fab-orders/<order_id>")
def get_fab_order(order_id):
    authorize(FAB_READ_ROLES)
    row = lookup("fab_orders", order_id, "ERR_FAB_ORDER_NOT_FOUND")
    return respond_object(fab_order_json(row), 200)


@bp.get("/dme/custom-fab-orders")
def list_fab_orders():
    authorize(FAB_READ_ROLES)
    rows = list(db["fab_orders"].values())
    for field in ("encounter_id", "supplier_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = enum_arg("status", FAB_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, pagination = paginate(sort_created(rows))
    return respond_list([fab_order_json(r) for r in page], pagination, 200)


@bp.post("/dme/custom-fab-orders/<order_id>/fabrication-events")
def create_fabrication_event(order_id):
    authorize(["InventoryManager"])
    body = body_json()
    event = need_enum(body, "event", FAB_EVENTS)
    order = lookup("fab_orders", order_id, "ERR_FAB_ORDER_NOT_FOUND")
    supplier = db["suppliers"].get(order["supplier_id"])
    status = order["status"]

    if event == "ACCEPT_ORDER":
        if status not in ACCEPT_ORDER_FROM:
            fail("ERR_INVALID_FAB_ORDER_STATE")
        # Starting fresh work, and lifting a hold, both demand a clean supplier;
        # resuming a rework round only demands that the hold be off.
        if status in ("SUBMITTED", "SUPPLIER_HOLD"):
            guards.guard_supplier_standards(supplier)
        guards.guard_supplier_quality(supplier)
        order["status"] = "IN_FABRICATION"
        touch(order)
        return respond_object(fab_order_json(order), 201)

    if status != "IN_FABRICATION":
        fail("ERR_INVALID_FAB_ORDER_STATE")
    guards.guard_supplier_quality(supplier)
    if order["first_delivered_at"] is None:
        delivered_at = now()
        order["first_delivered_at"] = delivered_at
        days = whole_days(order["submitted_at"], delivered_at)
        order["first_delivery_days"] = days
        order["projected_turnaround_score"] = projected_score(
            days, order["promised_turnaround_days_snapshot"])
    order["status"] = "READY_FOR_FITTING"
    touch(order)
    return respond_object(fab_order_json(order), 201)


@bp.post("/dme/custom-fab-orders/<order_id>/fitting-check")
def create_fitting_check(order_id):
    user_id, _ = authorize(["DmeFitter"])
    body = body_json()
    outcome = need_enum(body, "outcome", FITTING_CHECK_OUTCOMES)
    opt_str(body, "note")
    order = lookup("fab_orders", order_id, "ERR_FAB_ORDER_NOT_FOUND")
    fitter = db["fitters"].get(user_id)
    encounter = db["encounters"].get(order["encounter_id"])
    product = db["products"].get(encounter["product_id"]) if encounter else None
    status = order["status"]

    required_from = "SUPPLIER_HOLD" if outcome == "CANCEL" else "READY_FOR_FITTING"
    if status != required_from:
        fail("ERR_INVALID_FAB_ORDER_STATE")
    guards.guard_fitter_credential(fitter)
    if product is not None:
        guards.guard_fitter_privilege(fitter, product)

    if outcome == "ACCEPT":
        accepted_at = now()
        order["accepted_at"] = accepted_at
        elapsed = whole_days(order["submitted_at"], accepted_at)
        order["total_elapsed_days"] = elapsed
        order["final_turnaround_score"] = final_score(
            elapsed, order["promised_turnaround_days_snapshot"],
            order["adjustment_rounds"])
        order["status"] = "ACCEPTED"
        touch(order)
        supplier = db["suppliers"].get(order["supplier_id"])
        if supplier is not None:
            refresh_supplier_rollup(supplier)
        return respond_object(fab_order_json(order), 201)

    if outcome == "REQUEST_ADJUSTMENT":
        if order["adjustment_rounds"] >= ADJUSTMENT_ROUND_LIMIT:
            fail("ERR_ADJUSTMENT_LIMIT_REACHED")
        order["adjustment_rounds"] += 1
        order["status"] = "ADJUSTMENT_REQUESTED"
        touch(order)
        return respond_object(fab_order_json(order), 201)

    order["status"] = "CANCELLED"
    touch(order)
    if encounter is not None:
        if encounter["clinical_status"] == "AWAITING_DEVICE":
            encounter["clinical_status"] = "DOCUMENTED"
        encounter["compliance_hold"] = False
        encounter["hold_reason"] = None
        touch(encounter)
    return respond_object(fab_order_json(order), 201)

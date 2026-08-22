"""Refurbishment orders: quote, approve, reject, complete."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered
from errors import ApiError
from guard import (auth, lookup, get_body, resolve_fk, v_string, v_int, v_number,
                   v_enum, require_branch_owner)
from response import success, created, paginate

bp = Blueprint("refurb", __name__)

SCOPES = ("COSMETIC", "STANDARD", "FULL")
GRADES = ("A", "B", "C", "D")


@bp.post("/refurbishment-orders")
def create_order():
    user_id, role = auth("BranchOps")
    body = get_body()

    # rank 4 -- body foreign keys in the declared field order
    unit = resolve_fk(body, "unit_id", store.units, "ERR_UNIT_NOT_FOUND")
    branch = resolve_fk(body, "branch_id", store.branches, "ERR_BRANCH_NOT_FOUND")
    assessment = resolve_fk(body, "damage_assessment_id", store.assessments, "ERR_ASSESSMENT_NOT_FOUND")

    # rank 5 -- body shape
    unit_id = v_string(body, "unit_id")
    branch_id = v_string(body, "branch_id")
    damage_assessment_id = v_string(body, "damage_assessment_id")
    scope = v_enum(body, "scope", SCOPES)
    labor_hours = v_number(body, "labor_hours", minimum=0)
    parts_cost_cents = v_int(body, "parts_cost_cents", minimum=0)
    target_condition_grade = v_enum(body, "target_condition_grade", GRADES)
    expected_unit_version = v_int(body, "expected_unit_version")

    # rank 6 -- resource ownership
    require_branch_owner(user_id, role, branch_id)

    # rank 7 -- source state
    if assessment["status"] != "FINALIZED":
        raise ApiError("ERR_ASSESSMENT_NOT_FINALIZED", "The damage assessment is not FINALIZED.")

    # rank 8 -- stale parent version
    if expected_unit_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION",
                       "expected_unit_version does not match the unit's current version.")

    # rank 13 -- cross-entity link agreement
    if assessment["unit_id"] != unit_id:
        raise ApiError("ERR_ENTITY_LINK_MISMATCH", "The assessment is not for this unit.")

    # rank 15 -- servicing branch operational
    if branch["status"] != "OPERATIONAL":
        raise ApiError("ERR_BRANCH_SUSPENDED", "The servicing branch is SUSPENDED.")

    estimate = calc.refurbishment_estimate(
        labor_hours, branch["labor_rate_cents_per_hour"], scope,
        parts_cost_cents, assessment["chargeable_cents"])

    for existing in services.refurb_orders_of_unit(unit_id):
        if existing["status"] == "QUOTED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    record = new_record(
        unit_id=unit_id,
        branch_id=branch_id,
        damage_assessment_id=damage_assessment_id,
        scope=scope,
        labor_hours=labor_hours,
        parts_cost_cents=parts_cost_cents,
        target_condition_grade=target_condition_grade,
        estimated_cost_cents=estimate,
        actual_cost_cents=None,
        status="QUOTED",
        approved_by_user_id=None,
        rejection_reason=None,
    )
    store.refurb_orders[record["id"]] = record

    unit["latest_quote_estimate_cents"] = estimate
    touch(unit)

    return created(S.refurb_order(record))


@bp.get("/refurbishment-orders/<order_id>")
def read_order(order_id):
    auth("BranchOps", "FleetAdmin")
    record = lookup(store.refurb_orders, order_id, "ERR_REFURB_ORDER_NOT_FOUND")
    return success(S.refurb_order(record))


@bp.get("/refurbishment-orders")
def list_orders():
    auth("BranchOps", "FleetAdmin")
    records = ordered(store.refurb_orders.values())
    records = services.apply_filters(records, {
        "unit_id": "unit_id",
        "branch_id": "branch_id",
        "damage_assessment_id": "damage_assessment_id",
        "status": "status",
    })
    return paginate(records, S.refurb_order)


@bp.post("/refurbishment-orders/<order_id>/approve")
def approve_order(order_id):
    user_id, role = auth("FleetAdmin")
    order = lookup(store.refurb_orders, order_id, "ERR_REFURB_ORDER_NOT_FOUND")
    assessment = store.assessments[order["damage_assessment_id"]]
    unit = store.units[order["unit_id"]]

    # rank 7 -- source state
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED order may be approved.")
    if assessment["status"] != "FINALIZED":
        raise ApiError("ERR_ASSESSMENT_NOT_FINALIZED", "The damage assessment is not FINALIZED.")
    if unit["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", "The unit is not RETURNED.")

    # rank 12 -- segregation of duties
    if user_id == assessment["assessor_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver may not be the operator who authored the assessment.")

    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id
    touch(order)

    unit["status"] = "REFURBISHING"
    touch(unit)
    services.recompute_branch_of_unit(unit)

    return success(S.refurb_order(order))


@bp.post("/refurbishment-orders/<order_id>/reject")
def reject_order(order_id):
    auth("FleetAdmin")
    order = lookup(store.refurb_orders, order_id, "ERR_REFURB_ORDER_NOT_FOUND")
    body = get_body()
    rejection_reason = v_string(body, "rejection_reason")

    unit = store.units[order["unit_id"]]

    # rank 7 -- source state
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED order may be rejected.")
    if unit["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", "The unit is not RETURNED.")

    order["status"] = "REJECTED"
    order["rejection_reason"] = rejection_reason
    touch(order)

    unit["status"] = "IN_FLEET"
    unit["latest_quote_estimate_cents"] = 0
    touch(unit)
    services.recompute_branch_of_unit(unit)

    return success(S.refurb_order(order))


@bp.post("/refurbishment-orders/<order_id>/complete")
def complete_order(order_id):
    user_id, role = auth("BranchOps")
    order = lookup(store.refurb_orders, order_id, "ERR_REFURB_ORDER_NOT_FOUND")
    body = get_body()
    actual_cost_cents = v_int(body, "actual_cost_cents", minimum=0)

    # rank 6 -- resource ownership
    require_branch_owner(user_id, role, order["branch_id"])

    # rank 7 -- source state
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED order may be completed.")

    assessment = store.assessments[order["damage_assessment_id"]]
    unit = store.units[order["unit_id"]]

    order["status"] = "COMPLETED"
    order["actual_cost_cents"] = actual_cost_cents
    touch(order)

    unit["status"] = "IN_FLEET"
    unit["condition_grade"] = order["target_condition_grade"]
    unit["refurb_cycles"] += 1
    unit["accumulated_damage_cents"] += assessment["chargeable_cents"]
    unit["latest_quote_estimate_cents"] = 0
    touch(unit)
    services.recompute_branch_of_unit(unit)

    return success(S.refurb_order(order))

"""Cellar work orders: scheduling, execution, billing and disputes."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import (
    ALL_ROLES,
    CELLAR_SUPERVISOR,
    CLIENT_REP,
    FACILITY_ADMIN,
    forbid_action_actor,
    guard,
    scope,
)
from envelope import respond
from errors import (
    ApiError,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CONTRACT_VERSION,
)
from helpers import declared, run_list
from store import db, new_entity, touch
from validation import v_bool, v_datetime, v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("work_orders", __name__)

OPERATION_TYPES = {"PUNCHDOWN", "PUMPOVER", "RACKING", "PRESS", "ADDITION", "TOPPING",
                   "FILTRATION"}
WORK_ORDER_ACTIONS = {
    "SCHEDULE": [CELLAR_SUPERVISOR],
    "START": [CELLAR_SUPERVISOR],
    "COMPLETE": [CELLAR_SUPERVISOR, FACILITY_ADMIN],
    "DISPUTE": [CLIENT_REP],
    "CANCEL": [CLIENT_REP],
}


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    ctx = guard([CLIENT_REP, CELLAR_SUPERVISOR])
    body = ctx.body
    lot_id = v_string(body, "lot_id")
    operation_type = v_enum(body, "operation_type", OPERATION_TYPES)
    scheduled_raw, _scheduled = v_datetime(body, "scheduled_at")
    labor_hours = v_number(body, "labor_hours", gt=0, max_dp=2)
    crew_size = v_int(body, "crew_size", ge=1)
    material_cost = v_int(body, "material_cost_cents", required=False, default=0, ge=0)
    rush = v_bool(body, "rush", required=False, default=False)

    lot = domain.get_lot(lot_id)
    scope(ctx, domain.lot_client_id(lot))

    order = new_entity({
        "lot_id": lot_id,
        "operation_type": operation_type,
        "scheduled_at": scheduled_raw,
        "labor_hours": labor_hours,
        "crew_size": crew_size,
        "material_cost_cents": material_cost,
        "rush": rush,
        "status": "REQUESTED",
        "actual_labor_hours": None,
        "executed_by_user_id": None,
        "billed_by_user_id": None,
        "base_labor_cents": 0,
        "rush_surcharge_cents": 0,
        "subtotal_cents": 0,
        "volume_discount_pct": D(0),
        "billable_amount_cents": 0,
        "dispute_reason": None,
    })
    db.work_orders[order["id"]] = order
    return respond(domain.serialize(order), 201)


@bp.route("/work-orders/<order_id>", methods=["GET"])
def read_work_order(order_id):
    ctx = guard(ALL_ROLES, read_body=False)
    order = domain.get_work_order(order_id)
    scope(ctx, domain.work_order_client_id(order))
    return respond(domain.serialize(order))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.work_orders.values(), ctx, domain.serialize,
                    owner_fn=domain.work_order_client_id,
                    filters=(("lot_id", "lot_id"), ("status", "status"),
                             ("operation_type", "operation_type")))


@bp.route("/work-orders/<order_id>/transitions", methods=["POST"])
def work_order_transitions(order_id):
    ctx = guard([CELLAR_SUPERVISOR, FACILITY_ADMIN, CLIENT_REP], WORK_ORDER_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(WORK_ORDER_ACTIONS))

    actual_hours = None
    dispute_reason = None
    if action == "COMPLETE":
        actual_hours = v_number(body, "actual_labor_hours", gt=0)
    elif action == "DISPUTE":
        dispute_reason = v_string(body, "dispute_reason", required=False, nullable=True)

    order = domain.get_work_order(order_id)
    scope(ctx, domain.work_order_client_id(order))

    lot = db.lots.get(order["lot_id"])
    contract = db.contracts.get(lot["contract_id"]) if lot else None

    if action == "SCHEDULE":
        declared(order["status"] == "REQUESTED")
        if lot is not None and lot["production_status"] in ("CONSUMED", "BOTTLED"):
            raise ApiError(ERR_INVALID_STATE,
                           "The target lot is already finished with.")
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACT_NOT_ACTIVE,
                           "The governing contract is not ACTIVE.")
        order["status"] = "SCHEDULED"
    elif action == "START":
        declared(order["status"] == "SCHEDULED")
        order["status"] = "IN_PROGRESS"
        order["executed_by_user_id"] = ctx.user_id
    elif action == "COMPLETE":
        declared(order["status"] in ("IN_PROGRESS", "DISPUTED"))
        # The actor differs by the state the completion is taken from.
        if order["status"] == "IN_PROGRESS":
            forbid_action_actor(ctx, CELLAR_SUPERVISOR)
        else:
            forbid_action_actor(ctx, FACILITY_ADMIN)
        order["actual_labor_hours"] = actual_hours
        order["status"] = "COMPLETED"
        order["dispute_reason"] = None
    elif action == "DISPUTE":
        declared(order["status"] == "BILLED")
        if contract is not None:
            contract["billed_total_cents"] = (contract["billed_total_cents"]
                                              - order["billable_amount_cents"])
            touch(contract)
        order["status"] = "DISPUTED"
        order["dispute_reason"] = dispute_reason
        order["billable_amount_cents"] = 0
        order["subtotal_cents"] = 0
        order["volume_discount_pct"] = D(0)
    else:  # CANCEL
        declared(order["status"] in ("REQUESTED", "SCHEDULED"))
        order["status"] = "CANCELLED"

    touch(order)
    return respond(domain.serialize(order))


@bp.route("/work-orders/<order_id>/bill", methods=["POST"])
def bill_work_order(order_id):
    ctx = guard([FACILITY_ADMIN])
    expected = v_int(ctx.body, "expected_contract_version")

    order = domain.get_work_order(order_id)

    # Rung 30 -- declared transition.
    declared(order["status"] == "COMPLETED")

    lot = db.lots.get(order["lot_id"])
    contract = db.contracts.get(lot["contract_id"]) if lot else None

    # Rung 35 -- stale-parent rejection on the contract ledger.
    if contract is None or expected != contract["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION,
                       "The contract has moved since it was last read.")
    # Rung 40 -- cross-entity state gate.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "The governing contract is not ACTIVE.")
    # Rung 50 -- segregation of duties.
    if ctx.user_id == order["executed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "The biller may not be the user who executed the order.")

    figures = calc.work_order_billing(
        order["actual_labor_hours"], order["crew_size"],
        contract["labor_rate_cents_per_hour"], order["rush"],
        order["material_cost_cents"], contract["billed_total_cents"])
    order.update(figures)
    order["status"] = "BILLED"
    order["billed_by_user_id"] = ctx.user_id
    touch(order)

    contract["billed_total_cents"] = (contract["billed_total_cents"]
                                      + figures["billable_amount_cents"])
    touch(contract)
    return respond(domain.serialize(order))

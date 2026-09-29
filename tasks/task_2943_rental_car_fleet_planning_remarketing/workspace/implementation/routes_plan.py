"""Fleet plans, postures, purchase allocations and plan performance (PRD 3.3, 3.9)."""

from flask import Blueprint

import calc
import serialize
import validate
from auth import ALL_ROLES, NON_OPERATOR_ROLES, authorize
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, store, touch

bp = Blueprint("plan", __name__)

SEASONS = ("PEAK", "SHOULDER", "OFF_PEAK")


# ===================== FleetPlan =========================================


@bp.route("/fleet/fleet-plans", methods=["POST"])
def draft_plan():
    authorize(("FleetPlanner",))
    payload = validate.body()

    market = validate.body_fk(payload, "market_id", "market")

    validate.s_id(payload, "market_id")
    season = validate.s_enum(payload, "season", SEASONS)
    plan_year = validate.s_int(payload, "plan_year", ge=2020)
    planned_units = validate.s_int(payload, "planned_unit_count", gt=0)
    revenue_target = validate.s_int(payload, "revenue_per_unit_target_cents", gt=0)
    utilization = validate.s_num(payload, "utilization_target_pct", gt=0, le=1)

    for existing in store.plans.values():
        if (
            existing["market_id"] == market["id"]
            and existing["season"] == season
            and existing["plan_year"] == plan_year
        ):
            raise ApiError(
                "ERR_DUPLICATE_FLEET_PLAN",
                "A fleet plan already exists for this market, season and plan year.",
            )

    if market["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MARKET_SUSPENDED",
            "A SUSPENDED market cannot host a new fleet plan.",
        )

    row = base_row()
    row.update({
        "market_id": market["id"],
        "season": season,
        "plan_year": plan_year,
        "planned_unit_count": planned_units,
        "revenue_per_unit_target_cents": revenue_target,
        "utilization_target_pct": utilization,
        "status": "DRAFT",
    })
    store.plans[row["id"]] = row
    return created(serialize.plan(row))


@bp.route("/fleet/fleet-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    authorize(ALL_ROLES)
    return ok(serialize.plan(validate.load("plan", plan_id)))


@bp.route("/fleet/fleet-plans", methods=["GET"])
def list_plans():
    authorize(ALL_ROLES)
    return collect(
        store.plans.values(),
        [
            ("market_id", "market_id", "str"),
            ("season", "season", "str"),
            ("plan_year", "plan_year", "int"),
            ("status", "status", "str"),
        ],
        serialize.plan,
    )


@bp.route("/fleet/fleet-plans/<plan_id>/lock", methods=["POST"])
def lock_plan(plan_id):
    authorize(("FleetController",))
    plan = validate.load("plan", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", "Only a DRAFT plan may be locked.")
    market = store.markets.get(plan["market_id"])
    if market is not None and market["status"] != "ACTIVE":
        raise ApiError("ERR_MARKET_SUSPENDED", "The plan's market is SUSPENDED.")
    plan["status"] = "LOCKED"
    touch(plan)
    return ok(serialize.plan(plan))


@bp.route("/fleet/fleet-plans/<plan_id>/performance", methods=["GET"])
def plan_performance(plan_id):
    authorize(NON_OPERATOR_ROLES)
    plan = validate.load("plan", plan_id)
    return ok(calc.plan_performance(plan))


# ===================== PurchaseAllocation ================================


@bp.route("/fleet/fleet-plans/<plan_id>/allocations", methods=["POST"])
def create_allocation(plan_id):
    authorize(("FleetPlanner",))
    plan = validate.load("plan", plan_id)
    payload = validate.body()

    program = validate.body_fk(payload, "program_id", "program")
    segment = validate.body_fk(payload, "segment_id", "segment")

    validate.s_id(payload, "program_id")
    validate.s_id(payload, "segment_id")
    unit_count = validate.s_int(
        payload, "unit_count", ge=1, error_id="ERR_INVALID_UNIT_COUNT"
    )
    unit_cost = validate.s_int(payload, "capitalized_cost_per_unit_cents", gt=0)
    expected_version = validate.s_int(payload, "expected_plan_version")

    if expected_version != plan["version"]:
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            "expected_plan_version does not match the plan's current version.",
        )

    if plan["status"] != "LOCKED":
        raise ApiError(
            "ERR_PLAN_NOT_LOCKED",
            "Allocations may only be added to a LOCKED plan.",
        )
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROGRAM_CLOSED",
            "A CLOSED manufacturer program accepts no new purchase allocations.",
        )

    allocated = calc.plan_allocated_unit_count(plan)
    posture = calc.plan_posture(plan, allocated)
    if posture == "RESTRICTED" and allocated + unit_count > plan["planned_unit_count"]:
        raise ApiError(
            "ERR_PLAN_POSTURE_RESTRICTED",
            "The plan's posture is RESTRICTED and this allocation would overshoot "
            "planned_unit_count.",
        )
    if posture == "FROZEN":
        raise ApiError(
            "ERR_PLAN_POSTURE_FROZEN",
            "The plan's posture is FROZEN and accepts no further allocations.",
        )

    row = base_row()
    row.update({
        "plan_id": plan["id"],
        "program_id": program["id"],
        "segment_id": segment["id"],
        "unit_count": unit_count,
        "capitalized_cost_per_unit_cents": unit_cost,
        "status": "ORDERED",
    })
    store.allocations[row["id"]] = row
    touch(plan)
    return created(serialize.allocation(row))


@bp.route("/fleet/purchase-allocations/<allocation_id>", methods=["GET"])
def read_allocation(allocation_id):
    authorize(ALL_ROLES)
    return ok(serialize.allocation(validate.load("allocation", allocation_id)))


@bp.route("/fleet/purchase-allocations", methods=["GET"])
def list_allocations():
    authorize(ALL_ROLES)
    return collect(
        store.allocations.values(),
        [
            ("plan_id", "plan_id", "str"),
            ("program_id", "program_id", "str"),
            ("segment_id", "segment_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.allocation,
    )


@bp.route("/fleet/purchase-allocations/<allocation_id>/cancel", methods=["POST"])
def cancel_allocation(allocation_id):
    authorize(("FleetPlanner",))
    allocation = validate.load("allocation", allocation_id)

    if allocation["status"] != "ORDERED" or calc.allocation_created_vehicle_count(allocation):
        raise ApiError(
            "ERR_ALLOCATION_NOT_CANCELLABLE",
            "Only an ORDERED allocation that has minted no vehicle may be cancelled.",
        )
    plan = store.plans.get(allocation["plan_id"])
    if plan is not None and plan["status"] != "LOCKED":
        raise ApiError("ERR_PLAN_NOT_LOCKED", "The allocation's plan is not LOCKED.")

    allocation["status"] = "CANCELLED"
    touch(allocation)
    if plan is not None:
        touch(plan)
    return ok(serialize.allocation(allocation))

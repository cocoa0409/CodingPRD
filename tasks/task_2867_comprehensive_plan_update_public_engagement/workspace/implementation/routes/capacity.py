"""Inventory datasets, growth scenarios and housing allocations (PRD 3.1-3.3)."""
from flask import Blueprint

import constants as K
import serial
import validation as V
from db import bump, db, new_row, sort_rows
from errors import ApiError
from response import (actor, authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import calc, planservice, repo

bp = Blueprint("capacity", __name__)

_READERS = K.ALL_ROLES
_ACREAGE = ("vacant_acres", "underutilized_acres",
            "infrastructure_constrained_acres", "allowed_density_units_per_acre")


@bp.post("/planning/inventory-datasets")
def create_inventory():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    inventory_type = V.get_enum(data, "inventory_type", K.INVENTORY_TYPES)
    vintage_year = V.get_int(data, "vintage_year", 2000, 2100)

    # Rung 4: the acreage payload shape is checked before the plan is resolved.
    if inventory_type == "LAND_USE":
        vacant = V.get_num(data, "vacant_acres", 0)
        underutilized = V.get_num(data, "underutilized_acres", 0)
        constrained = V.get_num(data, "infrastructure_constrained_acres", 0)
        density = V.get_num(data, "allowed_density_units_per_acre", 0,
                            exclusive_min=True)
        if constrained > vacant:
            V.bad("infrastructure_constrained_acres must not exceed "
                  "vacant_acres.")
        record_count = 0
    else:
        for field in _ACREAGE:
            if data.get(field) is not None:
                V.bad("Field '%s' is only valid on a LAND_USE dataset." % field)
        vacant = underutilized = constrained = density = None
        record_count = V.get_int(data, "record_count", 1)

    plan = repo.plan(plan_id)
    planservice.ensure_not_adopted(plan)
    if vintage_year > int(plan["base_year"]):
        raise ApiError("ERR_INVENTORY_VINTAGE_TOO_LATE")

    row = new_row({
        "plan_update_id": plan["id"],
        "inventory_type": inventory_type,
        "vintage_year": vintage_year,
        "status": "DRAFT",
        "record_count": record_count,
        "vacant_acres": vacant,
        "underutilized_acres": underutilized,
        "infrastructure_constrained_acres": constrained,
        "allowed_density_units_per_acre": density,
        "referencing_scenario_count": 0,
        "authored_by_user_id": actor(),
        "certified_by_user_id": None,
    })
    db.inventory_datasets[row["id"]] = row
    return created(serial.inventory(row))


@bp.get("/planning/inventory-datasets/<row_id>")
def read_inventory(row_id):
    authenticate(_READERS)
    return ok(serial.inventory(repo.inventory(row_id)))


@bp.post("/planning/inventory-datasets/<row_id>/certify")
def certify_inventory(row_id):
    authenticate([K.ROLE_DIRECTOR])
    row = repo.inventory(row_id)
    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVENTORY_NOT_DRAFT")

    siblings = [r for r in repo.inventories_of(row["plan_update_id"])
                if r["id"] != row["id"]
                and r["inventory_type"] == row["inventory_type"]
                and r["status"] == "CERTIFIED"]
    for sibling in siblings:
        for scenario in repo.scenarios_of(row["plan_update_id"]):
            if (scenario["land_use_inventory_id"] == sibling["id"]
                    and scenario["status"] == "ADOPTED"):
                raise ApiError("ERR_ADOPTED_SCENARIO_PINNED")

    if actor() == row["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    row["status"] = "CERTIFIED"
    row["certified_by_user_id"] = actor()
    bump(row)
    # Supersession cascade: sibling certified datasets, then their draft scenarios.
    for sibling in siblings:
        sibling["status"] = "SUPERSEDED"
        bump(sibling)
        for scenario in repo.scenarios_of(row["plan_update_id"]):
            if (scenario["land_use_inventory_id"] == sibling["id"]
                    and scenario["status"] == "DRAFT"):
                scenario["status"] = "SUPERSEDED"
                bump(scenario)
    return ok(serial.inventory(row))


# --- growth scenarios -------------------------------------------------------

@bp.post("/planning/growth-scenarios")
def create_scenario():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    inventory_id = V.get_str(data, "land_use_inventory_id", 1, None)
    expected_version = V.get_int(data, "expected_inventory_version", 1)
    label = V.get_str(data, "label", 1, 80)
    method = V.get_enum(data, "method", K.SCENARIO_METHODS)
    horizon_year = V.get_int(data, "horizon_year", 2000, 2100)
    base_households = V.get_int(data, "base_households", 1)
    growth_rate = V.get_num(data, "annual_household_growth_rate", 0, "0.2")
    job_growth = V.get_int(data, "job_growth_total", 0)
    demolition = V.get_int(data, "demolition_replacement_units", 0)

    plan = repo.plan(plan_id)
    inventory = repo.inventory(inventory_id)
    planservice.ensure_not_adopted(plan)
    if inventory["inventory_type"] != "LAND_USE":
        raise ApiError("ERR_INVENTORY_TYPE_MISMATCH")
    if inventory["status"] != "CERTIFIED":
        raise ApiError("ERR_INVENTORY_NOT_CERTIFIED")
    if expected_version != int(inventory["version"]):
        raise ApiError("ERR_STALE_INVENTORY_VERSION")
    if inventory["plan_update_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_LINK")
    # The horizon comparison is deliberately the last check on a creation.
    if horizon_year != int(plan["horizon_year"]):
        raise ApiError("ERR_HORIZON_YEAR_MISMATCH")

    row = new_row({
        "plan_update_id": plan["id"],
        "land_use_inventory_id": inventory["id"],
        "label": label,
        "method": method,
        "horizon_year": horizon_year,
        "base_households": base_households,
        "annual_household_growth_rate": growth_rate,
        "job_growth_total": job_growth,
        "demolition_replacement_units": demolition,
        "capacity_variant": calc.capacity_variant_for(method),
        "status": "DRAFT",
    })
    row["land_capacity_units"] = calc.land_capacity_units(inventory, method)
    row["projected_demand_units"] = calc.projected_demand_units(
        row, plan["base_year"])
    row["capacity_gap_units"] = calc.capacity_gap_units(
        row["projected_demand_units"], row["land_capacity_units"])
    db.growth_scenarios[row["id"]] = row

    inventory["referencing_scenario_count"] = \
        int(inventory["referencing_scenario_count"]) + 1
    bump(inventory)
    return created(serial.scenario(row))


@bp.get("/planning/growth-scenarios/<row_id>")
def read_scenario(row_id):
    authenticate(_READERS)
    return ok(serial.scenario(repo.scenario(row_id)))


@bp.get("/planning/growth-scenarios")
def list_scenarios():
    authenticate(_READERS)
    limit, offset = pagination()
    plan_id = filter_param("plan_update_id")
    inventory_id = filter_param("land_use_inventory_id")
    status = filter_param("status")
    method = filter_param("method")
    rows = sort_rows(list(db.growth_scenarios.values()))
    if plan_id is not None:
        rows = [r for r in rows if r["plan_update_id"] == plan_id]
    if inventory_id is not None:
        rows = [r for r in rows if r["land_use_inventory_id"] == inventory_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    return paginate(rows, limit, offset, serial.scenario)


@bp.post("/planning/growth-scenarios/<row_id>/adopt")
def adopt_scenario(row_id):
    authenticate([K.ROLE_DIRECTOR])
    row = repo.scenario(row_id)
    plan = repo.plan(row["plan_update_id"])
    planservice.ensure_not_adopted(plan)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_SCENARIO_NOT_DRAFT")
    certified = set(r["inventory_type"] for r in repo.inventories_of(plan["id"])
                    if r["status"] == "CERTIFIED")
    if any(t not in certified for t in K.INVENTORY_TYPES):
        raise ApiError("ERR_INVENTORY_SET_INCOMPLETE")

    previous_id = plan.get("adopted_scenario_id")
    if previous_id is not None and previous_id != row["id"]:
        previous = db.growth_scenarios.get(previous_id)
        if previous is not None and previous["status"] == "ADOPTED":
            previous["status"] = "SUPERSEDED"
            bump(previous)
    row["status"] = "ADOPTED"
    bump(row)
    plan["adopted_scenario_id"] = row["id"]
    planservice.run_waterfall(plan)
    planservice.refresh(plan)
    bump(plan)
    return ok(serial.scenario(row))


# --- housing allocations ----------------------------------------------------

@bp.post("/planning/housing-allocations")
def create_allocation():
    authenticate([K.ROLE_STATE])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    tier = V.get_enum(data, "income_tier", K.INCOME_TIERS)
    assigned = V.get_int(data, "assigned_units", 0)
    deadline = V.get_instant(data, "cycle_deadline")

    plan = repo.plan(plan_id)
    planservice.ensure_not_adopted(plan)
    for existing in repo.allocations_of(plan["id"]):
        if existing["income_tier"] == tier:
            raise ApiError("ERR_DUPLICATE_ALLOCATION_TIER")

    row = new_row({
        "plan_update_id": plan["id"],
        "income_tier": tier,
        "assigned_units": assigned,
        "cycle_deadline": deadline,
        "tier_capacity_units": 0,
        "carryover_in_units": 0,
        "accommodated_units": 0,
        "shortfall_units": 0,
    })
    db.housing_allocations[row["id"]] = row
    # The whole tier set is recomputed from scratch; the new row stays at v1.
    planservice.run_waterfall(plan, skip_bump_id=row["id"])
    planservice.refresh(plan)
    bump(plan)
    return created(serial.allocation(row))

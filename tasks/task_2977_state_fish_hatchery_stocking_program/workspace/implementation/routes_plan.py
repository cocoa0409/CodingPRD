"""Allocation plans and the distribution run (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import validators as v
from auth import authorize, scope_hatchery
from envelope import (created, enum_filter, int_filter, ok, pagination, paginate,
                      str_filter)
from errors import ApiError
from serialize import dump
from store import (Tx, base_record, clock, fmt_instant, get_or_404, insert, sort_key,
                   values)

bp = Blueprint("allocation_plan", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.REGIONAL_BIOLOGIST)


@bp.post("/allocation-plans")
def create_allocation_plan():
    authorize(K.PROGRAM_ADMIN)
    body = v.body()
    hatchery = get_or_404("hatcheries", v.req_id(body, "hatchery_id"))

    fiscal_year = v.req_int(body, "fiscal_year")
    species = v.req_enum(body, "species", K.SPECIES)
    size_class = v.req_enum(body, "size_class", K.SIZE_CLASSES)
    available_count = v.req_int(body, "available_count", minimum=Decimal(0))
    public_request_cap_pct = v.req_num(body, "public_request_cap_pct",
                                     minimum=Decimal(0), maximum=Decimal(1))
    allocation_mode = v.opt_enum(body, "allocation_mode", K.ALLOCATION_MODES,
                                default="PRIORITY_WATERFALL")

    record = base_record()
    record.update({
        "hatchery_id": hatchery["id"],
        "fiscal_year": fiscal_year,
        "species": species,
        "size_class": size_class,
        "available_count": available_count,
        "public_request_cap_pct": public_request_cap_pct,
        "allocation_mode": allocation_mode,
        "allocated_total_count": 0,
        "unmet_demand_count": 0,
        "run_count": 0,
        "public_allocated_count": 0,
        "status": "DRAFT",
    })
    insert("allocation_plans", record)
    return created(dump(record))


@bp.get("/allocation-plans/<identifier>")
def get_allocation_plan(identifier):
    user_id, role = authorize(*READ_ROLES)
    plan = get_or_404("allocation_plans", identifier)
    scope_hatchery(role, user_id, plan["hatchery_id"])
    return ok(dump(plan))


@bp.get("/allocation-plans")
def list_allocation_plans():
    authorize(*READ_ROLES)
    hatchery_id = str_filter("hatchery_id")
    status = enum_filter("status", K.PLAN_STATUSES)
    fiscal_year = int_filter("fiscal_year")
    limit, offset = pagination()

    records = values("allocation_plans")
    if hatchery_id is not None:
        records = [r for r in records if r["hatchery_id"] == hatchery_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if fiscal_year is not None:
        records = [r for r in records if r["fiscal_year"] == fiscal_year]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


def _order_key(stocking_request):
    """priority_score DESC, then requested_count ASC, then created_at ASC."""
    return (-Decimal(stocking_request["priority_score"]),
            stocking_request["requested_count"],
            stocking_request["created_at"],
            stocking_request["_seq"])


@bp.post("/allocation-plans/<identifier>/run")
def run_allocation_plan(identifier):
    authorize(K.PROGRAM_ADMIN)
    plan = get_or_404("allocation_plans", identifier)
    body = v.body()
    expected_plan_version = v.req_int(body, "expected_plan_version")

    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION",
                       "The plan has advanced since it was read.")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT plan may be run.")
    hatchery = get_or_404("hatcheries", plan["hatchery_id"])
    if hatchery["operating_posture"] == "FROZEN":
        raise ApiError("ERR_HATCHERY_FROZEN", "This station is frozen.")

    queued = [r for r in derive.requests_of_plan(plan["id"]) if r["status"] == "QUEUED"]
    eligible = []
    ineligible = []
    for candidate in queued:
        water = get_or_404("waters", candidate["water_id"])
        if candidate["species"] == plan["species"] and water["status"] == "ACTIVE":
            eligible.append(candidate)
        else:
            ineligible.append(candidate)
    if not eligible:
        # "nothing at all is written: the plan stays DRAFT, its version does not
        # advance, and no request changes status"
        raise ApiError("ERR_NO_ELIGIBLE_REQUESTS",
                       "No queued request on this plan survives eligibility.")

    tx = Tx()
    stamp = fmt_instant(clock())
    for candidate in ineligible:
        candidate["status"] = "DENIED"
        candidate["allocated_count"] = 0
        candidate["deferral_reason"] = "INELIGIBLE"
        tx.touch(candidate)

    available = plan["available_count"]
    public_pool = calc.floor_int(Decimal(available) * Decimal(plan["public_request_cap_pct"]))
    remaining = available
    total_requested = sum(candidate["requested_count"] for candidate in eligible)

    for candidate in sorted(eligible, key=_order_key):
        requested = candidate["requested_count"]
        if plan["allocation_mode"] == "PRIORITY_WATERFALL":
            raw = min(requested, remaining)
        else:
            pro_rata = 0
            if total_requested > 0:
                pro_rata = calc.floor_int(
                    Decimal(available) * Decimal(requested) / Decimal(total_requested))
            raw = min(requested, pro_rata, remaining)
        if candidate["requester_kind"] == "PUBLIC":
            raw = min(raw, public_pool)
        # "the entitlement is rounded down to a whole multiple of the 25-fish
        # transport unit ... BEFORE the remainder is decremented"
        grant = (raw // K.STOCKING_UNIT) * K.STOCKING_UNIT
        if candidate["requester_kind"] == "PUBLIC":
            public_pool -= grant
        remaining -= grant

        candidate["allocated_count"] = grant
        if grant > 0:
            candidate["status"] = "ALLOCATED"
            candidate["allocated_at"] = stamp
            candidate["deferral_reason"] = None
        else:
            candidate["status"] = "DEFERRED"
            candidate["allocated_at"] = None
            candidate["deferral_reason"] = "POOL_EXHAUSTED"
        tx.touch(candidate)

    plan["status"] = "ALLOCATED"
    plan["run_count"] = plan["run_count"] + 1
    plan["allocated_total_count"] = available - remaining
    plan["unmet_demand_count"] = sum(
        candidate["requested_count"] - candidate["allocated_count"] for candidate in eligible)
    plan["public_allocated_count"] = sum(
        candidate["allocated_count"] for candidate in eligible
        if candidate["requester_kind"] == "PUBLIC")
    tx.touch(plan)

    waters = []
    for candidate in eligible + ineligible:
        water = get_or_404("waters", candidate["water_id"])
        if water not in waters:
            waters.append(water)
    for water in waters:
        derive.recompute_water(tx, water)
    tx.settle()
    return ok(dump(plan))

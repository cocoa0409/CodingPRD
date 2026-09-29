"""Demand intake, the frozen priority score, withdrawal and queueing (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import validators as v
from auth import authorize, own_request
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from errors import ApiError
from serialize import dump
from store import Tx, base_record, clock, fmt_instant, get_or_404, insert, sort_key, values

bp = Blueprint("stocking_request", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.REGIONAL_BIOLOGIST, K.PUBLIC_REQUESTER)
OPEN_STATUSES = ("SUBMITTED", "QUEUED", "DEFERRED")


@bp.post("/stocking-requests")
def create_stocking_request():
    user_id, role = authorize(K.REGIONAL_BIOLOGIST, K.PUBLIC_REQUESTER)
    body = v.body()
    water = get_or_404("waters", v.req_id(body, "water_id"))

    species = v.req_enum(body, "species", K.SPECIES)
    requested_count = v.req_int(body, "requested_count", minimum=Decimal(1))
    size_class = v.req_enum(body, "size_class", K.SIZE_CLASSES)
    justification = v.req_str(body, "justification")

    # "The requester_kind is never accepted from the body."
    requester_kind = "BIOLOGIST" if role == K.REGIONAL_BIOLOGIST else "PUBLIC"

    record = base_record()
    record.update({
        "water_id": water["id"],
        "allocation_plan_id": None,
        "requester_kind": requester_kind,
        "requested_by_user_id": user_id,
        "species": species,
        "requested_count": requested_count,
        "size_class": size_class,
        "justification": justification,
        # "computed from the destination water's counters as they stand at that
        # moment and then frozen on the request"
        "priority_score": calc.priority_score(water, species, requester_kind),
        "allocated_count": 0,
        "allocated_at": None,
        "deferral_reason": None,
        "fulfilled_at": None,
        "status": "SUBMITTED",
    })
    insert("stocking_requests", record)
    return created(dump(record))


@bp.get("/stocking-requests/<identifier>")
def get_stocking_request(identifier):
    authorize(*READ_ROLES)
    return ok(dump(get_or_404("stocking_requests", identifier)))


@bp.get("/stocking-requests")
def list_stocking_requests():
    authorize(*READ_ROLES)
    water_id = str_filter("water_id")
    allocation_plan_id = str_filter("allocation_plan_id")
    status = enum_filter("status", K.REQUEST_STATUSES)
    requester_kind = enum_filter("requester_kind", K.REQUESTER_KINDS)
    species = enum_filter("species", K.SPECIES)
    limit, offset = pagination()

    records = values("stocking_requests")
    if water_id is not None:
        records = [r for r in records if r["water_id"] == water_id]
    if allocation_plan_id is not None:
        records = [r for r in records if r["allocation_plan_id"] == allocation_plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if requester_kind is not None:
        records = [r for r in records if r["requester_kind"] == requester_kind]
    if species is not None:
        records = [r for r in records if r["species"] == species]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/stocking-requests/<identifier>/withdraw")
def withdraw_stocking_request(identifier):
    user_id, role = authorize(K.REGIONAL_BIOLOGIST, K.PUBLIC_REQUESTER, K.PROGRAM_ADMIN)
    stocking_request = get_or_404("stocking_requests", identifier)
    own_request(role, user_id, stocking_request)

    if stocking_request["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "This request may no longer be withdrawn.")

    tx = Tx()
    # "Withdrawal from QUEUED retains the allocation_plan_id for audit."
    stocking_request["status"] = "WITHDRAWN"
    tx.touch(stocking_request)
    derive.recompute_water(tx, get_or_404("waters", stocking_request["water_id"]))
    tx.settle()
    return ok(dump(stocking_request))


def _plan_has_started_production(plan):
    """"any stocking event has already been created against a request this plan
    allocated"."""
    request_ids = set(r["id"] for r in derive.requests_of_plan(plan["id"]))
    for event in values("stocking_events"):
        if event["stocking_request_id"] in request_ids:
            return True
    return False


def _reset_plan_to_draft(tx, plan):
    """"Such an attach sends the plan from ALLOCATED back to DRAFT."""
    plan["status"] = "DRAFT"
    plan["allocated_total_count"] = 0
    plan["unmet_demand_count"] = 0
    plan["public_allocated_count"] = 0
    tx.touch(plan)

    waters = []
    for resolved in derive.requests_of_plan(plan["id"]):
        if resolved["status"] not in ("ALLOCATED", "DEFERRED"):
            continue
        resolved["status"] = "QUEUED"
        resolved["allocated_count"] = 0
        resolved["allocated_at"] = None
        resolved["deferral_reason"] = None
        tx.touch(resolved)
        water = get_or_404("waters", resolved["water_id"])
        if water not in waters:
            waters.append(water)
    for water in waters:
        derive.recompute_water(tx, water)


@bp.post("/stocking-requests/<identifier>/attach-to-plan")
def attach_request_to_plan(identifier):
    user_id, role = authorize(K.REGIONAL_BIOLOGIST, K.PROGRAM_ADMIN)
    stocking_request = get_or_404("stocking_requests", identifier)
    own_request(role, user_id, stocking_request)

    body = v.body()
    plan = get_or_404("allocation_plans", v.req_id(body, "allocation_plan_id"))
    expected_plan_version = v.req_int(body, "expected_plan_version")

    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION",
                       "The plan has advanced since it was read.")

    if stocking_request["status"] not in ("SUBMITTED", "DEFERRED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED or DEFERRED request may be attached to a plan.")
    if plan["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "A CLOSED plan may not be attached to.")
    if (stocking_request["status"] == "DEFERRED"
            and stocking_request["allocation_plan_id"] == plan["id"]):
        raise ApiError("ERR_INVALID_STATE",
                       "A deferred request may not re-attach to the plan that deferred it.")
    if plan["status"] == "ALLOCATED" and _plan_has_started_production(plan):
        raise ApiError("ERR_INVALID_STATE",
                       "Production has begun against this plan's allocations.")
    if stocking_request["size_class"] != plan["size_class"]:
        raise ApiError("ERR_SIZE_CLASS_MISMATCH",
                       "The request's size_class does not match the plan's.")

    tx = Tx()
    if plan["status"] == "ALLOCATED":
        _reset_plan_to_draft(tx, plan)

    stocking_request["status"] = "QUEUED"
    stocking_request["allocation_plan_id"] = plan["id"]
    stocking_request["deferral_reason"] = None
    tx.touch(stocking_request)
    # "the plan's version advances too"
    tx.touch(plan)
    derive.recompute_water(tx, get_or_404("waters", stocking_request["water_id"]))
    tx.settle()
    return ok(dump(stocking_request))

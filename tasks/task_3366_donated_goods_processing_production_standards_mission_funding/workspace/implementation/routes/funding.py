"""Mission programs and the funding-allocation pipeline."""
from flask import Blueprint, request

import errors
from clock import now
from db import store
from envelope import success
from serializers import ser_allocation, ser_program
from services import (
    new_entity,
    org_of_allocation,
    org_of_program,
    recompute_margin_health,
    touch,
)
from validate import auth, field, get_body, paginate, require_role, sort_created

bp = Blueprint("funding", __name__)

PROGRAM_TYPES = {"JOB_TRAINING", "PLACEMENT", "SUPPORT"}


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


@bp.post("/donated-goods/mission-programs")
def create_program():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    name = field(body, "name", "str", required=True)
    program_type = field(body, "program_type", "str", required=True,
                         enum=PROGRAM_TYPES)
    start_date = field(body, "start_date", "datetime", required=True)
    end_date = field(body, "end_date", "datetime", required=True)
    funding_goal = field(body, "funding_goal_cents", "int", required=True)
    _uid, role = auth()
    require_role(role, {"ProgramDirector"})
    org = _get_org(member_org_id)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        program = new_entity()
        program.update({
            "member_org_id": member_org_id,
            "name": name,
            "program_type": program_type,
            "start_date": start_date,
            "end_date": end_date,
            "funding_goal_cents": funding_goal,
            "funding_disbursed_cents": 0,
        })
        store.mission_programs[program["id"]] = program
    return success(ser_program(program), 201)


@bp.get("/donated-goods/member-orgs/<oid>/mission-programs")
def list_programs(oid):
    auth()
    _get_org(oid)
    items = [p for p in store.mission_programs.values()
             if p["member_org_id"] == oid]
    ptype = request.args.get("program_type")
    if ptype is not None:
        items = [p for p in items if p["program_type"] == ptype]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_program(p) for p in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Funding allocations
# ---------------------------------------------------------------------------

def _get_program(pid):
    program = store.mission_programs.get(pid)
    if program is None:
        errors.not_found("MissionProgram not found")
    return program


def _get_allocation(aid):
    alloc = store.funding_allocations.get(aid)
    if alloc is None:
        errors.not_found("FundingAllocation not found")
    return alloc


def _check_program_window(program):
    clock = now()
    if not (program["start_date"] <= clock <= program["end_date"]):
        errors.program_window_closed()


@bp.post("/donated-goods/funding-allocations")
def create_allocation():
    body = get_body()
    program_id = field(body, "mission_program_id", "str", required=True)
    amount = field(body, "amount_cents", "int", required=True, minval=1)
    expected_version = field(body, "expected_member_org_version", "int",
                             required=True)
    uid, role = auth()
    require_role(role, {"ProgramDirector"})
    program = _get_program(program_id)
    org = org_of_program(program)
    # OCC (priority 6) precedes the suspension gate (priority 7).
    if expected_version != org["version"]:
        errors.stale_version()
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    _check_program_window(program)
    if org["margin_health"] != "HEALTHY":
        errors.margin_reserve_breach()
    with store.lock:
        alloc = new_entity()
        alloc.update({
            "mission_program_id": program_id,
            "amount_cents": amount,
            "created_by_user_id": uid,
            "approved_by_user_id": None,
            "status": "PENDING",
        })
        store.funding_allocations[alloc["id"]] = alloc
        touch(org)
    return success(ser_allocation(alloc), 201)


@bp.get("/donated-goods/funding-allocations")
def list_allocations():
    auth()
    items = list(store.funding_allocations.values())
    for param in ("mission_program_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a[param] == val]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_allocation(a) for a in page], 200,
                   response_type="array", pagination=meta)


@bp.get("/donated-goods/funding-allocations/<aid>")
def get_allocation(aid):
    auth()
    return success(ser_allocation(_get_allocation(aid)), 200)


@bp.post("/donated-goods/funding-allocations/<aid>/approve")
def approve_allocation(aid):
    get_body()
    uid, role = auth()
    require_role(role, {"MemberCFO"})
    alloc = _get_allocation(aid)
    program = store.mission_programs[alloc["mission_program_id"]]
    org = org_of_allocation(alloc)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if alloc["status"] != "PENDING":
        errors.invalid_state("Only a PENDING allocation can be approved")
    if uid == alloc["created_by_user_id"]:
        errors.segregation()
    _check_program_window(program)
    if alloc["amount_cents"] > org["retail_margin_pool_cents"] - org["reserved_cents"]:
        errors.insufficient_margin()
    with store.lock:
        alloc["status"] = "APPROVED"
        alloc["approved_by_user_id"] = uid
        org["reserved_cents"] += alloc["amount_cents"]
        touch(alloc)
        touch(org)
    return success(ser_allocation(alloc), 200)


@bp.post("/donated-goods/funding-allocations/<aid>/cancel")
def cancel_allocation(aid):
    get_body()
    uid, role = auth()
    require_role(role, {"ProgramDirector", "MemberCFO"})
    alloc = _get_allocation(aid)
    # Cancel is EXEMPT from the org-suspension gate (cleanup path).
    if alloc["status"] not in ("PENDING", "APPROVED"):
        errors.invalid_state("Only a PENDING or APPROVED allocation can be cancelled")
    # The two cancellable states belong to distinct actors (PRD 3.7).
    if alloc["status"] == "PENDING" and role != "ProgramDirector":
        errors.forbidden("From PENDING, a ProgramDirector cancels")
    if alloc["status"] == "APPROVED" and role != "MemberCFO":
        errors.forbidden("From APPROVED, a MemberCFO cancels")
    with store.lock:
        if alloc["status"] == "APPROVED":
            # Compensating action: release the reservation (and only then
            # does cancellation advance the org version).
            org = org_of_allocation(alloc)
            org["reserved_cents"] -= alloc["amount_cents"]
            touch(org)
        alloc["status"] = "CANCELLED"
        touch(alloc)
    return success(ser_allocation(alloc), 200)


@bp.post("/donated-goods/funding-allocations/<aid>/disburse")
def disburse_allocation(aid):
    get_body()
    uid, role = auth()
    require_role(role, {"MemberCFO"})
    alloc = _get_allocation(aid)
    program = store.mission_programs[alloc["mission_program_id"]]
    org = org_of_allocation(alloc)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if alloc["status"] != "APPROVED":
        errors.invalid_state("Only an APPROVED allocation can be disbursed")
    with store.lock:
        amount = alloc["amount_cents"]
        org["reserved_cents"] -= amount           # link 1: release reservation
        org["retail_margin_pool_cents"] -= amount  # link 2: pool debit ...
        recompute_margin_health(org)               # ... may cross to LOW
        program["funding_disbursed_cents"] += amount
        alloc["status"] = "DISBURSED"
        touch(alloc)
        touch(program)
        touch(org)
    return success(ser_allocation(alloc), 200)

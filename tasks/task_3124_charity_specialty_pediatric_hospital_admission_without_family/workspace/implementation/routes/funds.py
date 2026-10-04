"""PhilanthropicFund and FundAllocation endpoints (PRD §3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import services
from errors import (ApiError, ERR_ALLOCATION_NOT_FOUND, ERR_FUND_NOT_FOUND,
                    ERR_FUND_NOT_OPEN, ERR_HOSPITAL_NOT_FOUND,
                    ERR_CARE_PLAN_NOT_FOUND, ERR_PROGRAM_NOT_FOUND,
                    ERR_INSUFFICIENT_FUND_BALANCE, ERR_PLEDGED_ALLOCATIONS_EXIST,
                    ERR_PLAN_HAS_STAGE_IN_FLIGHT, ERR_STALE_VERSION,
                    bad_request, invalid_state)
from helpers import get_body, is_int, new_id, now_iso, req_int, req_str, touch
from middleware import require_auth
from response import success_list, success_object, paginate
from views import allocation_view, fund_view

bp = Blueprint("funds", __name__)

LIST_ROLES = ["NetworkAdmin", "PhilanthropyOfficer", "CareCoordinator"]

BASE_WEIGHT = Decimal("1.0")
CAPACITY_STRAIN_FRACTION = Decimal("0.5")


def get_fund_or_404(fund_id):
    f = db.funds.get(fund_id)
    if f is None:
        raise ApiError(ERR_FUND_NOT_FOUND, 404, "Philanthropic fund id does not exist")
    return f


def get_allocation_or_404(allocation_id):
    a = db.allocations.get(allocation_id)
    if a is None:
        raise ApiError(ERR_ALLOCATION_NOT_FOUND, 404, "Fund allocation id does not exist")
    return a


@bp.post("/philanthropic-funds")
def create_fund():
    require_auth(["PhilanthropyOfficer"])
    body = get_body()
    fund_name = req_str(body, "fund_name")
    fiscal_year = req_int(body, "fiscal_year")
    total_committed_cents = req_int(body, "total_committed_cents", minimum=0)
    now = now_iso()
    f = {
        "id": new_id(),
        "fund_name": fund_name,
        "fiscal_year": fiscal_year,
        "total_committed_cents": total_committed_cents,
        "allocated_cents": 0,
        "available_cents": total_committed_cents,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.funds[f["id"]] = f
    return success_object(fund_view(f), 201)


@bp.get("/philanthropic-funds")
def list_funds():
    require_auth(LIST_ROLES)
    items = list(db.funds.values())
    fiscal_year = request.args.get("fiscal_year")
    if fiscal_year is not None and fiscal_year != "":
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise bad_request("fiscal_year must be an integer")
        items = [f for f in items if f["fiscal_year"] == fy]
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([fund_view(f) for f in page], total, limit, offset)


@bp.get("/philanthropic-funds/<fundId>")
def get_fund(fundId):
    require_auth(LIST_ROLES)
    f = get_fund_or_404(fundId)
    return success_object(fund_view(f))


@bp.post("/philanthropic-funds/<fundId>/lock")
def lock_fund(fundId):
    require_auth(["PhilanthropyOfficer"])
    f = get_fund_or_404(fundId)
    if f["status"] != "OPEN":
        raise invalid_state("Fund must be OPEN to lock")
    f["status"] = "LOCKED"
    touch(f)
    return success_object(fund_view(f))


@bp.post("/philanthropic-funds/<fundId>/unlock")
def unlock_fund(fundId):
    require_auth(["PhilanthropyOfficer"])
    f = get_fund_or_404(fundId)
    if f["status"] != "LOCKED":
        raise invalid_state("Fund must be LOCKED to unlock")
    f["status"] = "OPEN"
    touch(f)
    return success_object(fund_view(f))


@bp.post("/philanthropic-funds/<fundId>/close")
def close_fund(fundId):
    require_auth(["PhilanthropyOfficer"])
    f = get_fund_or_404(fundId)
    if f["status"] != "LOCKED":
        raise invalid_state("Fund must be LOCKED to close")
    for a in db.allocations.values():
        if a["fund_id"] == f["id"] and a["status"] == "PLEDGED":
            raise ApiError(ERR_PLEDGED_ALLOCATIONS_EXIST, 409,
                           "Fund close blocked by PLEDGED allocations")
    f["status"] = "CLOSED"
    touch(f)
    return success_object(fund_view(f))


@bp.post("/philanthropic-funds/<id>/allocations")
def create_allocation(id):
    require_auth(["PhilanthropyOfficer"])
    fund = get_fund_or_404(id)
    body = get_body()
    hospital_id = body.get("hospital_id")
    if hospital_id is None:
        raise bad_request("Missing required field: hospital_id")
    if not isinstance(hospital_id, str) or hospital_id == "":
        raise bad_request("Field hospital_id must be a non-empty string")
    amount_cents = req_int(body, "amount_cents", minimum=1)
    program_id = body.get("program_id")
    if program_id is not None and (not isinstance(program_id, str) or program_id == ""):
        raise bad_request("Field program_id must be a non-empty string")
    care_plan_id = body.get("care_plan_id")
    if care_plan_id is not None and (not isinstance(care_plan_id, str) or care_plan_id == ""):
        raise bad_request("Field care_plan_id must be a non-empty string")

    # Body FK existence (priority 4)
    if hospital_id not in db.hospitals:
        raise ApiError(ERR_HOSPITAL_NOT_FOUND, 404, "Hospital id does not exist")
    if program_id is not None and program_id not in db.programs:
        raise ApiError(ERR_PROGRAM_NOT_FOUND, 404, "Program id does not exist")
    if care_plan_id is not None and care_plan_id not in db.care_plans:
        raise ApiError(ERR_CARE_PLAN_NOT_FOUND, 404, "Care plan id does not exist")

    now = now_iso()
    a = {
        "id": new_id(),
        "fund_id": fund["id"],
        "hospital_id": hospital_id,
        "program_id": program_id,
        "care_plan_id": care_plan_id,
        "amount_cents": amount_cents,
        "allocation_weight": None,
        "status": "PLEDGED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.allocations[a["id"]] = a
    return success_object(allocation_view(a), 201)


@bp.get("/philanthropic-funds/<id>/allocations")
def list_allocations_of_fund(id):
    require_auth(LIST_ROLES)
    fund = get_fund_or_404(id)
    items = [a for a in db.allocations.values() if a["fund_id"] == fund["id"]]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    hospital_id = request.args.get("hospital_id")
    if hospital_id:
        items = [a for a in items if a["hospital_id"] == hospital_id]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([allocation_view(a) for a in page], total, limit, offset)


@bp.get("/fund-allocations")
def list_allocations():
    require_auth(LIST_ROLES)
    items = list(db.allocations.values())
    fund_id = request.args.get("fund_id")
    if fund_id:
        items = [a for a in items if a["fund_id"] == fund_id]
    hospital_id = request.args.get("hospital_id")
    if hospital_id:
        items = [a for a in items if a["hospital_id"] == hospital_id]
    program_id = request.args.get("program_id")
    if program_id:
        items = [a for a in items if a.get("program_id") == program_id]
    care_plan_id = request.args.get("care_plan_id")
    if care_plan_id:
        items = [a for a in items if a.get("care_plan_id") == care_plan_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([allocation_view(a) for a in page], total, limit, offset)


@bp.get("/fund-allocations/<allocationId>")
def get_allocation(allocationId):
    require_auth(LIST_ROLES)
    a = get_allocation_or_404(allocationId)
    return success_object(allocation_view(a))


@bp.post("/fund-allocations/<allocationId>/commit")
def commit_allocation(allocationId):
    require_auth(["PhilanthropyOfficer"])
    a = get_allocation_or_404(allocationId)
    body = get_body()
    expected_fund_version = body.get("expected_fund_version")
    if expected_fund_version is None:
        raise bad_request("Missing required field: expected_fund_version")
    if not is_int(expected_fund_version):
        raise bad_request("Field expected_fund_version must be an integer")

    fund = db.funds.get(a["fund_id"])
    # State check (priority 5) before OCC (priority 6)
    if a["status"] != "PLEDGED":
        raise invalid_state("Allocation must be PLEDGED to commit")
    if expected_fund_version != fund["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_fund_version does not match the fund's current version")
    if fund["status"] != "OPEN":
        raise ApiError(ERR_FUND_NOT_OPEN, 409, "Fund must be OPEN to commit allocations")
    if fund["available_cents"] < a["amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_FUND_BALANCE, 402,
                       "fund.available_cents < allocation.amount_cents at commit")

    # Pinned evaluation order (scaffold §1.3 allocation_weight):
    # (1) snapshot hospital admissions_ytd / annual_capacity BEFORE the commit,
    # (2) compute the weight from the snapshot, (3) then mutate fund balances.
    hospital = db.hospitals.get(a["hospital_id"])
    snapshot_ytd = hospital["admissions_ytd"] if hospital else 0
    snapshot_capacity = hospital["annual_capacity"] if hospital else 1

    weight = BASE_WEIGHT
    if a.get("program_id") is not None:
        weight *= Decimal("1.5")
    if a.get("care_plan_id") is not None:
        weight *= Decimal("2.0")
    if Decimal(snapshot_ytd) < Decimal(snapshot_capacity) * CAPACITY_STRAIN_FRACTION:
        weight *= Decimal("1.25")
    a["allocation_weight"] = float(
        weight.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())

    fund["allocated_cents"] += a["amount_cents"]
    fund["available_cents"] -= a["amount_cents"]
    touch(fund)

    a["status"] = "COMMITTED"
    touch(a)

    if a.get("care_plan_id"):
        plan = db.care_plans.get(a["care_plan_id"])
        if plan is not None:
            services.recompute_plan_funding(plan)

    return success_object(allocation_view(a))


@bp.post("/fund-allocations/<allocationId>/withdraw")
def withdraw_allocation(allocationId):
    require_auth(["PhilanthropyOfficer"])
    a = get_allocation_or_404(allocationId)
    if a["status"] != "PLEDGED":
        raise invalid_state("Allocation must be PLEDGED to withdraw")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_object(allocation_view(a))


@bp.post("/fund-allocations/<allocationId>/release")
def release_allocation(allocationId):
    require_auth(["PhilanthropyOfficer"])
    a = get_allocation_or_404(allocationId)
    if a["status"] != "COMMITTED":
        raise invalid_state("Allocation must be COMMITTED to release")
    if a.get("care_plan_id"):
        plan = db.care_plans.get(a["care_plan_id"])
        if plan is not None and plan["clinical_status"] == "ACTIVE_TREATMENT":
            in_flight = any(s for s in db.stages.values()
                            if s["care_plan_id"] == plan["id"] and s["status"] == "SCHEDULED")
            if in_flight:
                raise ApiError(ERR_PLAN_HAS_STAGE_IN_FLIGHT, 409,
                               "Allocation release blocked: designated care plan is "
                               "ACTIVE_TREATMENT with a SCHEDULED stage")
    fund = db.funds.get(a["fund_id"])
    fund["allocated_cents"] -= a["amount_cents"]
    fund["available_cents"] += a["amount_cents"]
    touch(fund)
    a["status"] = "RELEASED"
    touch(a)
    if a.get("care_plan_id"):
        plan = db.care_plans.get(a["care_plan_id"])
        if plan is not None:
            services.recompute_plan_funding(plan)
    return success_object(allocation_view(a))

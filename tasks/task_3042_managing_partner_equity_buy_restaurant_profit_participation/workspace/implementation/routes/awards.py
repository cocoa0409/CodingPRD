"""Award program and grant routes (PRD §3.10)."""

from flask import Blueprint, request

import db
from errors import conflict, invalid_request, unprocessable
from errors import (
    ERR_AWARD_NOT_ELIGIBLE,
    ERR_AWARD_POOL_EXHAUSTED,
    ERR_AWARD_SOURCE_PERIOD_INELIGIBLE,
    ERR_INVALID_STATE,
)
from middleware import require_roles, ALL_ROLES
from response import success_list, success_object
from services import calculations, domain
from util import (
    base_entity,
    get_json_body,
    paginate,
    req_date,
    req_field,
    req_int,
    req_number,
    req_string,
    touch,
)

bp = Blueprint("awards", __name__)


@bp.route("/award-programs", methods=["POST"])
def create_program():
    require_roles("CorporateController")
    body = get_json_body()
    name = req_string(body, "name")
    program_type = req_string(body, "program_type")
    if program_type not in ("CONFERENCE", "STOCK_GRANT"):
        raise invalid_request("program_type must be CONFERENCE or STOCK_GRANT")
    perf_start = req_date(body, "performance_period_start_date")
    perf_end = req_date(body, "performance_period_end_date")
    if perf_end < perf_start:
        raise invalid_request("performance_period_end_date must be on or after performance_period_start_date")
    threshold = body.get("eligibility_threshold_score")
    if threshold is None:
        threshold = 80
    elif isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise invalid_request("eligibility_threshold_score must be a number")
    stock_pool = body.get("stock_units_pool")
    if program_type == "STOCK_GRANT":
        if stock_pool is None:
            raise invalid_request("stock_units_pool is required for STOCK_GRANT programs")
        if isinstance(stock_pool, bool) or not isinstance(stock_pool, int) or stock_pool <= 0:
            raise invalid_request("stock_units_pool must be an integer > 0 for STOCK_GRANT programs")
    p = base_entity()
    p.update({
        "name": name,
        "program_type": program_type,
        "performance_period_start_date": perf_start.isoformat(),
        "performance_period_end_date": perf_end.isoformat(),
        "eligibility_threshold_score": threshold,
        "stock_units_pool": stock_pool if program_type == "STOCK_GRANT" else None,
        "units_reserved": 0,
        "status": "OPEN",
    })
    db.award_programs[p["id"]] = p
    return success_object(domain.ser_program(p), 201)


@bp.route("/award-programs", methods=["GET"])
def list_programs():
    require_roles(*ALL_ROLES)
    items = list(db.award_programs.values())
    program_type = request.args.get("program_type")
    if program_type is not None:
        items = [p for p in items if p["program_type"] == program_type]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_program(p) for p in page], limit, offset, total)


@bp.route("/award-programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles(*ALL_ROLES)
    return success_object(domain.ser_program(domain.get_program(pid)))


@bp.route("/award-programs/<pid>/close", methods=["POST"])
def close_program(pid):
    require_roles("CorporateController")
    p = domain.get_program(pid)
    if p["status"] != "OPEN":
        raise conflict(ERR_INVALID_STATE, "Program must be OPEN to close")
    p["status"] = "CLOSED"
    touch(p)
    return success_object(domain.ser_program(p))


@bp.route("/award-programs/<pid>/grants", methods=["POST"])
def create_grant(pid):
    require_roles("CorporateController")
    program = domain.get_program(pid)
    if program["status"] != "OPEN":
        raise conflict(ERR_INVALID_STATE, "Program must be OPEN to grant awards")
    body = get_json_body()
    partner_id = req_field(body, "partner_id")
    source_period_id = req_field(body, "source_period_id")
    # Body FK existence (tier 4).
    domain.ref_partner(partner_id)
    period = domain.ref_period(source_period_id)
    # Referential gate (tier 7): source period FINALIZED/LOCKED within the inclusive window.
    if period["status"] not in ("FINALIZED", "LOCKED"):
        raise unprocessable(
            ERR_AWARD_SOURCE_PERIOD_INELIGIBLE,
            "Source period must be FINALIZED or LOCKED",
        )
    if not (
        program["performance_period_start_date"] <= period["period_start_date"]
        and period["period_end_date"] <= program["performance_period_end_date"]
    ):
        raise unprocessable(
            ERR_AWARD_SOURCE_PERIOD_INELIGIBLE,
            "Source period lies outside the program's performance window",
        )
    score = calculations.award_eligibility_score(period)
    if program["program_type"] == "CONFERENCE":
        units = 0
        if score < program["eligibility_threshold_score"]:
            raise unprocessable(ERR_AWARD_NOT_ELIGIBLE, "Eligibility score below the program threshold")
    else:
        # STOCK_GRANT tiers: score >= 90 -> 200 units; score >= 80 -> 100 units (inclusive).
        if score >= domain.STOCK_TIER2_SCORE:
            units = 200
        elif score >= domain.STOCK_TIER1_SCORE:
            units = 100
        else:
            raise unprocessable(ERR_AWARD_NOT_ELIGIBLE, "Eligibility score below the stock tier threshold")
        if score < program["eligibility_threshold_score"]:
            raise unprocessable(ERR_AWARD_NOT_ELIGIBLE, "Eligibility score below the program threshold")
        if program["units_reserved"] + units > program["stock_units_pool"]:
            raise unprocessable(ERR_AWARD_POOL_EXHAUSTED, "Stock pool capacity exceeded")
    g = base_entity()
    g.update({
        "program_id": program["id"],
        "partner_id": partner_id,
        "source_period_id": source_period_id,
        "eligibility_score": score,
        "units_awarded": units,
        "status": "EARNED",
    })
    db.award_grants[g["id"]] = g
    if program["program_type"] == "STOCK_GRANT":
        program["units_reserved"] += units
        touch(program)
    return success_object(domain.ser_grant(g), 201)


@bp.route("/award-grants", methods=["GET"])
def list_grants():
    require_roles(*ALL_ROLES)
    items = list(db.award_grants.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [g for g in items if g["program_id"] == program_id]
    partner_id = request.args.get("partner_id")
    if partner_id is not None:
        items = [g for g in items if g["partner_id"] == partner_id]
    source_period_id = request.args.get("source_period_id")
    if source_period_id is not None:
        items = [g for g in items if g["source_period_id"] == source_period_id]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_grant(g) for g in page], limit, offset, total)


@bp.route("/award-grants/<gid>", methods=["GET"])
def get_grant(gid):
    require_roles(*ALL_ROLES)
    return success_object(domain.ser_grant(domain.get_grant(gid)))


@bp.route("/award-grants/<gid>/vest", methods=["POST"])
def vest_grant(gid):
    require_roles("CorporateController")
    g = domain.get_grant(gid)
    if g["status"] != "EARNED":
        raise conflict(ERR_INVALID_STATE, "Grant must be EARNED to enter vesting")
    g["status"] = "VESTING"
    touch(g)
    return success_object(domain.ser_grant(g))

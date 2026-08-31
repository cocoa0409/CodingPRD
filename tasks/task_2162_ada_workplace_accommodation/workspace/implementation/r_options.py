"""Accommodation options and undue-hardship assessments."""
from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (endpoint, need_function, need_option, need_request,
                   require_case_owner, require_not_sealed)
from envelope import created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, store
from validation import F, raw_body, validate

bp = Blueprint("options", __name__)

CATEGORIES = ("EQUIPMENT", "SCHEDULE_MODIFICATION", "TELEWORK", "JOB_RESTRUCTURING",
              "REASSIGNMENT", "LEAVE_AS_ACCOMMODATION", "POLICY_EXCEPTION")

OPTION_SPEC = [
    F("option_code", "string", required=True, non_empty=True),
    F("category", "enum", required=True, enum=CATEGORIES),
    F("one_time_cost_cents", "integer", default=0, has_default=True, minimum=0),
    F("recurring_monthly_cost_cents", "integer", default=0, has_default=True, minimum=0),
    F("implementation_days", "integer", required=True, minimum=0, maximum=365),
    F("coverage_function_ids", "id_array", required=True),
]


def _require_functions_pinned(req, function_ids, require_essential=True):
    for fid in function_ids:
        function = store.essential_functions.get(fid)
        if function is None or function["status"] != "ACTIVE" or \
                function["job_profile_id"] != req["job_profile_id"] or \
                (require_essential and function["is_essential"] is not True):
            raise ApiError("ERR_FUNCTION_NOT_IN_PINNED_PROFILE",
                           "A referenced duty is not a live essential duty on the "
                           "case's pinned profile.")


@bp.post("/accommodation-requests/<case_id>/options")
@endpoint(["AccommodationCoordinator", "Employee"])
def create_option(case_id):
    data = validate(raw_body(), OPTION_SPEC)
    req = need_request(case_id)
    for fid in data["coverage_function_ids"]:
        need_function(fid)
    require_case_owner(req)
    if req["stage"] != "OPTION_EXPLORATION":
        raise ApiError("ERR_INVALID_STAGE_TRANSITION",
                       "Options may only be proposed during OPTION_EXPLORATION.")
    require_not_sealed(req)
    _require_functions_pinned(req, data["coverage_function_ids"])
    for existing in domain.options_of(req["id"]):
        if existing["option_code"] == data["option_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "option_code is already taken on this case.")
    net = calc.option_net_cost(data["one_time_cost_cents"],
                               data["recurring_monthly_cost_cents"])
    ratio = calc.coverage_ratio(req["job_profile_id"], data["coverage_function_ids"])
    row = store.new_row("AccommodationOption", {
        "request_id": req["id"],
        "option_code": data["option_code"],
        "category": data["category"],
        "proposed_by_role": g.role,
        "one_time_cost_cents": data["one_time_cost_cents"],
        "recurring_monthly_cost_cents": data["recurring_monthly_cost_cents"],
        "implementation_days": data["implementation_days"],
        "coverage_function_ids": data["coverage_function_ids"],
        "option_net_cost_cents": net,
        "coverage_ratio": calc.as_number(ratio),
        "committed_cost_cents": 0,
        "status": "PROPOSED",
    })
    store.options[row["id"]] = row
    return created(row)


@bp.get("/accommodation-requests/<case_id>/options")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "FinanceOfficer",
           "AppealOfficer", "ComplianceAuditor"])
def list_options(case_id):
    limit, offset = read_pagination()
    need_request(case_id)
    rows = domain.options_of(case_id)
    status = flask_request.args.get("status")
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    return listing(by_created(rows), limit, offset)


@bp.get("/accommodation-options/<option_id>")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "FinanceOfficer",
           "AppealOfficer", "ComplianceAuditor"])
def get_option(option_id):
    return ok(need_option(option_id))


@bp.patch("/accommodation-options/<option_id>")
@endpoint(["AccommodationCoordinator"])
def patch_option(option_id):
    data = validate(raw_body(), [
        F("one_time_cost_cents", "integer", minimum=0),
        F("recurring_monthly_cost_cents", "integer", minimum=0),
        F("implementation_days", "integer", minimum=0, maximum=365),
        F("coverage_function_ids", "id_array"),
    ])
    option = need_option(option_id)
    if "coverage_function_ids" in data:
        for fid in data["coverage_function_ids"]:
            need_function(fid)
    req = store.requests.get(option["request_id"])
    if req["stage"] != "HARDSHIP_REVIEW" or \
            option["status"] not in ("PROPOSED", "HARDSHIP_BLOCKED"):
        raise ApiError("ERR_OPTION_NOT_ASSESSABLE",
                       "The option cannot be revised in its current state.")
    require_not_sealed(req)
    if "coverage_function_ids" in data:
        _require_functions_pinned(req, data["coverage_function_ids"])
    for key in ("one_time_cost_cents", "recurring_monthly_cost_cents",
                "implementation_days", "coverage_function_ids"):
        if key in data:
            option[key] = data[key]
    option["option_net_cost_cents"] = calc.option_net_cost(
        option["one_time_cost_cents"], option["recurring_monthly_cost_cents"])
    option["coverage_ratio"] = calc.as_number(
        calc.coverage_ratio(req["job_profile_id"], option["coverage_function_ids"]))
    was_blocked = option["status"] == "HARDSHIP_BLOCKED"
    if was_blocked:
        option["status"] = "PROPOSED"
    touch(option)
    if was_blocked:
        domain.assign(req, blocked_option_count=max(0, req["blocked_option_count"] - 1))
        current = domain.current_assessment(option["id"])
        if current is not None:
            domain.assign(current, status="SUPERSEDED")
    return ok(option)


# ===================== Undue-hardship assessments ========================
@bp.post("/accommodation-options/<option_id>/hardship-assessments")
@endpoint(["FinanceOfficer"])
def create_assessment(option_id):
    data = validate(raw_body(), [
        F("assessment_basis", "enum", required=True,
          enum=("EMPLOYER_WIDE", "SITE_LOCAL")),
        F("expected_option_version", "integer", required=True),
    ])
    option = need_option(option_id)
    req = store.requests.get(option["request_id"])
    if req["stage"] != "HARDSHIP_REVIEW" or option["status"] != "PROPOSED":
        raise ApiError("ERR_OPTION_NOT_ASSESSABLE",
                       "The option cannot be assessed in its current state.")
    if data["expected_option_version"] != option["version"]:
        raise ApiError("ERR_STALE_VERSION")
    require_not_sealed(req)
    _require_functions_pinned(req, option["coverage_function_ids"],
                              require_essential=False)
    profile = domain.profile_of_case(req)
    computed = calc.hardship_assessment(option, profile, data["assessment_basis"])

    previous = domain.current_assessment(option["id"])
    if previous is not None:
        domain.assign(previous, status="SUPERSEDED")
    row = store.new_row("UndueHardshipAssessment", {
        "option_id": option["id"],
        "assessment_basis": data["assessment_basis"],
        "assessor_user_id": g.user_id,
        "assessed_net_cost_cents": computed["assessed_net_cost_cents"],
        "denominator_cents": computed["denominator_cents"],
        "budget_ratio": computed["budget_ratio"],
        "budget_ratio_norm": computed["budget_ratio_norm"],
        "disruption_index": computed["disruption_index"],
        "lag_norm": computed["lag_norm"],
        "raw_hardship_score": computed["raw_hardship_score"],
        "mitigation_credit_rate": computed["mitigation_credit_rate"],
        "hardship_score": computed["hardship_score"],
        "hardship_verdict": computed["hardship_verdict"],
        "status": "CURRENT",
    })
    store.assessments[row["id"]] = row

    if computed["hardship_verdict"] == "UNDUE":
        option["status"] = "HARDSHIP_BLOCKED"
        touch(option)
        domain.assign(req, blocked_option_count=req["blocked_option_count"] + 1)
    else:
        option["status"] = "CLEARED"
        touch(option)
        domain.assign(req, cleared_option_count=req["cleared_option_count"] + 1)
    return created(row)


@bp.get("/accommodation-options/<option_id>/hardship-assessments")
@endpoint(["AccommodationCoordinator", "FinanceOfficer", "AppealOfficer",
           "ComplianceAuditor"])
def list_assessments(option_id):
    limit, offset = read_pagination()
    need_option(option_id)
    rows = domain.assessments_of(option_id)
    status = flask_request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return listing(by_created(rows), limit, offset)

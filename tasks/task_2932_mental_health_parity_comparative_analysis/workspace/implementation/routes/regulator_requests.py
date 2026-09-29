"""Regulator requests: opening, responding and adjudication (PRD 3.9)."""

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import guard
from enums import (ADJUDICATION_OUTCOMES, ALL_ROLES, NQTL_TYPES,
                   RESPONDABLE_REGULATOR_STATUSES)
from envelope import success
from errors import ApiError
from helpers import list_response
from store import add_days, clock_now, db, lookup_path, new_row, touch

bp = Blueprint("regulator_requests", __name__)


@bp.route("/regulator-requests", methods=["POST"])
@guard("Regulator")
def create_regulator_request():
    payload = shape.body()
    raw_plan_year = shape.raw_fk(payload, "plan_year_id")
    if raw_plan_year is not None and raw_plan_year not in db.plan_years:
        raise ApiError("ERR_PLAN_YEAR_NOT_FOUND")

    plan_year_id = shape.req_string(payload, "plan_year_id", 1, None)
    requested_types = shape.req_enum_array(payload, "requested_nqtl_types", NQTL_TYPES)
    request_reference = shape.req_string(payload, "request_reference", 1, 64)

    plan_year = db.plan_years[plan_year_id]
    # Step 14.
    recompute.gate_not_closed(plan_year)

    opened_at = clock_now()
    row = new_row({
        "plan_year_id": plan_year_id,
        "requested_nqtl_types": requested_types,
        "request_reference": request_reference,
        "opened_at": opened_at,
        "response_due_at": add_days(opened_at, calc.REGULATOR_RESPONSE_DAYS),
        "requested_item_count": 0,
        "covered_item_count": 0,
        "completeness_score": None,
        "response_sufficient": None,
        "regulator_round": 0,
        "status": "OPEN",
    })
    db.regulator_requests[row["id"]] = row

    # The plan-design surface freezes while the regulator is looking at the year.
    if plan_year["status"] == "OPEN":
        plan_year["status"] = "UNDER_REGULATOR_REVIEW"
        touch(plan_year)
    return success(serialize.regulator_request(row), 201)


@bp.route("/regulator-requests/<request_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_regulator_request(request_id):
    row = lookup_path(db.regulator_requests, request_id, "ERR_REGULATOR_REQUEST_NOT_FOUND")
    return success(serialize.regulator_request(row))


@bp.route("/regulator-requests", methods=["GET"])
@guard(*ALL_ROLES)
def list_regulator_requests():
    return list_response(db.regulator_requests.values(), serialize.regulator_request,
                         ("plan_year_id", "status"))


@bp.route("/regulator-requests/<request_id>/respond", methods=["POST"])
@guard("PlanSponsor")
def respond_to_regulator(request_id):
    regulator_request = lookup_path(db.regulator_requests, request_id,
                                    "ERR_REGULATOR_REQUEST_NOT_FOUND")
    payload = shape.body()
    shape.opt_string(payload, "response_note", 1, None)

    plan_year = db.plan_years.get(regulator_request["plan_year_id"])
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if regulator_request["status"] not in RESPONDABLE_REGULATOR_STATUSES:
        raise ApiError("ERR_REGULATOR_REQUEST_NOT_OPEN")
    # Step 31: the clock must stand at or before the (possibly extended) deadline.
    if clock_now() > regulator_request["response_due_at"]:
        raise ApiError("ERR_RESPONSE_WINDOW_EXPIRED")
    # Step 32: the demand must match at least one inventoried item.
    requested, covered, score, sufficient = calc.regulator_response_completeness(
        regulator_request)
    if requested < 1:
        raise ApiError("ERR_NO_REQUESTED_ITEMS")

    regulator_request["requested_item_count"] = requested
    regulator_request["covered_item_count"] = covered
    regulator_request["completeness_score"] = score
    regulator_request["response_sufficient"] = sufficient
    regulator_request["status"] = "RESPONDED"
    touch(regulator_request)
    return success(serialize.regulator_request(regulator_request))


@bp.route("/regulator-requests/<request_id>/adjudicate", methods=["POST"])
@guard("Regulator")
def adjudicate_regulator_request(request_id):
    regulator_request = lookup_path(db.regulator_requests, request_id,
                                    "ERR_REGULATOR_REQUEST_NOT_FOUND")
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", ADJUDICATION_OUTCOMES)
    shape.opt_string(payload, "adjudication_note", 1, None)

    plan_year = db.plan_years.get(regulator_request["plan_year_id"])
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if regulator_request["status"] != "RESPONDED":
        raise ApiError("ERR_REGULATOR_REQUEST_NOT_RESPONDED")

    if outcome == "INSUFFICIENT":
        regulator_request["status"] = "INSUFFICIENT_RESPONSE"
        regulator_request["regulator_round"] = regulator_request["regulator_round"] + 1
        regulator_request["response_due_at"] = add_days(
            regulator_request["response_due_at"], calc.REOPEN_EXTENSION_DAYS)
        touch(regulator_request)
        return success(serialize.regulator_request(regulator_request))

    regulator_request["status"] = "CLOSED"
    touch(regulator_request)
    if (plan_year is not None
            and plan_year["compliance_posture"] == "COMPLIANT"
            and plan_year["status"] == "UNDER_REGULATOR_REVIEW"):
        plan_year["status"] = "CLOSED"
        touch(plan_year)
    return success(serialize.regulator_request(regulator_request))

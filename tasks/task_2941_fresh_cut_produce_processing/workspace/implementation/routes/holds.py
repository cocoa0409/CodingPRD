"""Hold records, the bounded retest loop, release, rejection and shipping."""

import datetime

from flask import Blueprint

import db
import enums
import serializers
from envelope import actor, enum_param, listing, object_response, read_body, require
from errors import ApiError
from services import holds, shelflife
from util import now_dt

bp = Blueprint("holds", __name__)

MAX_TEST_ROUNDS = 3
TERMINAL_HOLD_STATES = ("RELEASED", "REJECTED")
SHIPPABLE_DISPOSITIONS = ("UNRESTRICTED", "RELEASED")

CREATE_HOLD = (("reason", "enum", True, {"values": enums.HOLD_REASON}),)
SUBMIT_SAMPLE = (("latest_test_type", "enum", True, {"values": enums.TEST_TYPE}),)
RECORD_RESULT = (
    ("latest_test_result", "enum", True, {"values": enums.TEST_RESULT}),
    ("latest_apc_cfu_g", "int", False, {"ge": 0}),
)


@bp.post("/process-runs/<run_id>/hold-records")
@require("QATechnician")
def create_hold(run_id):
    body = read_body(CREATE_HOLD)
    run = db.get_or_404("process_runs", run_id)
    if run["disposition_status"] == "REJECTED":
        raise ApiError("ERR_HOLD_INVALID_STATE", "the run is already REJECTED")
    if run["run_status"] == "CANCELLED":
        raise ApiError("ERR_HOLD_INVALID_STATE", "a CANCELLED run cannot be held")
    hold = holds.open_hold(run, body["reason"], now_dt())
    return object_response(serializers.hold_record(hold), 201)


@bp.get("/process-runs/<run_id>/hold-records")
@require("PlantAdmin", "QAManager", "QATechnician")
def list_holds(run_id):
    status = enum_param("status", enums.HOLD_STATUS)
    reason = enum_param("reason", enums.HOLD_REASON)
    db.get_or_404("process_runs", run_id)
    rows = holds.holds_of(run_id)
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    if reason is not None:
        rows = [h for h in rows if h["reason"] == reason]
    rows.sort(key=lambda h: (db.dt_of(h, "opened_at"), h["_seq"]), reverse=True)
    return listing(rows, serializers.hold_record)


@bp.post("/hold-records/<hold_id>/submit-sample")
@require("QATechnician")
def submit_sample(hold_id):
    body = read_body(SUBMIT_SAMPLE)
    hold = db.get_or_404("hold_records", hold_id)
    if hold["status"] not in ("HELD", "RETEST_REQUIRED"):
        raise ApiError(
            "ERR_HOLD_INVALID_STATE",
            "only a HELD or RETEST_REQUIRED hold may take a sample",
        )
    if not hold["test_round"] < MAX_TEST_ROUNDS:
        raise ApiError(
            "ERR_MAX_RETEST_ROUNDS_EXCEEDED",
            "the hold has already consumed its three test rounds",
        )
    hold["test_round"] = hold["test_round"] + 1
    hold["latest_test_type"] = body["latest_test_type"]
    hold["latest_test_result"] = None
    hold["latest_apc_cfu_g"] = None
    hold["resulted_by_user_id"] = None
    hold["status"] = "UNDER_TEST"
    db.touch(hold)
    return object_response(serializers.hold_record(hold))


@bp.post("/hold-records/<hold_id>/record-result")
@require("QATechnician")
def record_result(hold_id):
    body = read_body(RECORD_RESULT)
    hold = db.get_or_404("hold_records", hold_id)
    if hold["status"] != "UNDER_TEST":
        raise ApiError(
            "ERR_HOLD_INVALID_STATE", "only an UNDER_TEST hold may be resulted"
        )
    hold["latest_test_result"] = body["latest_test_result"]
    hold["latest_apc_cfu_g"] = body["latest_apc_cfu_g"]
    hold["resulted_by_user_id"] = actor()
    if body["latest_test_result"] == "INDETERMINATE":
        hold["status"] = "RETEST_REQUIRED"
    db.touch(hold)
    return object_response(serializers.hold_record(hold))


@bp.post("/hold-records/<hold_id>/release")
@require("QAManager")
def release_hold(hold_id):
    hold = db.get_or_404("hold_records", hold_id)
    run = db.get_or_404("process_runs", hold["process_run_id"])
    if hold["status"] != "UNDER_TEST":
        raise ApiError(
            "ERR_HOLD_INVALID_STATE", "only an UNDER_TEST hold may be released"
        )
    for other in holds.holds_of(run["id"]):
        if other["id"] == hold["id"]:
            continue
        if other["status"] not in TERMINAL_HOLD_STATES:
            raise ApiError(
                "ERR_HOLD_INVALID_STATE",
                "another hold on this run is still open",
            )
    if actor() == hold["resulted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the releaser must differ from resulted_by_user_id",
        )
    if hold["latest_test_result"] != "NEGATIVE":
        raise ApiError(
            "ERR_TEST_RESULT_NOT_NEGATIVE",
            "the hold's latest test result is not NEGATIVE",
        )
    now = now_dt()
    hold["status"] = "RELEASED"
    db.stamp(hold, "closed_at", now)
    hold["released_by_user_id"] = actor()
    db.touch(hold)

    reference = db.dt_of(run, "closed_at")
    code_date = None
    label = None
    if reference is not None:
        days, code_date, label = shelflife.compute(
            run, reference, shelflife.micro_penalty_for(hold)
        )
        run["final_shelf_life_days"] = days
        run["final_code_date"] = code_date
    holds.restore_cases(run, code_date, label)
    run["disposition_status"] = "RELEASED"
    holds.recount(run)
    db.touch(run)
    return object_response(serializers.hold_record(hold))


@bp.post("/hold-records/<hold_id>/reject")
@require("QAManager")
def reject_hold(hold_id):
    hold = db.get_or_404("hold_records", hold_id)
    run = db.get_or_404("process_runs", hold["process_run_id"])
    if hold["status"] not in ("UNDER_TEST", "RETEST_REQUIRED"):
        raise ApiError(
            "ERR_HOLD_INVALID_STATE",
            "only an UNDER_TEST or RETEST_REQUIRED hold may be rejected",
        )
    now = now_dt()
    hold["status"] = "REJECTED"
    db.stamp(hold, "closed_at", now)
    hold["released_by_user_id"] = actor()
    db.touch(hold)
    holds.destroy_cases(run)
    run["disposition_status"] = "REJECTED"
    holds.recount(run)
    db.touch(run)
    return object_response(serializers.hold_record(hold))


@bp.post("/finished-cases/<case_id>/ship")
@require("ShippingClerk")
def ship_case(case_id):
    case = db.get_or_404("finished_cases", case_id)
    run = db.get_or_404("process_runs", case["process_run_id"])
    if run["disposition_status"] not in SHIPPABLE_DISPOSITIONS:
        raise ApiError(
            "ERR_HOLD_NOT_RELEASED",
            "the run disposition is " + run["disposition_status"],
        )
    if case["status"] != "IN_INVENTORY":
        raise ApiError(
            "ERR_CASE_NOT_IN_INVENTORY", "the case is not IN_INVENTORY"
        )
    spec = db.get_or_404("customer_specs", run["customer_spec_id"])
    now = now_dt()
    remaining_days = (
        datetime.date.fromisoformat(case["code_date"]) - now.date()
    ).days
    if remaining_days < spec["min_remaining_shelf_life_days_at_ship"]:
        raise ApiError(
            "ERR_INSUFFICIENT_REMAINING_SHELF_LIFE",
            "the case has too little code-date life left to ship",
        )
    case["status"] = "SHIPPED"
    db.stamp(case, "shipped_at", now)
    db.touch(case)
    holds.recount(run)
    db.touch(run)
    return object_response(serializers.finished_case(case))

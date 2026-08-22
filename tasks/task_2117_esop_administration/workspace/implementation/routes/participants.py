"""Participant endpoints (PRD 3.1, 3.4)."""

from datetime import date

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import PLAN_SPONSOR, READ_ROLES, endpoint
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("participants", __name__)

PARTICIPANT_STATUSES = ("ACTIVE", "TERMINATED", "RETIRED", "DECEASED", "DISTRIBUTED")
TERMINATION_REASONS = ("TERMINATION", "RETIREMENT", "DEATH", "DISABILITY")


@bp.post("/participants")
@endpoint([PLAN_SPONSOR])
def create_participant():
    body = v.body()
    plan_id = v.req_string(body, "plan_id")
    employee_number = v.req_string(body, "employee_number")
    date_of_birth = v.req_date(body, "date_of_birth")
    hire_date = v.req_date(body, "hire_date")
    eligible_compensation_cents = v.req_integer(
        body, "eligible_compensation_cents", required=False, default=0, minimum=0)
    annual_hours = v.req_integer(body, "annual_hours", required=False, default=2000, minimum=0)

    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "OPEN")

    for existing in DB.participants.values():
        if existing["plan_id"] == plan_id and existing["employee_number"] == employee_number:
            fail("ERR_DUPLICATE_EMPLOYEE_NUMBER")

    record = {
        "plan_id": plan_id,
        "employee_number": employee_number,
        "date_of_birth": date_of_birth,
        "hire_date": hire_date,
        "eligible_compensation_cents": eligible_compensation_cents,
        "annual_hours": annual_hours,
        "status": "ACTIVE",
        "termination_date": None,
        "termination_reason": None,
        "years_of_service": 0,
        "vested_percentage": 0,
        "allocated_shares": 0,
        "vested_shares": 0,
        "distributed_shares_cumulative": 0,
        "tendered_shares_cumulative": 0,
        "diversified_shares_cumulative": 0,
        "put_window_open_date": None,
        "put_window_close_date": None,
        "last_put_window_close_date": None,
        "diversification_first_eligible_plan_year": None,
        "diversification_eligible": False,
    }
    participant = insert(DB.participants, record)
    services.refresh_diversification(participant, plan)
    return responses.ok(serialize(participant), 201)


@bp.get("/participants/<participant_id>")
@endpoint(READ_ROLES)
def read_participant(participant_id):
    participant = services.get_participant(participant_id)
    return responses.ok(serialize(participant))


@bp.get("/participants")
@endpoint(READ_ROLES)
def list_participants():
    limit, offset = v.pagination()
    plan_id = v.query_str("plan_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.participants)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return services.paged(rows, limit, offset)


@bp.patch("/participants/<participant_id>")
@endpoint([PLAN_SPONSOR])
def update_participant(participant_id):
    body = v.body()
    eligible_compensation_cents = v.req_integer(
        body, "eligible_compensation_cents", required=False, default=None, minimum=0)
    annual_hours = v.req_integer(body, "annual_hours", required=False, default=None, minimum=0)

    participant = services.get_participant(participant_id)
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "OPEN")

    if eligible_compensation_cents is not None:
        participant["eligible_compensation_cents"] = eligible_compensation_cents
    if annual_hours is not None:
        participant["annual_hours"] = annual_hours
    touch(participant)
    return responses.ok(serialize(participant))


@bp.post("/participants/<participant_id>/terminate")
@endpoint([PLAN_SPONSOR])
def terminate_participant(participant_id):
    body = v.body()
    termination_date = v.req_date(body, "termination_date")
    termination_reason = v.req_enum(body, "termination_reason", TERMINATION_REASONS)

    participant = services.get_participant(participant_id)
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    # priority 9 -- the transition must be declared from the current state
    if participant["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    separation = calc.iso_to_date(termination_date)
    if separation < calc.iso_to_date(participant["hire_date"]):
        fail("ERR_INVALID_STATE", "termination_date may not fall before hire_date.")

    # priority 22 -- the retirement age gate
    if termination_reason == "RETIREMENT":
        if calc.whole_year_age(participant["date_of_birth"], separation) < plan["normal_retirement_age"]:
            fail("ERR_RETIREMENT_AGE_NOT_ATTAINED")

    participant["termination_date"] = termination_date
    participant["termination_reason"] = termination_reason

    if plan["service_measurement_method"] == "TERMINATION_DATE_MEASURE":
        measurement_date = separation
    else:
        measurement_date = date(plan["plan_year"], 12, 31)

    years, percentage = calc.participant_vesting(
        participant["hire_date"], measurement_date, plan["vesting_schedule"], termination_reason)
    participant["years_of_service"] = years
    participant["vested_percentage"] = percentage
    services.recompute_vested_shares(participant)

    if termination_reason == "RETIREMENT":
        participant["status"] = "RETIRED"
        participant["vested_percentage"] = 100
        participant["vested_shares"] = participant["allocated_shares"]
    elif termination_reason == "DEATH":
        participant["status"] = "DECEASED"
        participant["vested_percentage"] = 100
        participant["vested_shares"] = participant["allocated_shares"]
    else:
        participant["status"] = "TERMINATED"
        if participant["vested_percentage"] < 100:
            forfeited = participant["allocated_shares"] - participant["vested_shares"]
            insert(DB.forfeiture_events, {
                "participant_id": participant["id"],
                "plan_id": plan["id"],
                "plan_year": plan["plan_year"],
                "forfeited_shares": forfeited,
                "vested_percentage_at_forfeiture": participant["vested_percentage"],
                "years_of_service_at_forfeiture": participant["years_of_service"],
                "measurement_method_applied": plan["service_measurement_method"],
                "reallocated_in_run_id": None,
                "status": "PENDING_REALLOCATION",
            })
            # PINNED exception: both counters land on the pre-forfeiture vested count.
            vested_before = participant["vested_shares"]
            participant["allocated_shares"] = vested_before
            participant["vested_shares"] = vested_before

            plan["unallocated_forfeiture_shares"] += forfeited
            plan["allocated_shares_total"] -= forfeited
            services.recompute_forfeiture_posture(plan)

    services.refresh_diversification(participant, plan)
    touch(participant)
    touch(plan)
    return responses.ok(serialize(participant))


@bp.get("/forfeiture-events/<forfeiture_id>")
@endpoint(READ_ROLES)
def read_forfeiture(forfeiture_id):
    row = services.lookup("forfeiture_events", forfeiture_id)
    return responses.ok(serialize(row))


@bp.get("/forfeiture-events")
@endpoint(READ_ROLES)
def list_forfeitures():
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    plan_id = v.query_str("plan_id")
    run_id = v.query_str("reallocated_in_run_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.forfeiture_events)
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if run_id is not None:
        rows = [r for r in rows if r["reallocated_in_run_id"] == run_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return services.paged(rows, limit, offset)

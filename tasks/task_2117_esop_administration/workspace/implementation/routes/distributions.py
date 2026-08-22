"""Distribution election and installment endpoints (PRD 3.7)."""

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import (PARTICIPANT, PLAN_ADMINISTRATOR, READ_ROLES, caller_id,
                  endpoint, is_participant_caller)
from clock import CLOCK
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("distributions", __name__)

ELECTION_TYPES = ("TERMINATION", "RETIREMENT", "DEATH", "DISABILITY", "DIVERSIFICATION")
SEPARATION_TYPES = ("TERMINATION", "RETIREMENT", "DEATH", "DISABILITY")
SEPARATED_STATUSES = ("TERMINATED", "RETIRED", "DECEASED")


@bp.post("/distribution-elections")
@endpoint([PARTICIPANT, PLAN_ADMINISTRATOR])
def create_election():
    body = v.body()
    participant_id = v.req_string(body, "participant_id")
    election_type = v.req_enum(body, "election_type", ELECTION_TYPES)
    requested_shares = v.req_integer(body, "requested_shares", minimum=1)

    participant = services.get_participant(participant_id)

    if is_participant_caller() and caller_id() != participant["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    year_index = None
    cap_percent = None
    if election_type == "DIVERSIFICATION":
        anchor = calc.diversification_anchor_year(
            participant["date_of_birth"], participant["hire_date"],
            plan["diversification_min_age"], plan["diversification_min_years"])
        year_index = calc.diversification_year_index(plan["plan_year"], anchor)
        if year_index < 1 or year_index > calc.QUALIFIED_PERIOD_YEARS:
            fail("ERR_DIVERSIFICATION_WINDOW_CLOSED")
        cap_percent = calc.diversification_cap_percent(year_index)

    # priority 21 -- the participant's status must permit the election type
    if election_type == "DIVERSIFICATION":
        if participant["status"] != "ACTIVE":
            fail("ERR_ELECTION_NOT_PERMITTED")
    else:
        if participant["status"] not in SEPARATED_STATUSES:
            fail("ERR_ELECTION_NOT_PERMITTED")

    if election_type != "DIVERSIFICATION":
        if requested_shares > participant["vested_shares"]:
            fail("ERR_INSUFFICIENT_SHARES")
    else:
        available = calc.diversification_available_shares(
            participant["allocated_shares"], participant["diversified_shares_cumulative"],
            cap_percent)
        if requested_shares > available:
            fail("ERR_DIVERSIFICATION_LIMIT_EXCEEDED")

    election = insert(DB.distribution_elections, {
        "participant_id": participant_id,
        "election_type": election_type,
        "requested_shares": requested_shares,
        "approved_shares": 0,
        "installment_count": 0,
        "approval_status": "REQUESTED",
        "payment_status": "NOT_STARTED",
        "share_price_at_election_cents": plan["current_share_price_cents"],
        "commenced_at_date": None,
        "diversification_year_index": year_index,
        "diversification_cap_percent": cap_percent,
    })
    return responses.ok(serialize(election), 201)


@bp.get("/distribution-elections/<election_id>")
@endpoint(READ_ROLES)
def read_election(election_id):
    return responses.ok(serialize(services.get_election(election_id)))


@bp.get("/distribution-elections")
@endpoint(READ_ROLES)
def list_elections():
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    election_type = v.query_str("election_type")
    approval_status = v.query_str("approval_status")
    payment_status = v.query_str("payment_status")
    rows = sorted_rows(DB.distribution_elections)
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if election_type is not None:
        rows = [r for r in rows if r["election_type"] == election_type]
    if approval_status is not None:
        rows = [r for r in rows if r["approval_status"] == approval_status]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    return services.paged(rows, limit, offset)


@bp.post("/distribution-elections/<election_id>/commence")
@endpoint([PLAN_ADMINISTRATOR])
def commence_election(election_id):
    election = services.get_election(election_id)
    participant = services.get_participant(election["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if election["approval_status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")
    if plan["current_share_price_cents"] <= 0:
        fail("ERR_NO_APPROVED_VALUATION")

    commenced_at = CLOCK.today()
    if election["election_type"] == "DIVERSIFICATION" or plan["distribution_policy"] == "LUMP_SUM":
        installment_count = 1
    else:
        installment_count = calc.INSTALLMENT_YEARS

    election["approval_status"] = "APPROVED"
    election["approved_shares"] = election["requested_shares"]
    election["commenced_at_date"] = commenced_at.isoformat()
    election["installment_count"] = installment_count
    touch(election)

    for row in calc.installment_plan(election["approved_shares"], installment_count, commenced_at):
        insert(DB.installment_payments, {
            "distribution_election_id": election["id"],
            "sequence_number": row["sequence_number"],
            "scheduled_date": row["scheduled_date"],
            "shares_scheduled": row["shares_scheduled"],
            "shares_delivered": 0,
            "paid_date": None,
            "status": "SCHEDULED",
        })

    return responses.ok(serialize(election))


@bp.get("/installment-payments/<installment_id>")
@endpoint(READ_ROLES)
def read_installment(installment_id):
    return responses.ok(serialize(services.get_installment(installment_id)))


@bp.get("/installment-payments")
@endpoint(READ_ROLES)
def list_installments():
    limit, offset = v.pagination()
    election_id = v.query_str("distribution_election_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.installment_payments)
    if election_id is not None:
        rows = [r for r in rows if r["distribution_election_id"] == election_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    # sequence_number ascending within an election, created_at ascending across elections
    group_key = {}
    for row in sorted_rows(DB.installment_payments):
        key = row["distribution_election_id"]
        if key not in group_key:
            group_key[key] = (row["created_at"], row["_seq"])
    rows = sorted(rows, key=lambda r: (group_key[r["distribution_election_id"]],
                                       r["sequence_number"]))
    return services.paged(rows, limit, offset)


@bp.post("/installment-payments/<installment_id>/pay")
@endpoint([PLAN_ADMINISTRATOR])
def pay_installment(installment_id):
    installment = services.get_installment(installment_id)
    election = services.get_election(installment["distribution_election_id"])
    participant = services.get_participant(election["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    # priority 9 -- target state
    if installment["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if election["approval_status"] != "APPROVED":
        fail("ERR_INVALID_STATE")
    if participant["allocated_shares"] < installment["shares_scheduled"]:
        fail("ERR_INVALID_STATE", "The participant no longer holds the scheduled shares.")

    today = CLOCK.today()

    # priority 16 -- the put option window cooling buffer
    if not calc.put_window_buffer_ok(today, participant["last_put_window_close_date"]):
        fail("ERR_PUT_WINDOW_BUFFER_VIOLATION")

    # priority 18 -- due and in sequence
    if today < calc.iso_to_date(installment["scheduled_date"]):
        fail("ERR_INSTALLMENT_NOT_DUE")
    for sibling in DB.installment_payments.values():
        if (sibling["distribution_election_id"] == election["id"]
                and sibling["sequence_number"] < installment["sequence_number"]
                and sibling["status"] != "PAID"):
            fail("ERR_INSTALLMENT_NOT_DUE")

    delivered = installment["shares_scheduled"]
    installment["status"] = "PAID"
    installment["shares_delivered"] = delivered
    installment["paid_date"] = today.isoformat()
    touch(installment)

    participant["allocated_shares"] -= delivered
    services.recompute_vested_shares(participant)
    participant["distributed_shares_cumulative"] += delivered
    if election["election_type"] == "DIVERSIFICATION":
        participant["diversified_shares_cumulative"] += delivered

    window_open, window_close = calc.put_window_candidate(today)
    participant["put_window_open_date"] = window_open.isoformat()
    participant["put_window_close_date"] = window_close.isoformat()
    participant["last_put_window_close_date"] = window_close.isoformat()

    plan["total_plan_shares"] -= delivered
    plan["allocated_shares_total"] -= delivered

    remaining_scheduled = any(
        row["distribution_election_id"] == election["id"] and row["status"] == "SCHEDULED"
        for row in DB.installment_payments.values())
    next_payment_status = "IN_PROGRESS" if remaining_scheduled else "COMPLETED"
    if election["payment_status"] != next_payment_status:
        election["payment_status"] = next_payment_status
        touch(election)

    if (election["payment_status"] == "COMPLETED"
            and participant["allocated_shares"] == 0
            and participant["status"] in SEPARATED_STATUSES):
        participant["status"] = "DISTRIBUTED"
        services.refresh_diversification(participant, plan)

    touch(participant)
    touch(plan)
    return responses.ok(serialize(installment))

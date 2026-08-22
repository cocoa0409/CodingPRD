"""Allocation run endpoints (PRD 3.5, 3.6)."""

from datetime import date

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import PLAN_ADMINISTRATOR, READ_ROLES, TRUSTEE, caller_id, endpoint
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("allocations", __name__)


@bp.post("/allocation-runs")
@endpoint([PLAN_ADMINISTRATOR])
def create_run():
    body = v.body()
    plan_id = v.req_string(body, "plan_id")
    valuation_id = v.req_string(body, "valuation_id")
    plan_year = v.req_integer(body, "plan_year")
    contributed_shares = v.req_integer(body, "contributed_shares", minimum=0)
    expected_plan_version = v.req_integer(body, "expected_plan_version")

    plan = services.get_plan(plan_id)
    services.get_valuation(valuation_id)
    services.check_not_frozen(plan)

    if expected_plan_version != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION")

    run = insert(DB.allocation_runs, {
        "plan_id": plan_id,
        "valuation_id": valuation_id,
        "plan_year": plan_year,
        "contributed_shares": contributed_shares,
        "created_by_user_id": caller_id(),
        "finalized_by_user_id": None,
        "released_shares_snapshot": 0,
        "forfeiture_shares_snapshot": 0,
        "pool_shares": 0,
        "share_price_cents": 0,
        "eligible_participant_count": 0,
        "total_capped_compensation_cents": 0,
        "capped_participant_count": 0,
        "passes_executed": 0,
        "residual_shares": 0,
        "status": "DRAFT",
        "void_reason": None,
    })

    plan["draft_run_count"] += 1
    touch(plan)
    return responses.ok(serialize(run), 201)


@bp.get("/allocation-runs/<run_id>")
@endpoint(READ_ROLES)
def read_run(run_id):
    return responses.ok(serialize(services.get_run(run_id)))


@bp.get("/allocation-runs")
@endpoint(READ_ROLES)
def list_runs():
    limit, offset = v.pagination()
    plan_id = v.query_str("plan_id")
    valuation_id = v.query_str("valuation_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.allocation_runs)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if valuation_id is not None:
        rows = [r for r in rows if r["valuation_id"] == valuation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return services.paged(rows, limit, offset)


@bp.post("/allocation-runs/<run_id>/finalize")
@endpoint([PLAN_ADMINISTRATOR])
def finalize_run(run_id):
    run = services.get_run(run_id)
    plan = services.get_plan(run["plan_id"])
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "VALUATION_PENDING")

    if run["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if caller_id() == run["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    valuation = DB.valuations.get(run["valuation_id"])
    if valuation is None or valuation["status"] != "APPROVED":
        fail("ERR_NO_APPROVED_VALUATION")
    if (valuation["plan_id"] != run["plan_id"]
            or run["plan_year"] != valuation["plan_year"]
            or run["plan_year"] != plan["plan_year"]):
        fail("ERR_ENTITY_MISMATCH")

    eligible = [p for p in services.participants_of_plan(plan["id"])
                if p["status"] == "ACTIVE" and p["eligible_compensation_cents"] > 0]
    if not eligible:
        fail("ERR_NO_ELIGIBLE_PARTICIPANTS")

    share_price_cents = valuation["share_price_cents"]
    released_snapshot = plan["unallocated_released_shares"]
    forfeiture_snapshot = plan["unallocated_forfeiture_shares"]
    pool_shares = released_snapshot + forfeiture_snapshot + run["contributed_shares"]

    members = []
    for index, participant in enumerate(eligible):
        capped = min(participant["eligible_compensation_cents"],
                     plan["annual_compensation_limit_cents"])
        members.append({"key": participant["id"], "capped": capped, "order": index})
    total_capped = sum(m["capped"] for m in members)

    max_shares_cap = calc.floor_div(plan["annual_additions_limit_cents"], share_price_cents)
    outcome = calc.run_allocation_passes(pool_shares, members, max_shares_cap)
    residual_shares = outcome["residual_shares"]

    if plan["forfeiture_policy"] == "REDUCE_CONTRIBUTION" and residual_shares > 0:
        fail("ERR_ANNUAL_ADDITIONS_EXCEEDED")

    # ---- commit
    run["status"] = "FINALIZED"
    run["finalized_by_user_id"] = caller_id()
    run["share_price_cents"] = share_price_cents
    run["released_shares_snapshot"] = released_snapshot
    run["forfeiture_shares_snapshot"] = forfeiture_snapshot
    run["pool_shares"] = pool_shares
    run["eligible_participant_count"] = len(eligible)
    run["total_capped_compensation_cents"] = total_capped
    run["passes_executed"] = outcome["passes_executed"]
    run["residual_shares"] = residual_shares

    capped_participant_count = 0
    for member, participant in zip(members, eligible):
        award = outcome["award"][member["key"]]
        gross = outcome["gross"][member["key"]]
        is_capped = (award == max_shares_cap)
        if is_capped:
            capped_participant_count += 1
        insert(DB.share_allocations, {
            "allocation_run_id": run["id"],
            "participant_id": participant["id"],
            "capped_compensation_cents": member["capped"],
            "max_shares_cap": max_shares_cap,
            "gross_shares_before_cap": gross,
            "remainder_shares_awarded": outcome["remainder_awarded"][member["key"]],
            "excess_shares_removed": gross - award,
            "allocated_shares": award,
            "annual_additions_cents": award * share_price_cents,
            "capped": is_capped,
        }, common_fields=False)
    run["capped_participant_count"] = capped_participant_count
    touch(run)

    measurement_date = date(run["plan_year"], 12, 31)
    for member, participant in zip(members, eligible):
        award = outcome["award"][member["key"]]
        opening_shares = participant["allocated_shares"]
        participant["allocated_shares"] = opening_shares + award
        years, percentage = calc.participant_vesting(
            participant["hire_date"], measurement_date, plan["vesting_schedule"],
            participant["termination_reason"])
        participant["years_of_service"] = years
        participant["vested_percentage"] = percentage
        services.recompute_vested_shares(participant)
        touch(participant)

        forfeited_this_year = sum(
            e["forfeited_shares"] for e in DB.forfeiture_events.values()
            if e["participant_id"] == participant["id"] and e["plan_year"] == run["plan_year"])
        closing_shares = opening_shares + award
        insert(DB.participant_statements, {
            "participant_id": participant["id"],
            "allocation_run_id": run["id"],
            "plan_year": run["plan_year"],
            "opening_shares": opening_shares,
            "shares_allocated": award,
            "forfeited_shares_this_year": forfeited_this_year,
            "closing_shares": closing_shares,
            "share_price_cents": share_price_cents,
            "vested_percentage": participant["vested_percentage"],
            "vested_value_cents": calc.vested_value_cents(
                closing_shares, participant["vested_percentage"], share_price_cents),
            "total_value_cents": closing_shares * share_price_cents,
            "diversification_eligible": participant["diversification_eligible"],
            "delivery_status": "GENERATED",
            "delivery_channel": None,
        })

    for event in sorted_rows(DB.forfeiture_events):
        if event["plan_id"] == plan["id"] and event["status"] == "PENDING_REALLOCATION":
            event["status"] = "REALLOCATED"
            event["reallocated_in_run_id"] = run["id"]
            touch(event)

    plan["unallocated_released_shares"] = 0
    plan["unallocated_forfeiture_shares"] = residual_shares
    plan["total_plan_shares"] += run["contributed_shares"]
    plan["allocated_shares_total"] += pool_shares - residual_shares
    services.recompute_forfeiture_posture(plan)
    plan["draft_run_count"] -= 1
    plan["plan_status"] = "ALLOCATION_LOCKED"
    touch(plan)

    return responses.ok(serialize(run))


@bp.post("/allocation-runs/<run_id>/void")
@endpoint([TRUSTEE])
def void_run(run_id):
    body = v.body()
    reason = v.req_string(body, "reason")

    run = services.get_run(run_id)
    plan = services.get_plan(run["plan_id"])
    services.check_not_frozen(plan)

    if run["status"] == "FINALIZED":
        services.require_plan_status(plan, "ALLOCATION_LOCKED")
    if run["status"] not in ("DRAFT", "FINALIZED"):
        fail("ERR_INVALID_STATE")

    if run["status"] == "DRAFT":
        run["status"] = "VOID"
        run["void_reason"] = reason
        touch(run)
        plan["draft_run_count"] -= 1
        touch(plan)
        return responses.ok(serialize(run))

    # --- compensating reversal of a FINALIZED run
    for line in sorted_rows(DB.share_allocations):
        if line["allocation_run_id"] != run["id"]:
            continue
        participant = DB.participants.get(line["participant_id"])
        if participant is None:
            continue
        participant["allocated_shares"] -= line["allocated_shares"]
        services.recompute_vested_shares(participant)
        touch(participant)

    plan["allocated_shares_total"] -= run["pool_shares"] - run["residual_shares"]
    plan["unallocated_released_shares"] = run["released_shares_snapshot"]
    plan["unallocated_forfeiture_shares"] = run["forfeiture_shares_snapshot"]
    plan["total_plan_shares"] -= run["contributed_shares"]

    for event in sorted_rows(DB.forfeiture_events):
        if event["reallocated_in_run_id"] == run["id"]:
            event["status"] = "PENDING_REALLOCATION"
            event["reallocated_in_run_id"] = None
            touch(event)

    for statement_id in [s["id"] for s in DB.participant_statements.values()
                         if s["allocation_run_id"] == run["id"]]:
        del DB.participant_statements[statement_id]

    services.recompute_forfeiture_posture(plan)
    plan["plan_status"] = "VALUATION_PENDING"

    run["status"] = "VOID"
    run["void_reason"] = reason
    touch(run)
    touch(plan)
    return responses.ok(serialize(run))


@bp.get("/share-allocations/<allocation_id>")
@endpoint(READ_ROLES)
def read_share_allocation(allocation_id):
    return responses.ok(serialize(services.lookup("share_allocations", allocation_id)))


@bp.get("/share-allocations")
@endpoint(READ_ROLES)
def list_share_allocations():
    limit, offset = v.pagination()
    allocation_run_id = v.query_str("allocation_run_id")
    participant_id = v.query_str("participant_id")
    rows = sorted_rows(DB.share_allocations)
    if allocation_run_id is not None:
        rows = [r for r in rows if r["allocation_run_id"] == allocation_run_id]
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    return services.paged(rows, limit, offset)

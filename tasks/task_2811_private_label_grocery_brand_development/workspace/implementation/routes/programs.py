"""Brand programs and category gaps."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db, now
from domain import (
    TERMINAL_DEV_STATUS,
    capture,
    PROGRAM_COUNTERS,
    available_budget,
    get_gap,
    get_program,
    guard_program_open,
    items_of_program,
    new_row,
    program_of_gap,
    refresh_active_item_count,
    runs_of_program,
    touch,
    touch_if_moved,
)
from errors import fail
from listing import GAP_STATUS_SET, PROGRAM_STATUS_SET, TIER_SET, no_query, paginate
from middleware import (
    ALL_ROLES,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SOURCING_MANAGER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response

bp = Blueprint("programs", __name__)


@bp.post("/private-label/programs")
def create_program():
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    body = validate_body(
        {
            "brand_name": Field("string", required=True),
            "retailer_name": Field("string", required=True),
            "fiscal_year": Field(
                "integer",
                required=True,
                check=lambda v: 2020 <= v <= 2100,
                detail="must be a whole year from 2020 through 2100 inclusive",
            ),
            "dev_budget_cents": Field(
                "integer", required=True, check=lambda v: v >= 0, detail="must not be negative"
            ),
        }
    )
    row = new_row(
        {
            "brand_name": body["brand_name"],
            "retailer_name": body["retailer_name"],
            "fiscal_year": body["fiscal_year"],
            "dev_budget_cents": body["dev_budget_cents"],
            "committed_budget_cents": 0,
            "lifetime_committed_cents": 0,
            "lifetime_released_cents": 0,
            "active_item_count": 0,
            "status": "ACTIVE",
        }
    )
    db.programs[row["id"]] = row
    return object_response(ser.program_out(row), 201)


@bp.get("/private-label/programs/<program_id>")
def read_program(program_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.program_out(get_program(program_id)))


@bp.get("/private-label/programs")
def list_programs():
    authenticate(ALL_ROLES)
    return paginate(
        db.programs,
        {"status": PROGRAM_STATUS_SET, "fiscal_year": "integer"},
        ser.program_out,
        descending=True,
    )


@bp.get("/private-label/programs/<program_id>/budget-ledger")
def read_budget_ledger(program_id):
    authenticate(ALL_ROLES)
    no_query()
    program = get_program(program_id)
    return object_response(
        {
            "program_id": program["id"],
            "dev_budget_cents": program["dev_budget_cents"],
            "committed_budget_cents": program["committed_budget_cents"],
            "available_budget_cents": available_budget(program),
            "lifetime_committed_cents": program["lifetime_committed_cents"],
            "lifetime_released_cents": program["lifetime_released_cents"],
            "active_item_count": program["active_item_count"],
        }
    )


@bp.post("/private-label/programs/<program_id>/lifecycle")
def program_lifecycle(program_id):
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    body = validate_body(
        {
            "action": Field(
                "string",
                required=True,
                enum=frozenset(("START_RELAUNCH", "COMPLETE_RELAUNCH", "CLOSE")),
            )
        }
    )
    program = get_program(program_id)
    action = body["action"]
    guard_program_open(program)
    if action == "START_RELAUNCH":
        if program["status"] != "ACTIVE":
            fail("ERR_RELAUNCH_INCOMPLETE", "A relaunch is already under way for this program.")
        launched = [
            row
            for row in items_of_program(program["id"])
            if row["development_status"] in ("LAUNCHED", "RELAUNCH_PENDING")
        ]
        if not launched:
            fail("ERR_NO_LAUNCHED_ITEMS")
        program["status"] = "RELAUNCH_FREEZE"
    elif action == "COMPLETE_RELAUNCH":
        if program["status"] != "RELAUNCH_FREEZE":
            fail("ERR_RELAUNCH_INCOMPLETE", "The program is not in a relaunch freeze.")
        pending = [
            row
            for row in items_of_program(program["id"])
            if row["development_status"] == "RELAUNCH_PENDING"
        ]
        if pending:
            fail("ERR_RELAUNCH_INCOMPLETE")
        program["status"] = "ACTIVE"
    else:
        if program["status"] != "ACTIVE":
            fail("ERR_RELAUNCH_INCOMPLETE", "A program in a relaunch freeze cannot be closed.")
        live = [
            row
            for row in runs_of_program(program["id"])
            if row["status"] in ("SCHEDULED", "APPROVED", "HOLD")
        ]
        if live:
            fail("ERR_ACTIVE_RUNS_PRESENT")
        program["status"] = "CLOSED"
        for gap in db.gaps.values():
            if gap["program_id"] == program["id"] and gap["status"] in ("DRAFT", "ANALYZED"):
                gap["status"] = "REJECTED"
                touch(gap)
    touch(program)
    return object_response(ser.program_out(program))


@bp.post("/private-label/category-gaps")
def create_gap():
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {
            "program_id": Field("string", required=True),
            "category_code": Field("string", required=True),
            "national_brand_name": Field("string", required=True),
            "nb_retail_price_cents": Field(
                "integer", required=True, check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
            "category_annual_sales_cents": Field(
                "integer", required=True, check=lambda v: v >= 0, detail="must not be negative"
            ),
            "pl_share_pct": Field(
                "number",
                required=True,
                check=lambda v: 0.0 <= v <= 100.0,
                detail="must be between 0.0 and 100.0 inclusive",
            ),
            "unit_velocity_per_week": Field(
                "number", required=True, check=lambda v: v >= 0, detail="must not be negative"
            ),
            "shelf_slots_quota": Field(
                "integer", required=True, check=lambda v: v >= 1, detail="must be at least 1"
            ),
        }
    )
    program = get_program(body["program_id"])
    guard_program_open(program)
    row = new_row(
        {
            "program_id": program["id"],
            "category_code": body["category_code"],
            "national_brand_name": body["national_brand_name"],
            "nb_retail_price_cents": body["nb_retail_price_cents"],
            "category_annual_sales_cents": body["category_annual_sales_cents"],
            "pl_share_pct": body["pl_share_pct"],
            "unit_velocity_per_week": body["unit_velocity_per_week"],
            "shelf_slots_quota": body["shelf_slots_quota"],
            "slots_consumed": 0,
            "slots_open": body["shelf_slots_quota"],
            "slots_consumed_lifetime": 0,
            "slots_released_lifetime": 0,
            "gap_score": None,
            "recommended_tier": None,
            "approved_tier": None,
            "override_justification": None,
            "status": "DRAFT",
        }
    )
    db.gaps[row["id"]] = row
    return object_response(ser.gap_out(row), 201)


@bp.get("/private-label/category-gaps/<gap_id>")
def read_gap(gap_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.gap_out(get_gap(gap_id)))


@bp.get("/private-label/category-gaps")
def list_gaps():
    authenticate(ALL_ROLES)
    return paginate(
        db.gaps,
        {"program_id": "string", "status": GAP_STATUS_SET, "recommended_tier": TIER_SET},
        ser.gap_out,
    )


@bp.post("/private-label/category-gaps/<gap_id>/analyze")
def analyze_gap(gap_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {
            "category_annual_sales_cents": Field(
                "integer", check=lambda v: v >= 0, detail="must not be negative"
            ),
            "pl_share_pct": Field(
                "number",
                check=lambda v: 0.0 <= v <= 100.0,
                detail="must be between 0.0 and 100.0 inclusive",
            ),
            "unit_velocity_per_week": Field(
                "number", check=lambda v: v >= 0, detail="must not be negative"
            ),
            "nb_retail_price_cents": Field(
                "integer", check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
        }
    )
    gap = get_gap(gap_id)
    guard_program_open(program_of_gap(gap))
    if gap["status"] not in ("DRAFT", "ANALYZED"):
        fail("ERR_GAP_STATE_INVALID")
    # Restated values land on the gap first; the score is then computed from stored values.
    for name in (
        "category_annual_sales_cents",
        "pl_share_pct",
        "unit_velocity_per_week",
        "nb_retail_price_cents",
    ):
        if name in body["_supplied"]:
            gap[name] = body[name]
    score, tier = calc.category_gap_score(
        gap["category_annual_sales_cents"],
        gap["pl_share_pct"],
        gap["unit_velocity_per_week"],
        gap["nb_retail_price_cents"],
    )
    gap["gap_score"] = score
    gap["recommended_tier"] = tier
    gap["status"] = "ANALYZED"
    touch(gap)
    return object_response(ser.gap_out(gap))


@bp.post("/private-label/category-gaps/<gap_id>/tier-decision")
def gap_tier_decision(gap_id):
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    body = validate_body(
        {
            "decision": Field("string", required=True, enum=frozenset(("APPROVE", "REJECT"))),
            "approved_tier": Field("string", enum=TIER_SET),
            "override_justification": Field("string"),
        }
    )
    if body["decision"] == "APPROVE" and body["approved_tier"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'approved_tier' is required when approving a tier.")
    gap = get_gap(gap_id)
    guard_program_open(program_of_gap(gap))
    if gap["status"] != "ANALYZED":
        fail("ERR_GAP_NOT_ANALYZED")
    if body["decision"] == "APPROVE":
        justification = body["override_justification"]
        if body["approved_tier"] != gap["recommended_tier"]:
            if justification is None or justification.strip() == "":
                fail("ERR_OVERRIDE_JUSTIFICATION_REQUIRED")
        gap["approved_tier"] = body["approved_tier"]
        if justification is not None:
            gap["override_justification"] = justification
        gap["status"] = "TIER_APPROVED"
    else:
        gap["status"] = "REJECTED"
    touch(gap)
    return object_response(ser.gap_out(gap))

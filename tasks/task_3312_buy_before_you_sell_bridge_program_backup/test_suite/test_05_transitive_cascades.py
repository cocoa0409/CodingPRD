"""Depth chains: one transition drags several records with it (PRD 3.4, 3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, assert_version_incremented,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, occupy_new_home, complete_repairs, draft_listing,
    setup_referral, create_task, get_program, record_carrying_cost,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _cascade_scenario():
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "15 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "16 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=34_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    occupy_new_home(program["id"], sc["homeowner"]["id"])
    complete_repairs(sc["departing"]["id"], visits=3)
    agent, referral = setup_referral(program["id"], qualified=False)
    listing = draft_listing(sc["departing"]["id"], program["id"], list_price_cents=44_000_000)
    sc.update({"program": program, "loan": loan, "agent": agent,
               "referral": referral, "listing": listing})
    return sc


def test_go_live_escalates_overdue_tasks_opens_occupancy_and_lists_the_property(api):
    """PRD section 3.6: "When all of that holds, going live sets the listing to `LIVE` and
    its `marketing_status` to `ACTIVE`, stamps the listing's `listed_at` from the logical
    clock, sets the property's `listing_status` to `LISTED`, and moves the program's
    occupancy axis to `DEPARTING_LISTED`."

    PRD section 3.6: "It also performs a sweep: every coordination task belonging to the
    program that is still `OPEN` and whose `due_date` has already passed the logical clock
    is escalated to `IN_PROGRESS` in the same operation."

    Design: Difficulty/transitive_cascade/cascade_listing_go_live_depth4
    """
    reset_clock()
    sc = _cascade_scenario()
    # A task whose due date 2026-08-25 already precedes the 2026-09-01 clock.
    task = create_task(sc["program"]["id"], sc["referral"]["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-08-25T00:00:00Z")

    live = validate_success(api.go_live_listing(sc["listing"]["id"], COORD), 200)
    assert live["status"] == "LIVE"

    program = get_program(sc["program"]["id"])
    assert program["occupancy_status"] == "DEPARTING_LISTED", "hop 1: the occupancy axis moved"

    prop = validate_success(api.get_property(sc["departing"]["id"], COORD), 200)
    assert prop["listing_status"] == "LISTED", "hop 2: the property is now listed"

    task_after = validate_success(api.get_coordination_task(task["id"], COORD), 200)
    assert task_after["status"] == "IN_PROGRESS", "hop 3: the overdue task was escalated"


def test_go_live_returns_the_marketing_side_effect_on_the_property(api):
    """PRD section 3.6: "When all of that holds, going live sets the listing to `LIVE` and
    its `marketing_status` to `ACTIVE`, stamps the listing's `listed_at` from the logical
    clock, sets the property's `listing_status` to `LISTED`, and moves the program's
    occupancy axis to `DEPARTING_LISTED`."

    Design: Corner/state_machines/listing_go_live_sets_property_marketing_side_effect
    """
    reset_clock()
    sc = _cascade_scenario()
    live = validate_success(api.go_live_listing(sc["listing"]["id"], COORD), 200)
    assert live["status"] == "LIVE"
    assert live["marketing_status"] == "ACTIVE"
    assert live["listed_at"] is not None, "listed_at is stamped from the logical clock"

    prop = validate_success(api.get_property(sc["departing"]["id"], COORD), 200)
    assert prop["listing_status"] == "LISTED"


def test_go_live_bumps_the_referral_it_touched(api):
    """PRD section 3.7: "when the completed task is the referral's last open task, the
    system re-evaluates whether the referral can now be backfilled as complete, stamps the
    task's `completed_at` from the logical clock, and recomputes the agent's
    `active_referral_count`."

    PRD section 3.6: "It also performs a sweep: every coordination task belonging to the
    program that is still `OPEN` and whose `due_date` has already passed the logical clock
    is escalated to `IN_PROGRESS` in the same operation."

    Design: Difficulty/transitive_cascade/cascade_listing_go_live_depth4
    """
    reset_clock()
    sc = _cascade_scenario()
    task = create_task(sc["program"]["id"], sc["referral"]["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-08-25T00:00:00Z")
    referral_before = validate_success(
        api.get_referral(sc["referral"]["id"], COORD), 200)

    validate_success(api.go_live_listing(sc["listing"]["id"], COORD), 200)

    referral_after = validate_success(
        api.get_referral(sc["referral"]["id"], COORD), 200)
    assert referral_after["version"] > referral_before["version"], (
        "the escalated task's referral was recomputed as a side effect"
    )
    assert validate_success(api.get_coordination_task(task["id"], COORD), 200)[
        "status"] == "IN_PROGRESS"


def test_down_payment_disbursement_carries_loan_program_and_household_with_it(api):
    """PRD section 3.4: "The disbursement raises the loan's `drawn_cents` by the advance
    amount, recomputes the loan's `outstanding_principal_cents` and
    `accrued_interest_cents`, and, when the advance is the down payment, moves the
    program's advance axis to `FUNDED` and the household's `program_status` to `BRIDGED`."

    Design: Difficulty/transitive_cascade/cascade_advance_disbursement_depth3
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "17 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "18 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])

    advance = validate_success(api.create_bridge_advance(
        {"bridge_program_id": program["id"], "interim_loan_id": loan["id"],
         "purpose": "DOWN_PAYMENT", "amount_cents": 8_000_000}, COORD), 201)
    validate_success(api.approve_bridge_advance(advance["id"],
                     TEST_USERS["underwriter_headers"]), 200)
    disbursed = validate_success(api.disburse_bridge_advance(advance["id"], COORD), 200)
    assert disbursed["status"] == "DISBURSED"


def test_down_payment_disbursement_chain_lands_on_loan_program_and_household(api):
    """PRD section 3.4: "The disbursement raises the loan's `drawn_cents` by the advance
    amount, recomputes the loan's `outstanding_principal_cents` and
    `accrued_interest_cents`, and, when the advance is the down payment, moves the
    program's advance axis to `FUNDED` and the household's `program_status` to `BRIDGED`."

    Design: Difficulty/transitive_cascade/cascade_advance_disbursement_depth3
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "17 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "18 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    advance = validate_success(api.create_bridge_advance(
        {"bridge_program_id": program["id"], "interim_loan_id": loan["id"],
         "purpose": "DOWN_PAYMENT", "amount_cents": 8_000_000}, COORD), 201)
    validate_success(api.approve_bridge_advance(advance["id"],
                     TEST_USERS["underwriter_headers"]), 200)
    validate_success(api.disburse_bridge_advance(advance["id"], COORD), 200)

    loan_after = validate_success(api.get_interim_loan(loan["id"], COORD), 200)
    assert loan_after["status"] == "DRAWN", "hop 1: the loan left ORIGINATED"
    assert loan_after["drawn_cents"] == 8_000_000
    assert loan_after["outstanding_principal_cents"] == 8_000_000

    program_after = get_program(program["id"])
    assert program_after["advance_status"] == "FUNDED", "hop 2: the money axis advanced"

    household_after = validate_success(
        api.get_homeowner(sc["homeowner"]["id"], COORD), 200)
    assert household_after["program_status"] == "BRIDGED", "hop 3: the household bridged"
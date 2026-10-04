"""Combinatorial capacity arithmetic and the disclosure evaluation-order trap (PRD 3.2, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, program_summary,
    setup_referral, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _qualify(api, sc, variant="CONSERVATIVE", target=50_000_000):
    return validate_success(api.create_qualification(
        {"homeowner_id": sc["homeowner"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "new_property_id": sc["new"]["id"],
         "target_purchase_price_cents": target, "variant_used": variant}, COORD), 201)


def test_capacity_combines_condition_credit_equity_and_the_income_clamp(api):
    """PRD section 3.2: "The credit is zero for a home graded `D`, and grows by 500 basis
    points for each grade above the worst: a `C` home earns 500 basis points of credit, a
    `B` home earns 1000, and an `A` home earns 1500. That credit is added to the
    7000-basis-point base and the sum is applied to equity."

    PRD section 3.2: "The capacity may not exceed the household's `household_income_cents`
    multiplied by 50000 and divided by 10000 — that is, five times annual income — and
    whenever the computed capacity would exceed that ceiling it is lowered to the ceiling."

    Design: Difficulty/combinatorial_formula/purchase_capacity_nested_min_max
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "5 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "A"},
    )
    q = _qualify(api, sc)
    # equity 30000000, credited ratio 7000 + 1500 = 8500 bps -> 25500000.
    # The income ceiling is 10000000 * 5 = 50000000, so the clamp does not bind.
    assert q["capacity_cents"] == 25_500_000
    assert q["capacity_cents"] < sc["homeowner"]["household_income_cents"] * 5, (
        "the income ceiling is not the binding term in this scenario"
    )


@pytest.mark.parametrize("grade,expected_capacity", [
    ("D", 21_000_000),
    ("C", 22_500_000),
    ("B", 24_000_000),
    ("A", 25_500_000),
])
def test_capacity_condition_credit_ladder_is_five_hundred_bps_per_grade(api, grade, expected_capacity):
    """PRD section 3.2: "The credit is zero for a home graded `D`, and grows by 500 basis
    points for each grade above the worst: a `C` home earns 500 basis points of credit, a
    `B` home earns 1000, and an `A` home earns 1500."

    Design: Difficulty/combinatorial_formula/purchase_capacity_nested_min_max
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "6 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": grade},
    )
    q = _qualify(api, sc)
    # equity 30000000 with credited ratio 7000 + credit_bps
    assert q["capacity_cents"] == expected_capacity


def _disclosure_scenario():
    """An approved OPTIMISTIC qualification enrolling a program with one open referral."""
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "7 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "8 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4,
                               program_fee_basis_points=150)
    program, loan = fund_program(bp["id"])
    setup_referral(program["id"], qualified=False)
    return sc, program, loan


def test_disclosure_reports_origination_coordination_and_escalator_components(api):
    """PRD section 3.9: "The origination charge is the interim loan's `principal_cents`
    multiplied by the program's `program_fee_basis_points` and divided by ten thousand. The
    coordination charge is a flat 45000 cents for a single active referral"

    PRD section 3.9: "When the subtotal exceeds `DISCLOSURE_MIN_CENTS`, which is 300000
    cents, the escalator is a percentage of the actual subtotal — 500 basis points of it
    when the subtotal also exceeds `DISCLOSURE_REVIEW_CENTS` of 500000 cents, and 250 basis
    points of it when it does not."

    Design: Difficulty/combinatorial_formula/disclosure_evaluation_order_trap
    """
    reset_clock()
    exec_ = _disclosure_scenario()
    sc, program, loan = exec_
    summary = program_summary(program["id"])
    # capacity = 40000000 * (7000 + 1000 + 1000) // 10000 = 36000000 = loan principal
    assert loan["principal_cents"] == 36_000_000
    assert summary["origination_cents"] == 540_000, "36000000 * 150 // 10000"
    assert summary["coordination_cents"] == 45_000


def test_disclosure_escalator_tracks_the_actual_subtotal_above_the_review_tier(api):
    """PRD section 3.9: "When the subtotal exceeds `DISCLOSURE_MIN_CENTS`, which is
    300000 cents, the escalator is a percentage of the actual subtotal — 500 basis points
    of it when the subtotal also exceeds `DISCLOSURE_REVIEW_CENTS` of 500000 cents, and
    250 basis points of it when it does not."

    PRD section 3.9: "Each term floors, including the escalator itself, and the
    `total_program_charge_cents` is the subtotal plus the floored escalator."

    Design: Difficulty/combinatorial_formula/disclosure_evaluation_order_trap
    """
    reset_clock()
    sc, program, loan = _disclosure_scenario()
    summary = program_summary(program["id"])
    subtotal = summary["origination_cents"] + summary["coordination_cents"]
    assert subtotal == 585_000, "origination 540000 + flat coordination 45000"
    assert subtotal > 500_000, "this subtotal sits in the high escalation tier"
    assert summary["escalator_cents"] == 29_250, "585000 * 500 // 10000"
    assert summary["total_program_charge_cents"] == 614_250, "subtotal plus floored escalator"
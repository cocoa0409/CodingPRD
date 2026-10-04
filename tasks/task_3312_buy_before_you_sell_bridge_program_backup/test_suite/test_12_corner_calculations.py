"""Referral fee reconciliation and the disclosure tier boundaries (PRD 3.7, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, assert_referral,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, program_summary, setup_referral, create_task,
    complete_task,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _program_for_referral(income_cents=30_000_000):
    sc = build_qualified_household(
        income_cents=income_cents,
        departing={"address": "15 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    sc["qualification"], sc["program"] = q, bp
    return sc


def test_referral_base_fee_is_the_volume_times_the_rate(api):
    """PRD section 3.7: "The base term is the referral's `qualifying_volume_cents` multiplied
    by its `referral_rate_bps` and divided by ten thousand; this is the `base_fee_cents`, and
    it is rounded half-up to the nearest cent, as are the other computed fee fields."

    Design: Corner/calculations/referral_fee_qualified_bonus_and_credits
    """
    reset_clock()
    sc = _program_for_referral()
    agent, referral = setup_referral(sc["program"]["id"], qualified=True,
                                     role_scope="DEPARTING_SIDE",
                                     volume_cents=50_000_000, license_number="LIC-FEE")
    assert_referral(referral)
    # 50000000 * 250 // 10000
    assert referral["base_fee_cents"] == 1_250_000


def test_referral_reconciliation_adds_the_qualified_bonus_and_one_task_credit(api):
    """PRD section 3.7: "The second term is a bonus that depends on the agent's standing: an
    agent whose `qualification_status` is `QUALIFIED` earns a bonus of 300 basis points
    applied to the base, and any other agent earns no bonus at all."

    PRD section 3.7: "The third term is a coordination credit that rewards completed work but
    caps out: the number of the referral's coordination tasks that are `COMPLETED`,
    multiplied by 8000 cents each"

    Design: Corner/calculations/referral_fee_qualified_bonus_and_credits
    """
    reset_clock()
    sc = _program_for_referral()
    agent, referral = setup_referral(sc["program"]["id"], qualified=True,
                                     role_scope="DEPARTING_SIDE",
                                     volume_cents=50_000_000, license_number="LIC-FEE")
    task = create_task(sc["program"]["id"], referral["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-09-20T00:00:00Z")
    complete_task(task["id"])

    after = validate_success(api.get_referral(referral["id"], COORD), 200)
    # base 1250000 + 300-bps bonus 37500 + one completed task credit 8000 = 1295500
    assert after["reconciled_fee_cents"] == 1_295_500
    assert after["fee_variance_cents"] == 45_500
    assert after["fee_variance_cents"] == after["reconciled_fee_cents"] - after["base_fee_cents"]


def test_referral_coordination_credit_is_capped_at_twenty_thousand(api):
    """PRD section 3.7: "the whole of that capped at 20000 cents, so no more than 20000 cents
    of coordination credit can ever be earned by one referral."

    PRD section 3.7: "Tasks in `OPEN` or `IN_PROGRESS` count for nothing, and a `CANCELLED`
    task is excluded outright."

    Design: Corner/cross_cutting_layers/referral_credit_cap_at_threshold
    """
    reset_clock()
    sc = _program_for_referral()
    agent, referral = setup_referral(sc["program"]["id"], qualified=True,
                                     role_scope="DEPARTING_SIDE",
                                     volume_cents=50_000_000, license_number="LIC-CAP")
    # Three completed tasks would credit 3 * 8000 = 24000, above the 20000 cap.
    for kind, due in [
        ("PHOTOGRAPHY", "2026-09-20T00:00:00Z"),
        ("INSPECTION", "2026-10-20T00:00:00Z"),
        ("APPRAISAL", "2026-11-20T00:00:00Z"),
    ]:
        t = create_task(sc["program"]["id"], referral["id"], task_kind=kind, due_date=due)
        complete_task(t["id"])

    after = validate_success(api.get_referral(referral["id"], COORD), 200)
    assert after["base_fee_cents"] == 1_250_000
    # base 1250000 + bonus 37500 + capped credit 20000 (not 24000)
    assert after["reconciled_fee_cents"] == 1_307_500


def _disclosure_scenario(fee_bps: int):
    """A grade-A departing home whose conservative capacity makes the fee arithmetic integral.

    Equity 60000000 - 30000000 = 30000000; conservative ratio 7000 + 1500 = 8500 bps gives
    capacity 25500000, which funding originates as the loan principal.
    """
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "17 Def Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4,
                               program_fee_basis_points=fee_bps)
    program, loan = fund_program(bp["id"])
    setup_referral(program["id"], qualified=False)
    return sc, program, loan


def test_disclosure_at_exactly_the_minimum_uses_the_fixed_reference_base(api):
    """PRD section 3.9: "When the subtotal is at or below `DISCLOSURE_MIN_CENTS`, however, the
    escalator is deliberately not computed against the small actual subtotal: it is computed
    against the fixed reference `SUBTOTAL_REFERENCE_CENTS` of 400000 cents, at 250 basis
    points. That fixed reference is the evaluation-order trap in this calculation"

    Design: Corner/calculations/disclosure_min_tier_boundary_at_exact_threshold
    """
    reset_clock()
    sc, program, loan = _disclosure_scenario(fee_bps=100)
    assert loan["principal_cents"] == 25_500_000
    summary = program_summary(program["id"])
    # origination 25500000 * 100 // 10000 = 255000, plus the flat 45000 = exactly 300000.
    assert summary["origination_cents"] == 255_000
    subtotal = summary["origination_cents"] + summary["coordination_cents"]
    assert subtotal == 300_000, "the subtotal sits exactly on the minimum tier"
    assert summary["escalator_cents"] == 10_000, (
        "at or below the minimum the escalator uses the fixed 400000-cent reference at 250 bps"
    )
    assert summary["total_program_charge_cents"] == 310_000


def test_disclosure_just_above_the_minimum_tracks_the_actual_subtotal(api):
    """PRD section 3.9: "When the subtotal exceeds `DISCLOSURE_MIN_CENTS`, which is 300000
    cents, the escalator is a percentage of the actual subtotal — 500 basis points of it when
    the subtotal also exceeds `DISCLOSURE_REVIEW_CENTS` of 500000 cents, and 250 basis points
    of it when it does not."

    Design: Corner/calculations/disclosure_min_tier_boundary_at_exact_threshold
    """
    reset_clock()
    sc, program, loan = _disclosure_scenario(fee_bps=101)
    summary = program_summary(program["id"])
    # origination 25500000 * 101 // 10000 = 257550, plus 45000 = 302550.
    assert summary["origination_cents"] == 257_550
    subtotal = summary["origination_cents"] + summary["coordination_cents"]
    assert subtotal == 302_550
    assert subtotal > 300_000, "one basis point of fee pushed the subtotal over the tier"
    assert summary["escalator_cents"] == subtotal * 250 // 10000, (
        "above the minimum the low escalator rate tracks the actual subtotal"
    )


def test_distressed_grade_offer_price_floor_is_the_regulatory_minimum(api):
    """PRD section 3.6: "It is then compared against a regulatory floor set at 8500 basis
    points of the appraised value, and whichever of the two is the greater becomes the
    binding `price_basis_cents`."

    PRD section 3.6: "In practice a well-conditioned home graded `A` or `B` is bound by its
    discounted floor, while a distressed `C` or `D` home has been pushed by the condition
    modifier below the regulatory line and is bound by the regulatory floor instead."

    Design: Corner/calculations/backup_offer_regulatory_floor_binds_on_distressed_grade
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "19 Def Way", "appraised_value_cents": 50_000_000,
                   "mortgage_payoff_cents": 20_000_000, "condition_grade": "D"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    offer = validate_success(api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": bp["id"],
         "offer_price_cents": 43_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD), 201)
    # 50% less the 12% discount, then less the 600-bps D modifier, is 41360000, below the
    # 8500-bps regulatory floor of 42500000, so the regulatory floor binds.
    assert offer["price_basis_cents"] == 42_500_000
    assert offer["offer_price_cents"] == 43_000_000, "an offer at or above the floor is accepted"
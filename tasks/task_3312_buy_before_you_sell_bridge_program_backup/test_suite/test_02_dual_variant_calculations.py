"""Dual-variant calculations: the two readings of the same inputs diverge (PRD 3.2, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, record_carrying_cost, program_summary,
    BASE_EQUITY_RATIO_BPS, MARKET_APPRECIATION_BPS, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_capacity_conservative_and_optimistic_readings_diverge_verbatim(api):
    """PRD section 3.2: "Both then apply a base ratio that credits the household with
    7000 basis points of that equity, and both add a condition credit earned by the
    departing home's state of repair."

    PRD section 3.2: "The optimistic reading adds a further 1000 basis points of market
    appreciation to the ratio before applying it, so the optimistic capacity is at least
    1000 basis points of equity larger than the conservative figure for the same home."

    Design: Difficulty/dual_variant_calc/capacity_variant_divergence
    """
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "1 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    conservative = validate_success(api.create_qualification(
        {"homeowner_id": sc["homeowner"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "new_property_id": sc["new"]["id"],
         "target_purchase_price_cents": 50_000_000, "variant_used": "CONSERVATIVE"}, COORD), 201)
    optimistic = validate_success(api.create_qualification(
        {"homeowner_id": sc["homeowner"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "new_property_id": sc["new"]["id"],
         "target_purchase_price_cents": 50_000_000, "variant_used": "OPTIMISTIC"}, COORD), 201)

    # Net equity 60000000 - 30000000 = 30000000.
    # Condition credit for a grade-B home is 1000 bps (1000/500 = two grades
    # above the worst), so the credited ratio is 7000 + 1000 = 8000 bps.
    assert conservative["capacity_cents"] == 24_000_000, (
        "30000000 * 8000 // 10000 under the conservative reading"
    )
    assert optimistic["capacity_cents"] == 27_000_000, (
        "30000000 * (8000 + 1000) // 10000 under the optimistic reading"
    )
    assert optimistic["capacity_cents"] - conservative["capacity_cents"] == 3_000_000, (
        "the market-appreciation term is exactly 1000 bps of the same 30000000 equity"
    )


def test_capacity_reports_the_equity_ratio_to_four_decimals(api):
    """PRD section 3.2: "The `equity_ratio` reported alongside the capacity is the net
    departing equity divided by the appraised value of the departing home, carried to
    four decimal places."

    PRD section 3.2: "Both readings begin from the same equity figure: the departing
    property's `appraised_value_cents` minus its `mortgage_payoff_cents`."

    Design: Difficulty/dual_variant_calc/capacity_variant_divergence
    """
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "1 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = validate_success(api.create_qualification(
        {"homeowner_id": sc["homeowner"]["id"],
         "departing_property_id": sc["departing"]["id"],
         "new_property_id": sc["new"]["id"],
         "target_purchase_price_cents": 50_000_000, "variant_used": "CONSERVATIVE"}, COORD), 201)
    # 30000000 / 60000000 = 0.5, independent of which variant is selected
    assert q["equity_ratio"] == pytest.approx(0.5, abs=0.0001)
    assert q["capacity_cents"] == 24_000_000


def _carrying_scenario(months: int):
    """A funded program whose new home is grade A (high-cost bucket NEW_INSURANCE)."""
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "3 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "4 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE")["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=months)
    program, _loan = fund_program(bp["id"])
    cc_new_ins = record_carrying_cost(program["id"], "NEW_INSURANCE", 2_000_000)
    record_carrying_cost(program["id"], "NEW_TAX", 1_000_000)
    record_carrying_cost(program["id"], "DEPARTING_TAX", 500_000)
    return program, cc_new_ins


# The two carrying-burden divergence assertions that previously lived here were
# deleted under the PRD-First contract.  PRD section 3.9 names the A/B
# high-cost bucket as `NEW_CONSTRUCTION_INSURANCE`, but that string is not one of
# the eight `kind` values the same PRD paragraph enumerates for a CarryingCost,
# so no client can record a row of the named bucket; the design index and these
# tests silently substituted the enum member `NEW_INSURANCE` for it.  Reading the
# sentence literally (bucket unreachable, nothing surcharged) versus by
# substitution (NEW_INSURANCE surcharged) yields different outstanding amounts,
# so the expected 4375000 / 4000000 are not uniquely derivable.  Silence
# category: ENUM-MEMBERSHIP-ONLY / unstated-bucket-substitution.
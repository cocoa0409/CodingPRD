"""The day-one decision ladder and the pinned rounding order of a member
purchase.

Both are combinatorial formulas whose answer depends on the order the steps are
evaluated in, so the tests pin the order rather than only the final number.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_projection,
    round_half_up,
    scenario_for_projection_boundary,
    scenario_ready_to_purchase,
    make_subscriber_headers,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_day_one_ladder_approves_at_exactly_zero_projected_net_value(api):
    """PRD §3.9: "If the projected net value is at least zero **and** the
    title's `day_one_eligible` flag is true **and** the projection's
    `release_class` is `DAY_ONE`, the decision is `APPROVE_DAY_ONE`."
    PRD §3.9: "The capped engagement amount is the smaller of the theoretical
    gross amount and the deal's `monthly_engagement_cap_cents` multiplied by
    the term month count — that is, the monthly cap scaled to the length of the
    term."

    Design: Difficulty/combinatorial_formula/day_one_decision_ladder_at_the_zero_boundary
    """
    sc = scenario_for_projection_boundary(api)
    title = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert title["day_one_eligible"] is True
    assert title["unit_sales_30d"] == 25000

    projection = create_projection(api, sc, projected_unit_sales_units=500)

    # The six-month engagement cap scales the 300000 monthly ceiling to
    # 1800000, which the theoretical gross of 25000 * 1.25 * 1000 * 251
    # (7843750000) exceeds, so the cap binds.
    assert projection["projected_subscription_value_cents"] == \
        pytest.approx(1260000.00, abs=0.01), \
        "net-new 1080000.00 plus the tier uplift 180000.00"
    assert projection["projected_cannibalized_unit_sales_cents"] == \
        pytest.approx(1260000.00, abs=0.01), \
        "500 units at the 8400.00 regional list price times 0.30"
    assert projection["projected_net_value_cents"] == pytest.approx(0.00, abs=0.01)
    assert projection["decision"] == "APPROVE_DAY_ONE", \
        "the at-least-zero rung matches exactly at the boundary"
    assert projection["status"] == "DRAFT"
    assert projection["release_class"] == "DAY_ONE"


def test_day_one_ladder_drops_one_unit_past_the_boundary_to_hold(api):
    """PRD §3.9: "Otherwise, if the projected net value is at least negative
    50,000 cents, the decision is `HOLD_FOR_CATALOG`."
    PRD §3.9: "Note that the second rung is reached only when the first rung's
    conjunction fails — including the case where the net value clears zero but
    the title is not day-one eligible or the class is not `DAY_ONE`, in which
    case a favourable projection is held for the catalogue rather than
    approved."

    Design: Difficulty/combinatorial_formula/day_one_decision_ladder_at_the_zero_boundary
    """
    sc = scenario_for_projection_boundary(api)
    title = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert title["day_one_eligible"] is True, \
        "the title is eligible, so the second rung was not reached by eligibility"

    projection = create_projection(api, sc, projected_unit_sales_units=501)

    # One more unit of projected sales moves the downside to 501 * 8400 * 0.30.
    assert projection["projected_cannibalized_unit_sales_cents"] == \
        pytest.approx(1262520.00, abs=0.01)
    assert projection["projected_net_value_cents"] == pytest.approx(-2520.00, abs=0.01)
    assert projection["decision"] == "HOLD_FOR_CATALOG", \
        "-2520.00 is at least negative 50000 cents"
    assert projection["decision"] != "REJECT_DAY_ONE"

    # A projection far below the hold floor takes the third rung.
    deeper = create_projection(api, sc, projected_unit_sales_units=20000)
    assert deeper["projected_net_value_cents"] < -50000
    assert deeper["decision"] == "REJECT_DAY_ONE"


def test_back_catalog_purchase_rounds_the_discount_before_subtracting_it(api):
    """PRD §3.8: "The discount amount is the regional list price multiplied by
    the effective percentage, rounded half up to two decimals, and it is
    subtracted from the regional list price to form the subtotal."
    PRD §3.8: "The discount amount is rounded first and subtracted second, so
    the list price is never re-rounded after the subtraction and the
    subtraction itself introduces no rounding."

    Design: Difficulty/combinatorial_formula/member_purchase_discount_rounding_order
    """
    sc = scenario_ready_to_purchase(
        api, price_multiplier=1.199,
        entry_overrides={
            "removal_date": "2026-12-30T00:00:00Z",
            "release_class": "BACK_CATALOG",
            "popularity_index_cents": 4000,
            "popularity_index_cents_30d_avg": 4000,
        },
    )
    purchase = validate_success(
        api.create_purchase(
            {
                "subscriber_id": sc.subscriber["id"],
                "title_id": sc.title["id"],
                "entry_id": sc.entry["id"],
                "region_code": sc.region_code,
                "quantity": 1,
            },
            make_subscriber_headers(sc.subscriber["id"]),
        )
    , expected_status=201)

    # 7000 * 1.199 rounds to 8393.00; the tier's 0.075 plus the 0.05
    # BACK_CATALOG retention bonus is 0.125, under the 0.40 cap.
    assert purchase["list_price_cents_per_unit"] == pytest.approx(8393.00, abs=0.01)
    assert purchase["discount_pct_applied"] == pytest.approx(0.13, abs=0.001), \
        "not 0.125 rounded to two decimals, but the effective percentage"

    discount_amount = round_half_up(8393.00 * 0.125, 2)
    assert discount_amount == pytest.approx(1049.13, abs=0.01)
    assert purchase["total_charged_cents"] == pytest.approx(8393.00 - 1049.13, abs=0.01)
    assert purchase["total_charged_cents"] == pytest.approx(7343.87, abs=0.01)

    one_step = round_half_up(8393.00 * 0.875, 2)
    assert purchase["total_charged_cents"] != pytest.approx(one_step, abs=0.001), \
        "rounding the final total in one step would give 7343.88, one cent higher"


def test_purchase_figures_are_stable_when_the_row_is_read_back(api):
    """PRD §3.8: "Then wallet credit is applied: the amount offset is the
    smaller of the buyer's current `wallet_credit_cents` and the subtotal, so
    wallet credit can never exceed the discounted subtotal, and that amount is
    recorded as `wallet_applied_cents`."
    PRD §3.8: "A purchase response is stable thereafter: reading it back
    re-exposes the same figures unchanged."

    Design: Difficulty/combinatorial_formula/member_purchase_discount_rounding_order
    """
    sc = scenario_ready_to_purchase(
        api, wallet_credit_cents=1000, price_multiplier=1.199,
        entry_overrides={
            "removal_date": "2026-12-30T00:00:00Z",
            "release_class": "BACK_CATALOG",
            "popularity_index_cents": 4000,
            "popularity_index_cents_30d_avg": 4000,
        },
    )
    created = validate_success(
        api.create_purchase(
            {
                "subscriber_id": sc.subscriber["id"],
                "title_id": sc.title["id"],
                "entry_id": sc.entry["id"],
                "region_code": sc.region_code,
                "quantity": 2,
            },
            make_subscriber_headers(sc.subscriber["id"]),
        )
    , expected_status=201)

    assert created["wallet_applied_cents"] == 1000, \
        "the smaller of the wallet balance and the discounted subtotal"
    assert created["total_charged_cents"] == pytest.approx(7343.87 - 1000.00, abs=0.01), \
        "the subtotal less the wallet offset, with no rounding on the subtraction"
    assert created["unit_sales_credit_cents"] == \
        pytest.approx(created["total_charged_cents"] * 2, abs=0.01), \
        "the quantity scales the unit-sales credit only"

    reread = validate_success(api.get_purchase(created["id"], ADMIN))
    assert reread["total_charged_cents"] == created["total_charged_cents"]
    assert reread["discount_pct_applied"] == created["discount_pct_applied"]
    assert reread["wallet_applied_cents"] == created["wallet_applied_cents"]
    assert reread["unit_sales_credit_cents"] == created["unit_sales_credit_cents"]
    assert reread["status"] == "COMPLETED"

    listed_rows, _meta = validate_paginated(
        api.list_purchases(ADMIN, params={"subscriber_id": sc.subscriber["id"]})
    )
    assert len(listed_rows) == 1
    assert listed_rows[0]["id"] == created["id"]
    assert listed_rows[0]["total_charged_cents"] == created["total_charged_cents"], \
        "the discount is not recomputed on read"
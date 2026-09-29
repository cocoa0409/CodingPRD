"""Per-opening rounding: three identical openings cost more than their pooled area."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import assert_inches_equal, assert_page_meta
from test_helpers.fixtures import (
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    present_quote,
    record_opening,
)
from test_helpers.test_users import designer_headers

# 23.500 x 36.875 inches is 866.5625 square inches, or 6.017795 square feet raw.
READINGS = {
    "width_top_in": 24.000,
    "width_middle_in": 24.000,
    "width_bottom_in": 24.000,
    "height_left_in": 37.125,
    "height_center_in": 37.125,
    "height_right_in": 37.125,
    "depth_in": 3.000,
}
LABELS = ("Bay left", "Bay centre", "Bay right")


def _three_identical_openings(api):
    """One appointment carrying three geometrically identical CL-LINEN openings.

    Every opening is an `INSIDE` mount over the same square readings and is
    configured `CL-LINEN` / `CORDED` / `NONE`, so the trio differs from a single
    pooled window in nothing but the number of rows the arithmetic runs over.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    openings = []
    for label in LABELS:
        opening = record_opening(api, designer, consultation, label=label,
                                 room_type="LIVING_ROOM", mount_type="INSIDE",
                                 **READINGS)
        openings.append(configure_opening(api, designer, opening,
                                          fabric_code="CL-LINEN",
                                          lift_system="CORDED",
                                          motorization_option="NONE"))
    return territory, designer, consultation, openings


def test_each_opening_ceils_its_own_area_to_the_quarter_foot(api):
    """6.017795 raw square feet becomes 6.25 billable on each of the three rows.

    "Their product divided by 144 gives the raw area in square feet, and
    `billable_sqft` is that raw area rounded **up** to the next whole quarter of a
    square foot — the trade's billing unit."

    "Both are per-opening. This is the asymmetry §2.5 warns about: `billable_sqft` is
    rounded up to the quarter square foot for each opening individually and the fabric
    charge is rounded to the cent for each opening individually, and a quote's subtotal
    then sums those already-rounded integers."

    Design: Difficulty/combinatorial_formula/billable_sqft_ceils_per_opening_so_trio_costs_more_than_pooled_area
    """
    _territory, _designer, _consultation, openings = _three_identical_openings(api)

    for priced in openings:
        assert_inches_equal(priced["ordered_width_in"], 23.500,
                            "ordered_width_in")
        assert_inches_equal(priced["ordered_height_in"], 36.875,
                            "ordered_height_in")
        assert priced["billable_sqft"] == 6.25
        assert priced["list_price_cents"] == 5875
        assert priced["measure_status"] == "CONFIGURED"


def test_the_subtotal_sums_rounded_integers_and_lands_on_17625(api):
    """17625 cents, never the 17155 that pooling the three areas would give.

    "Summing raw areas across a consultation's openings and rounding once, or summing
    unrounded fabric charges and rounding once at the quote level, is forbidden and
    produces a different subtotal. Three identical openings whose raw area is 6.017795
    square feet each price at 5875 cents apiece for a subtotal of 17625 cents, whereas
    the forbidden order gives an aggregate 18.25 square feet and a subtotal of 17155
    cents."

    Design: Difficulty/combinatorial_formula/billable_sqft_ceils_per_opening_so_trio_costs_more_than_pooled_area
    """
    _territory, designer, consultation, openings = _three_identical_openings(api)

    quote = build_quote(api, designer, consultation)
    priced = present_quote(api, designer, quote)

    assert priced["opening_count"] == 3
    assert priced["motorized_opening_count"] == 0
    assert priced["subtotal_cents"] == 17625
    assert priced["subtotal_cents"] != 17155
    assert priced["subtotal_cents"] == sum(o["list_price_cents"] for o in openings)


def test_the_pooled_area_error_would_also_move_the_customer_facing_total(api):
    """The 470-cent per-opening rounding gain survives the whole waterfall.

    "Step three sets `pre_discount_total_cents` to `subtotal_cents` plus
    `install_fee_cents`."

    "Step six sets `total_cents`, the customer-facing price, to
    `pre_discount_total_cents` minus `discount_cents`, and sets `net_sales_cents`, the
    royalty base, to `subtotal_cents` minus `discount_cents` — equivalently
    `total_cents` minus `install_fee_cents`."

    Design: Difficulty/combinatorial_formula/billable_sqft_ceils_per_opening_so_trio_costs_more_than_pooled_area
    """
    _territory, designer, consultation, _openings = _three_identical_openings(api)

    quote = build_quote(api, designer, consultation)
    priced = present_quote(api, designer, quote)

    assert priced["install_fee_cents"] == 15000
    assert priced["pre_discount_total_cents"] == 32625
    assert priced["discount_pct"] == 0
    assert priced["discount_cents"] == 0
    assert priced["total_cents"] == 32625
    assert priced["net_sales_cents"] == 17625
    assert priced["status"] == "PRESENTED"

    attached, meta = validate_paginated(api.list_openings(
        designer_headers(designer["id"]), quote_id=quote["id"]))
    assert_page_meta(meta, total_count=3, has_more=False)
    assert sum(row["list_price_cents"] for row in attached) == 17625
    assert all(row["measure_status"] == "QUOTED" for row in attached)

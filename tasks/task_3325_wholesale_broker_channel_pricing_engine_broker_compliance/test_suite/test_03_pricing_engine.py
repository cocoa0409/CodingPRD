"""Rate sheets, the pricing engine and the price-point grid."""
from test_helpers import (
    ANY,
    ApiErrorId,
    expected_price_points,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    broker_version,
    create_and_approve_broker,
    price_quote,
    publish_rate_sheet,
    setup_full_scenario,
)
from test_helpers.test_users import TEST_USERS, make_broker_headers, make_channel_manager_headers

STANDARD_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]

CREDIT_LTV_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "credit", "bucket": "740-759", "adjust_pct": -0.050},
    {"dim": "credit", "bucket": "720-739", "adjust_pct": 0.000},
    {"dim": "credit", "bucket": "700-719", "adjust_pct": 0.125},
    {"dim": "credit", "bucket": "680-699", "adjust_pct": 0.250},
    {"dim": "ltv", "bucket": "60-70", "adjust_pct": 0.050},
    {"dim": "ltv", "bucket": "70-80", "adjust_pct": 0.125},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]

TWO_LTV_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "60-70", "adjust_pct": 0.050},
    {"dim": "ltv", "bucket": "70-80", "adjust_pct": 0.125},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]

VA_TABLE = [
    {"dim": "credit", "bucket": "720-739", "adjust_pct": 0.000},
    {"dim": "ltv", "bucket": "80-90", "adjust_pct": 0.250},
    {"dim": "occupancy", "bucket": "SECOND_HOME", "adjust_pct": 0.250},
    {"dim": "product", "bucket": "VA", "adjust_pct": -0.125},
]


def test_price_points_key_the_discount_on_the_provisional_value(api):
    """PRD §3.5: "the discount is keyed on the tier of the provisional pre-discount value, so
    the final `price_points` never re-enters the tier step."
    PRD §3.5: "The fifth step assigns a discount tier from the provisional value alone:
    `PLATINUM` when the provisional points are `-0.50` or lower"

    Design: Difficulty/combinatorial_formula/pricing_quote_price_points_provisional_tier_with_single_rounding
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    quote = price_quote(broker["id"], sheet, representative_fico=780, ltv_ratio=0.5500,
                        lock_period_days=30)

    assert quote["overall_adjustment_pct"] == -0.125
    # base grid at the 760-plus row / up-to-60 band is -1.00; provisional = -1.125 (PLATINUM).
    assert quote["price_points"] == -1.375
    assert quote["price_points"] == expected_price_points(780, 0.5500, -0.125)
    assert quote["price_points"] != -1.125, "the pre-discount provisional value is not the result"


def test_price_points_trace_and_note_rate_for_the_standard_scenario(api):
    """PRD §3.5: "That trace is an array of exactly four rows, each an object carrying `dim`,
    `bucket` and `adjust_pct`, emitted in the order credit, loan-to-value, occupancy, product."
    PRD §3.5: "A base of 6.125 with an adjustment of 0.125 and a lock surcharge of 0.125
    therefore produces 6.375 exactly."

    Design: Difficulty/combinatorial_formula/pricing_quote_price_points_provisional_tier_with_single_rounding
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    quote = price_quote(broker["id"], sheet, representative_fico=780, ltv_ratio=0.5500,
                        lock_period_days=30)

    trace = quote["adjustment_trace"]
    assert [row["dim"] for row in trace] == ["credit", "ltv", "occupancy", "product"]
    assert trace[0]["bucket"] == "760-plus" and trace[0]["adjust_pct"] == -0.125
    assert trace[1]["bucket"] == "up-to-60" and trace[1]["adjust_pct"] == 0.000
    assert trace[2]["bucket"] == "PRIMARY_RESIDENCE" and trace[2]["adjust_pct"] == 0.000
    assert trace[3]["bucket"] == "CONVENTIONAL" and trace[3]["adjust_pct"] == 0.000
    assert quote["note_rate_pct"] == 6.000


def test_lock_boundary_decides_the_third_decimal_of_the_note_rate(api):
    """PRD §3.5: "A `lock_period_days` below 30 takes `0.125`; from 30 up to but excluding 60
    takes `0.000`; 60 or more takes `-0.125`."
    PRD §3.5: "the sheet's `base_rate_pct`, the quote's `overall_adjustment_pct` and the quote's
    `lock_adjustment_pct` are summed at full precision, and that single sum is rounded half up
    to three decimal places exactly once."

    Design: Difficulty/combinatorial_formula/note_rate_single_rounding_across_lock_boundaries
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=TWO_LTV_TABLE)
    b = broker["id"]

    q29 = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.6500, lock_period_days=29)
    sheet = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    q30 = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.7500, lock_period_days=30)
    sheet = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    q60 = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.7500, lock_period_days=60)

    assert q29["adjustment_trace"][1]["bucket"] == "60-70"
    # credit 760-plus (-0.125) + ltv 60-70 (0.050) = -0.075
    assert q29["overall_adjustment_pct"] == -0.075
    assert q29["lock_adjustment_pct"] == 0.125
    assert q29["note_rate_pct"] == 6.175

    # ltv 0.7500 falls in 70-80 (0.125); credit -0.125 cancels it exactly.
    assert q30["lock_adjustment_pct"] == 0.000
    assert q30["note_rate_pct"] == 6.125

    assert q60["lock_adjustment_pct"] == -0.125
    assert q60["note_rate_pct"] == 6.000

    assert q29["note_rate_pct"] != q30["note_rate_pct"]


def test_lock_boundary_also_decides_the_price_point_tier(api):
    """PRD §3.5: "The `price_points` field is derived from an immutable base grid in seven
    pinned steps."
    PRD §3.5: "`GOLD` when they are `0.00` or lower, `SILVER` when they are `0.50` or lower, and
    `BRONZE` otherwise. The boundaries are inclusive"

    Design: Difficulty/combinatorial_formula/note_rate_single_rounding_across_lock_boundaries
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=TWO_LTV_TABLE)
    b = broker["id"]

    q29 = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.6500, lock_period_days=29)
    # 760-plus row / 60-70 column is -0.75; provisional -0.75 + (-0.075) = -0.825
    # -> PLATINUM (-0.25) -> -1.075.
    assert q29["price_points"] == -1.075


def test_truth_table_of_the_four_pricing_dimensions(api):
    """PRD §3.5: "The four selected values, each a signed decimal in percent, are summed."
    PRD §3.5: "The occupancy row matches `occupancy_type` exactly, with `PRIMARY_RESIDENCE` at
    `0.000`, `SECOND_HOME` at `0.250` and `INVESTMENT` at `0.500`."

    Design: Corner/calculations/va_second_home_quote_prices_from_known_inputs
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], product_code="VA", base_rate_pct=5.875,
                               adjustment_table=VA_TABLE)
    quote = price_quote(broker["id"], sheet, representative_fico=720, ltv_ratio=0.8500,
                        occupancy_type="SECOND_HOME", lock_period_days=45)

    assert quote["overall_adjustment_pct"] == 0.375
    assert quote["lock_adjustment_pct"] == 0.000
    assert quote["note_rate_pct"] == 6.250
    assert quote["price_points"] == 0.875
    assert quote["adjustment_trace"][2]["bucket"] == "SECOND_HOME"
    assert quote["adjustment_trace"][3]["bucket"] == "VA"
    assert quote["adjustment_trace"][3]["adjust_pct"] == -0.125


def test_credit_and_ltv_band_edges_are_inclusive_on_the_upper_end(api):
    """PRD §3.5: "a score of 760 or more takes the top band's `-0.125`, a score of 740 up to but
    excluding 760 takes `-0.050`, 720 up to but excluding 740 takes `0.000`"
    PRD §3.5: "an `ltv_ratio` of 0.60 or less takes `0.000`, above 0.60 up to and including 0.70
    takes `0.050`"

    Design: Difficulty/boundary_precision_check/credit_bucket_720_inclusive_and_ltv_700_boundary
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=CREDIT_LTV_TABLE)
    b = broker["id"]

    at_edge = price_quote(b, sheet, representative_fico=720, ltv_ratio=0.7000, lock_period_days=30)
    sheet = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    just_over = price_quote(b, sheet, representative_fico=700, ltv_ratio=0.7001, lock_period_days=30)

    assert at_edge["adjustment_trace"][0]["bucket"] == "720-739"
    assert at_edge["adjustment_trace"][0]["adjust_pct"] == 0.000
    assert at_edge["adjustment_trace"][1]["bucket"] == "60-70"
    assert at_edge["adjustment_trace"][1]["adjust_pct"] == 0.050
    assert at_edge["overall_adjustment_pct"] == 0.050

    assert just_over["adjustment_trace"][0]["bucket"] == "700-719"
    assert just_over["adjustment_trace"][0]["adjust_pct"] == 0.125
    assert just_over["adjustment_trace"][1]["bucket"] == "70-80"
    assert just_over["adjustment_trace"][1]["adjust_pct"] == 0.125
    assert just_over["overall_adjustment_pct"] == 0.250

    assert at_edge["overall_adjustment_pct"] != just_over["overall_adjustment_pct"]


def test_price_points_follow_the_grid_at_three_fico_buckets(api):
    """PRD §3.5: "The first step chooses the credit bucket by rounding `representative_fico`
    half up to the nearest ten."
    PRD §3.5: "the grid is a six-by-six table whose rows are the rounded credit buckets
    760-and-above, 740, 720, 700, 680, 660 and below 660"

    Design: Difficulty/boundary_precision_check/credit_bucket_720_inclusive_and_ltv_700_boundary
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=CREDIT_LTV_TABLE)
    b = broker["id"]

    cases = [
        (720, 0.7000, 0.050, "720", "60-70"),
        # 719 sits in the 700-719 credit band (0.125), not the 720 band; ltv
        # 0.7001 is above the closed 60-70 edge and falls in 70-80 (0.125).
        (719, 0.7001, 0.250, "720", "70-80"),
        (760, 0.6500, -0.075, "760-plus", "60-70"),
    ]
    for fico, ltv, adjustment, row_key, ltv_band in cases:
        quote = price_quote(b, sheet, representative_fico=fico, ltv_ratio=ltv, lock_period_days=30)
        sheet = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
        assert quote["overall_adjustment_pct"] == adjustment
        assert quote["price_points"] == expected_price_points(fico, ltv, adjustment), (
            f"price_points mismatch for fico={fico} ltv={ltv}"
        )
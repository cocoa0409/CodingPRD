"""The waterfall's pinned order, and the cardinality floor on quote assembly."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_QUOTE_HAS_NO_OPENINGS
from test_helpers.assertions import assert_page_meta
from test_helpers.fixtures import (
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    present_quote,
    read_consultation,
    read_opening,
    record_opening,
)
from test_helpers.test_users import designer_headers

SMALL = {
    "width_top_in": 24.000,
    "width_middle_in": 24.000,
    "width_bottom_in": 24.000,
    "height_left_in": 48.000,
    "height_center_in": 48.000,
    "height_right_in": 48.000,
    "depth_in": 3.000,
}
# 59.500 x 83.750 inches is 4982.125 square inches, 34.598 square feet raw.
LARGE = {
    "width_top_in": 60.000,
    "width_middle_in": 60.000,
    "width_bottom_in": 60.000,
    "height_left_in": 84.000,
    "height_center_in": 84.000,
    "height_right_in": 84.000,
    "depth_in": 3.000,
}


def _bay_that_straddles_the_first_tier(api):
    """Two 4960-cent openings and one hardwired 73363-cent opening on one quote.

    The goods subtotal of 83283 cents sits below the first discount threshold while
    the pre-discount total of 102783 cents sits above it, so the two candidate tier
    keys disagree. The motor package is the only reason the install fee carries its
    4500-cent adder.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    small_one = record_opening(api, designer, consultation, label="Hall north",
                              room_type="LIVING_ROOM", mount_type="INSIDE",
                              **SMALL)
    small_two = record_opening(api, designer, consultation, label="Hall south",
                              room_type="LIVING_ROOM", mount_type="INSIDE",
                              **SMALL)
    picture = record_opening(api, designer, consultation, label="Great room",
                            room_type="LIVING_ROOM", mount_type="INSIDE",
                            **LARGE)
    small_one = configure_opening(api, designer, small_one,
                                  fabric_code="LT-SHEER", lift_system="CORDED",
                                  motorization_option="NONE")
    small_two = configure_opening(api, designer, small_two,
                                  fabric_code="LT-SHEER", lift_system="CORDED",
                                  motorization_option="NONE")
    picture = configure_opening(api, designer, picture, fabric_code="WD-FAUX",
                                lift_system="MOTORIZED",
                                motorization_option="HARDWIRED")
    quote = build_quote(api, designer, consultation)
    return territory, designer, [small_one, small_two, picture], quote


def test_the_tier_is_keyed_on_the_pre_discount_total_not_the_subtotal(api):
    """102783 cents selects the 0.05 tier that the 83283-cent subtotal would not.

    "Step four selects `discount_pct` from `pre_discount_total_cents` alone: 0.12 when
    that figure is at least 500000 cents, otherwise 0.08 when it is at least 250000
    cents, otherwise 0.05 when it is at least 100000 cents, otherwise zero — every
    comparison inclusive of its threshold."

    "Selecting the tier from `subtotal_cents`, or applying `discount_pct` to
    `pre_discount_total_cents`, are both forbidden and both produce different money"

    Design: Difficulty/combinatorial_formula/discount_tier_read_from_pre_discount_total_but_applied_to_subtotal_only
    """
    _territory, designer, openings, quote = _bay_that_straddles_the_first_tier(api)

    assert [o["list_price_cents"] for o in openings] == [4960, 4960, 73363]
    assert openings[2]["billable_sqft"] == 34.75

    priced = present_quote(api, designer, quote)
    assert priced["opening_count"] == 3
    assert priced["motorized_opening_count"] == 1
    assert priced["subtotal_cents"] == 83283
    assert priced["install_fee_cents"] == 19500
    assert priced["pre_discount_total_cents"] == 102783
    assert priced["subtotal_cents"] < 100000
    assert priced["discount_pct"] == 0.05


def test_the_discount_base_is_the_goods_subtotal_only(api):
    """4164 cents of discount, not the 5139 the pre-discount total would yield.

    "Step five computes `discount_cents` as `subtotal_cents` multiplied by
    `discount_pct`, rounded half up to a whole cent; the base is the goods subtotal
    **only**, because install labour is discount-exempt."

    "Step six sets `total_cents`, the customer-facing price, to
    `pre_discount_total_cents` minus `discount_cents`, and sets `net_sales_cents`, the
    royalty base, to `subtotal_cents` minus `discount_cents` — equivalently
    `total_cents` minus `install_fee_cents`."

    Design: Difficulty/combinatorial_formula/discount_tier_read_from_pre_discount_total_but_applied_to_subtotal_only
    """
    _territory, designer, _openings, quote = _bay_that_straddles_the_first_tier(api)

    priced = present_quote(api, designer, quote)

    assert priced["discount_cents"] == 4164
    assert priced["discount_cents"] != 5139
    assert priced["total_cents"] == 98619
    assert priced["net_sales_cents"] == 79119
    assert (priced["total_cents"]
            - priced["install_fee_cents"]) == priced["net_sales_cents"]
    assert priced["status"] == "PRESENTED"


def _two_measured_but_unconfigured_openings(api):
    """An appointment holding two openings that were measured and never configured."""
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WALK_IN",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    left = record_opening(api, designer, consultation, label="Unpriced left",
                          room_type="KITCHEN", mount_type="INSIDE", **SMALL)
    right = record_opening(api, designer, consultation, label="Unpriced right",
                           room_type="KITCHEN", mount_type="INSIDE", **SMALL)
    return territory, designer, consultation, left, right


def test_zero_configured_openings_refuses_the_quote_and_writes_no_shell(api):
    """Two `MEASURED` openings and no `CONFIGURED` one is below the assembly floor.

    "the service sweeps in **every** opening on that consultation whose
    `measure_status` is `CONFIGURED`. If there is no such opening — every opening still
    merely `MEASURED`, say — the request fails with `ERR_QUOTE_HAS_NO_OPENINGS` (HTTP
    422)."

    Design: Difficulty/boundary_precision_check/quote_creation_needs_exactly_one_configured_opening_not_zero
    """
    _territory, designer, consultation, _left, _right = (
        _two_measured_but_unconfigured_openings(api))
    dsg = designer_headers(designer["id"])

    before = read_consultation(api, designer, consultation["id"])
    assert before["measured_opening_count"] == 2
    assert before["configured_opening_count"] == 0

    validate_error(
        api.create_quote(f.quote_payload(consultation["id"], before["version"]),
                         dsg),
        ERR_QUOTE_HAS_NO_OPENINGS, 422)

    _rows, meta = validate_paginated(
        api.list_quotes(dsg, consultation_id=consultation["id"]))
    assert_page_meta(meta, total_count=0, has_more=False)

    after = read_consultation(api, designer, consultation["id"])
    assert after["version"] == before["version"]


def test_exactly_one_configured_opening_admits_the_quote(api):
    """One configuration lifts the count to the floor, and the other row stays out.

    "Two counters describe the assembled set: `opening_count` is the number of
    openings carrying this quote's id, and `motorized_opening_count` is the number of
    those whose `motorization_option` is anything other than `NONE`."

    "The input set is every opening carrying this quote's id, whatever its install
    outcome; `opening_count` and `motorized_opening_count` are counts of that same set,
    and openings still `CONFIGURED` on the appointment but not attached to this quote
    are excluded."

    Design: Difficulty/boundary_precision_check/quote_creation_needs_exactly_one_configured_opening_not_zero
    """
    _territory, designer, consultation, left, right = (
        _two_measured_but_unconfigured_openings(api))
    dsg = designer_headers(designer["id"])

    configure_opening(api, designer, left, fabric_code="LT-SHEER",
                      lift_system="CORDED", motorization_option="NONE")

    staged = read_consultation(api, designer, consultation["id"])
    assert staged["configured_opening_count"] == 1
    assert staged["measured_opening_count"] == 2

    quote = validate_success(
        api.create_quote(f.quote_payload(consultation["id"], staged["version"]),
                         dsg), 201)
    assert quote["opening_count"] == 1
    assert quote["motorized_opening_count"] == 0
    assert quote["status"] == "DRAFT"

    attached = read_opening(api, designer, left["id"])
    assert attached["measure_status"] == "QUOTED"
    assert attached["quote_id"] == quote["id"]

    excluded = read_opening(api, designer, right["id"])
    assert excluded["measure_status"] == "MEASURED"
    assert excluded["quote_id"] is None
    assert excluded["list_price_cents"] == 0

    priced = present_quote(api, designer, quote)
    assert priced["subtotal_cents"] == 4960
    assert priced["install_fee_cents"] == 10000
    assert priced["pre_discount_total_cents"] == 14960
    assert priced["discount_cents"] == 0
    assert priced["total_cents"] == 14960

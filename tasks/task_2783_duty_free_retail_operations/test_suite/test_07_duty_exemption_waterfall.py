"""The per-category allowance waterfall, its two variants and its rounding order."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALLOWANCE_RULE_MISSING,
    ERR_ITINERARY_NOT_SCANNED,
    ERR_VOID_AFTER_PERIOD_CLOSE,
)
from test_helpers.assertions import (
    assert_instant,
    assert_line_split,
    assert_nulls,
    assert_sale_amounts,
    assert_sale_dimensions,
    ok,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
)


def _two_cigar_lines(api):
    """A basket holding two separate one-unit cigar lines at 333 cents and 1250 bps."""
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)
    brand = fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")
    cigar = fx.listed_product(
        api,
        brand["id"],
        sku="EMB-CIGAR-01",
        category="TOBACCO",
        unit_price_cents=333,
        duty_rate_bps=800,
        vat_rate_bps=450,
    )
    fx.stocked_ledger(api, terminal["id"], cigar["id"], 10)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="TOBACCO",
        allowance_units=0,
        advisory_text="Australia: no duty-free tobacco allowance beyond one open packet.",
    )
    agreement = fx.active_agreement(api, terminal["id"])
    itinerary = fx.scanned_itinerary(
        api, terminal["id"], departure_utc="2026-08-25T10:00:00Z", has_connection=False
    )
    sale = fx.open_basket(api, itinerary["id"])
    first = fx.append_line(api, sale["id"], cigar["id"], 1)
    second = fx.append_line(api, sale["id"], cigar["id"], 1)
    return agreement, sale, first, second


def test_each_line_rounds_its_own_levy_before_the_basket_sums_them(api):
    """Two lines of 41.625 cents duty each round to 42, so the basket owes 84 and not 83.

    PRD 3.5: "Set the line's `line_duty_cents` to the excess units multiplied by the snapshotted `unit_price_cents`, multiplied by the sum of the product's `duty_rate_bps` and `vat_rate_bps`, divided by 10000 and rounded half up to whole cents. This rounding happens here, on the line, and is not deferred."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_beats_sum_then_round
    """
    _agreement, sale, first, second = _two_cigar_lines(api)

    cleared = fx.clear_basket(api, sale["id"])

    assert_line_split(
        ok(api.get_sale_line(first["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=1,
        exempt_cents=0,
        duty_cents=42,
    )
    assert_line_split(
        ok(api.get_sale_line(second["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=1,
        exempt_cents=0,
        duty_cents=42,
    )
    assert_sale_amounts(cleared, gross=666, exempt=0, duty=84)
    assert cleared["duty_liability_cents"] != 83
    assert_sale_dimensions(cleared, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")


def test_the_already_rounded_line_figures_are_what_reach_the_concession_ledger(api):
    """The handover re-runs the same rounding and rolls the gross into the agreement.

    PRD 2.6: "**Duty and tax on a basket are rounded per line, then summed.** The combined levy on each sale line is rounded half up to whole cents on that line, and the sale's totals are the sums of the already-rounded line figures."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_beats_sum_then_round
    """
    agreement, sale, _first, _second = _two_cigar_lines(api)

    fx.clear_basket(api, sale["id"])
    handed_over = fx.hand_over(api, sale["id"])

    assert_sale_amounts(handed_over, gross=666, exempt=0, duty=84)
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="DUTY_LIABLE")

    settled = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert settled["gross_sales_cents"] == 666
    assert settled["percentage_rent_cents"] == 80


def _connecting_traveller_basket(api):
    """A Hong Kong basket of three bottles routed AU then onward to NZ."""
    terminal = fx.register_terminal(
        api,
        iata_code="HKG",
        name="Hong Kong T1 Duty Free",
        country_code="HK",
        sealed_bag_regime="ICAO_STEB",
        liquid_limit_ml=3000,
    )
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    whisky = fx.listed_product(
        api,
        brand["id"],
        sku="AUR-WHISKY-700",
        category="LIQUOR",
        unit_price_cents=8000,
        is_liquid=True,
        liquid_ml=700,
    )
    fx.stocked_ledger(api, terminal["id"], whisky["id"], 10)
    fx.publish_allowance_rule(api, destination_country="AU", category="LIQUOR", allowance_units=1)
    fx.publish_allowance_rule(
        api,
        destination_country="NZ",
        category="LIQUOR",
        allowance_units=3,
        advisory_text="New Zealand: 3 bottles of spirits per traveller.",
    )
    fx.active_agreement(api, terminal["id"])
    itinerary = fx.scanned_itinerary(
        api,
        terminal["id"],
        departure_utc="2026-08-05T10:00:00Z",
        destination_country="AU",
        final_destination_country="NZ",
        has_connection=True,
        connection_country="AU",
        connection_departure_utc="2026-08-06T02:00:00Z",
    )
    sale = fx.open_basket(api, itinerary["id"])
    line = fx.append_line(api, sale["id"], whisky["id"], 3)
    return sale, line


def test_the_estimate_run_prices_the_basket_against_the_first_leg(api):
    """Clearance keys on the AU allowance of one unit and ignores the onward leg entirely.

    PRD 3.5: "Under the `SUSPENDED_ESTIMATE` variant, run when eligibility is cleared, the effective destination is the itinerary's `destination_country`, the arrival country of the first leg, and any onward connection is ignored entirely."

    Design: Difficulty/dual_variant_calc/duty_exemption_first_leg_estimate_versus_final_destination_confirmation
    """
    sale, line = _connecting_traveller_basket(api)

    cleared = fx.clear_basket(api, sale["id"])
    assert cleared["eligibility_variant"] == "SUSPENDED_ESTIMATE"
    assert cleared["effective_destination_country"] == "AU"
    assert_sale_amounts(cleared, gross=24000, exempt=8000, duty=3840)
    assert_sale_dimensions(cleared, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")
    assert cleared["sealed_bag_required"] is True

    assert_line_split(
        ok(api.get_sale_line(line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=2,
        exempt_cents=8000,
        duty_cents=3840,
    )


def test_the_confirmation_run_reprices_the_same_basket_against_the_final_destination(api):
    """Nothing in the request changed, yet the New Zealand allowance of three units makes the
    identical basket fully exempt.

    PRD 3.5: "Under the `EXEMPT_CONFIRMED_FINAL` variant, run at handover, the effective destination is the itinerary's `final_destination_country` when `has_connection` is true and its `destination_country` otherwise."

    Design: Difficulty/dual_variant_calc/duty_exemption_first_leg_estimate_versus_final_destination_confirmation
    """
    sale, line = _connecting_traveller_basket(api)

    fx.clear_basket(api, sale["id"])
    bag = fx.issue_bag(api, sale["id"], "STEB-0002")
    fx.verify_bag(api, bag["id"], "INTACT")

    handed_over = fx.hand_over(api, sale["id"])
    assert handed_over["eligibility_variant"] == "EXEMPT_CONFIRMED_FINAL"
    assert handed_over["effective_destination_country"] == "NZ"
    assert_sale_amounts(handed_over, gross=24000, exempt=24000, duty=0)
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")

    assert_line_split(
        ok(api.get_sale_line(line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=0,
        exempt_cents=24000,
        duty_cents=0,
    )


def test_a_basket_that_exactly_consumes_the_allowance_carries_no_duty(api):
    """Two bottles against an allowance of two units leave nothing in excess.

    PRD 3.5: "Add this line's own `qty` to that already-consumed figure. If the result does not exceed the rule's `allowance_units`, the line's `allowance_excess_qty` is 0."

    Design: Difficulty/boundary_precision_check/allowance_units_exactly_consumed_versus_one_unit_over
    """
    estate = fx.liquor_estate(api, allowance_units=2)
    basket = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )

    cleared = fx.clear_basket(api, basket.sale["id"])
    assert_line_split(
        ok(api.get_sale_line(basket.line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=0,
        exempt_cents=16000,
        duty_cents=0,
    )
    assert_sale_amounts(cleared, gross=16000, exempt=16000, duty=0)

    handed_over = fx.hand_over(api, basket.sale["id"])
    assert_sale_amounts(handed_over, gross=16000, exempt=16000, duty=0)
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")


def test_one_unit_beyond_the_allowance_makes_only_that_unit_dutiable(api):
    """The third bottle is the whole excess, so exactly one unit is taxed while the first two
    stay exempt, and the two settled baskets leave the rent on its guarantee.

    PRD 3.5: "Otherwise the excess is the amount by which the result exceeds `allowance_units`, capped at this line's own `qty` — a line can never contribute more excess units than it contains."

    Design: Difficulty/boundary_precision_check/allowance_units_exactly_consumed_versus_one_unit_over
    """
    estate = fx.liquor_estate(api, allowance_units=2)
    exact = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )
    over = fx.till_ready_basket(
        api, estate, qty=3, itinerary_overrides={"departure_utc": "2026-08-26T10:00:00Z"}
    )

    cleared = fx.clear_basket(api, over.sale["id"])
    assert_line_split(
        ok(api.get_sale_line(over.line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=1,
        exempt_cents=16000,
        duty_cents=1920,
    )
    assert_sale_amounts(cleared, gross=24000, exempt=16000, duty=1920)

    handed_over = fx.hand_over(api, over.sale["id"])
    assert_sale_amounts(handed_over, gross=24000, exempt=16000, duty=1920)
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="DUTY_LIABLE")

    fx.clear_basket(api, exact.sale["id"])
    fx.hand_over(api, exact.sale["id"])

    settled = ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert settled["gross_sales_cents"] == 40000
    assert settled["percentage_rent_cents"] == 4800
    assert settled["rent_basis"] == "MINIMUM_GUARANTEE"

    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 5


def test_clearance_is_refused_until_the_boarding_pass_is_verified(api):
    """The basket is faultless; the referenced itinerary's UNSCANNED standing is what blocks it.

    PRD 3.5: "It is admissible only on a basket that has not been voided (`ERR_SALE_ALREADY_TERMINAL`) and is still in `CART` (`ERR_SALE_NOT_IN_CART`), that has at least one line (`ERR_EMPTY_BASKET`), whose itinerary has been verified — `scan_status` of `SCANNED` or `AMENDED`, else `ERR_ITINERARY_NOT_SCANNED`"

    Design: Difficulty/cross_entity_state_dependency/sale_eligibility_clearance_gated_on_itinerary_scan_status
    """
    estate = fx.liquor_estate(api, allowance_units=2)
    itinerary = fx.record_itinerary(
        api, estate.terminal["id"], departure_utc="2026-08-25T10:00:00Z"
    )
    assert itinerary["scan_status"] == "UNSCANNED"
    sale = fx.open_basket(api, itinerary["id"])
    line = fx.append_line(api, sale["id"], estate.product["id"], 2)

    validate_error(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_ITINERARY_NOT_SCANNED)

    still_in_cart = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(still_in_cart, fulfillment_status="CART", duty_status="SUSPENDED")
    assert_nulls(still_in_cart, "eligibility_variant", "effective_destination_country", "cleared_at")
    assert still_in_cart["exempt_amount_cents"] == 0

    scanned = fx.scan_itinerary(api, itinerary)
    assert scanned["scan_status"] == "SCANNED"
    assert_instant(scanned["scanned_at"], CLOCK_START, "scanned_at")

    cleared = ok(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(cleared, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")
    assert cleared["eligibility_variant"] == "SUSPENDED_ESTIMATE"
    assert cleared["effective_destination_country"] == "AU"
    assert_line_split(
        ok(api.get_sale_line(line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=0,
        exempt_cents=16000,
        duty_cents=0,
    )


def test_an_amended_itinerary_still_counts_as_verified_for_clearance(api):
    """The amendment drops the basket back to CART and clears `scanned_at`, yet the AMENDED
    standing is itself enough to re-clear the basket without a fresh scan.

    PRD 3.9: "Re-scanning closes the cycle `SCANNED → AMENDED → SCANNED`, and `amend_count` is never reset, so the number of amendments over a journey is permanently visible."

    Design: Difficulty/cross_entity_state_dependency/sale_eligibility_clearance_gated_on_itinerary_scan_status
    """
    estate = fx.liquor_estate(api, allowance_units=2)
    fx.publish_allowance_rule(
        api,
        destination_country="NZ",
        category="LIQUOR",
        allowance_units=1,
        advisory_text="New Zealand: 3 bottles of spirits per traveller.",
    )
    basket = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )
    fx.clear_basket(api, basket.sale["id"])

    amended = ok(
        api.amend_itinerary(
            basket.itinerary["id"],
            f.amend_payload(destination_country="NZ", final_destination_country="NZ"),
            SALES_ASSOCIATE_HEADERS,
        )
    )
    assert amended["scan_status"] == "AMENDED"
    assert_nulls(amended, "scanned_at")

    reverted = ok(api.get_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(reverted, fulfillment_status="CART", duty_status="SUSPENDED")

    recleared = ok(api.clear_eligibility(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert recleared["effective_destination_country"] == "NZ"
    assert_sale_amounts(recleared, gross=16000, exempt=8000, duty=1920)


def _mixed_category_basket(api):
    """A basket of liquor, tobacco then liquor again, with allowances of 2 and 1 units."""
    estate = fx.liquor_estate(api, allowance_units=2)
    tobacco_brand = fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")
    cigar = fx.listed_product(
        api,
        tobacco_brand["id"],
        sku="EMB-CIGAR-01",
        category="TOBACCO",
        unit_price_cents=500,
        duty_rate_bps=800,
        vat_rate_bps=450,
    )
    cigar_ledger = fx.stocked_ledger(api, estate.terminal["id"], cigar["id"], 10)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="TOBACCO",
        allowance_units=1,
        advisory_text="Australia: 25 cigarettes or 25 grams of tobacco per traveller.",
    )
    itinerary = fx.scanned_itinerary(
        api, estate.terminal["id"], departure_utc="2026-08-25T10:00:00Z"
    )
    sale = fx.open_basket(api, itinerary["id"])
    first = fx.append_line(api, sale["id"], estate.product["id"], 1)
    second = fx.append_line(api, sale["id"], cigar["id"], 2)
    third = fx.append_line(api, sale["id"], estate.product["id"], 2)
    return estate, cigar_ledger, sale, (first, second, third)


def test_each_category_keeps_its_own_allowance_consumed_in_line_order(api):
    """The tobacco line never touches the liquor allowance, and the second liquor line
    inherits only what the first liquor line already used.

    PRD 3.5: "Determine how much of that category's allowance the earlier lines already consumed: the sum of `qty` over the lines of the same basket whose product shares this product's `category` and whose `created_at` is strictly earlier than this line's."

    Design: Corner/calculations/allowance_waterfall_is_scoped_per_category_and_consumed_in_created_at_order
    """
    _estate, cigar_ledger, sale, lines = _mixed_category_basket(api)
    first, second, third = lines

    cleared = fx.clear_basket(api, sale["id"])

    assert_line_split(
        ok(api.get_sale_line(first["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=0,
        exempt_cents=8000,
        duty_cents=0,
    )
    assert_line_split(
        ok(api.get_sale_line(second["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=1,
        exempt_cents=500,
        duty_cents=63,
    )
    assert_line_split(
        ok(api.get_sale_line(third["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=1,
        exempt_cents=8000,
        duty_cents=1920,
    )
    assert_sale_amounts(cleared, gross=25000, exempt=16500, duty=1983)
    assert cleared["arrival_advisory"] == [
        "Travellers arriving in Australia may import 2 litres of spirits duty free.",
        "Australia: 25 cigarettes or 25 grams of tobacco per traveller.",
    ]
    assert ok(api.get_stock_item(cigar_ledger["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 10


def test_the_missing_allowance_rule_and_the_settled_period_both_answer_before_the_money_moves(api):
    """The first clearance is refused for a category with no rule and leaves the amounts at
    zero; the void after settlement is refused and leaves the handover intact.

    PRD 3.5: "Finally an `ACTIVE` arrival-allowance rule must exist for the effective destination and for **every** distinct product category present in the basket; a single category without a rule refuses the whole request with `ERR_ALLOWANCE_RULE_MISSING`."

    Design: Corner/validations/allowance_rule_and_period_close_guards_run_before_the_amounts_are_touched
    """
    estate = fx.liquor_estate(api, allowance_units=2)
    tobacco_brand = fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")
    cigar = fx.listed_product(
        api,
        tobacco_brand["id"],
        sku="EMB-CIGAR-01",
        category="TOBACCO",
        unit_price_cents=500,
        duty_rate_bps=800,
        vat_rate_bps=450,
    )
    cigar_ledger = fx.stocked_ledger(api, estate.terminal["id"], cigar["id"], 10)
    itinerary = fx.scanned_itinerary(
        api, estate.terminal["id"], departure_utc="2026-09-25T10:00:00Z"
    )
    sale = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, sale["id"], estate.product["id"], 1)
    fx.append_line(api, sale["id"], cigar["id"], 1)

    validate_error(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_ALLOWANCE_RULE_MISSING)
    untouched = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(untouched, fulfillment_status="CART", duty_status="SUSPENDED")
    assert untouched["exempt_amount_cents"] == 0
    assert untouched["duty_liability_cents"] == 0

    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="TOBACCO",
        allowance_units=10,
        advisory_text="Australia: 25 cigarettes or 25 grams of tobacco per traveller.",
    )

    cleared = ok(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert cleared["arrival_advisory"] == [
        "Travellers arriving in Australia may import 2 litres of spirits duty free.",
        "Australia: 25 cigarettes or 25 grams of tobacco per traveller.",
    ]

    handed_over = fx.hand_over(api, sale["id"])
    assert_sale_amounts(handed_over, gross=8500, exempt=8500, duty=0)
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")

    accrued = ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert accrued["gross_sales_cents"] == 8500
    assert accrued["percentage_rent_cents"] == 1020

    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    closed = ok(api.close_agreement_period(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert closed["status"] == "CLOSED"
    assert closed["final_rent_cents"] == 10000
    assert closed["rent_basis"] == "MINIMUM_GUARANTEE"

    validate_error(api.void_sale(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_VOID_AFTER_PERIOD_CLOSE)

    preserved = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(preserved, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 9
    assert ok(api.get_stock_item(cigar_ledger["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 9

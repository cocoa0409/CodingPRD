"""Boarding-pass verification, the amend/rescan cycle and the exclusive departure instant."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BOARDING_PASS_MISMATCH,
    ERR_DEPARTURE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_ITINERARY_NOT_INTERNATIONAL,
)
from test_helpers.assertions import (
    assert_line_split,
    assert_nulls,
    assert_sale_amounts,
    assert_sale_dimensions,
    ok,
)
from test_helpers.test_users import SALES_ASSOCIATE_HEADERS, TERMINAL_ADMIN_HEADERS


def _cleared_basket_bound_for_australia(api):
    """A three-bottle basket cleared against an AU allowance of one unit."""
    estate = fx.liquor_estate(api, allowance_units=1)
    fx.publish_allowance_rule(
        api,
        destination_country="NZ",
        category="LIQUOR",
        allowance_units=3,
        advisory_text="New Zealand: 3 bottles of spirits per traveller.",
    )
    basket = fx.till_ready_basket(
        api,
        estate,
        qty=3,
        itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"},
    )
    cleared = fx.clear_basket(api, basket.sale["id"])
    assert_sale_amounts(cleared, gross=24000, exempt=8000, duty=3840)
    return estate, basket


def test_amending_a_scanned_itinerary_drags_the_cleared_basket_back_to_cart(api):
    """The backward edge unwinds the till dimension and zeroes every priced figure while
    the duty dimension stays exactly where it was.

    PRD 3.4: "Every basket of that itinerary that had already been cleared for sale is unwound in the same request: each such sale reverts `ELIGIBILITY_CLEARED → CART` on its till dimension, its `exempt_amount_cents` and `duty_liability_cents` return to 0, every one of its lines has `allowance_excess_qty`, `line_exempt_cents` and `line_duty_cents` reset to 0, and `eligibility_variant`, `effective_destination_country` and `cleared_at` are cleared to null, `arrival_advisory` back to an empty list and `sealed_bag_required` back to false."

    Design: Difficulty/non_linear_state_machine/itinerary_amend_rescan_cycle_reverts_and_reprices_cleared_sale
    """
    _estate, basket = _cleared_basket_bound_for_australia(api)

    amended = ok(
        api.amend_itinerary(
            basket.itinerary["id"],
            f.amend_payload("NZ", "NZ", has_connection=False),
            SALES_ASSOCIATE_HEADERS,
        )
    )
    assert amended["scan_status"] == "AMENDED"
    assert amended["amend_count"] == 1
    assert_nulls(amended, "scanned_at")

    sale = ok(api.get_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(sale, fulfillment_status="CART", duty_status="SUSPENDED")
    assert_sale_amounts(sale, gross=24000, exempt=0, duty=0)
    assert_nulls(sale, "eligibility_variant", "effective_destination_country", "cleared_at")
    assert sale["arrival_advisory"] == []
    assert sale["sealed_bag_required"] is False

    line = ok(api.get_sale_line(basket.line["id"], SALES_ASSOCIATE_HEADERS))
    assert_line_split(line, excess_qty=0, exempt_cents=0, duty_cents=0)


def test_the_rescan_closes_the_cycle_and_the_basket_reprices_against_the_new_routing(api):
    """SCANNED → AMENDED → SCANNED leaves ``amend_count`` at 1, and re-clearing against the
    New Zealand allowance turns 8000/3840 into 24000/0.

    PRD 3.4: "Re-scanning closes the cycle `SCANNED → AMENDED → SCANNED`, and `amend_count` is never reset, so the number of amendments over a journey is permanently visible."

    Design: Difficulty/non_linear_state_machine/itinerary_amend_rescan_cycle_reverts_and_reprices_cleared_sale
    """
    _estate, basket = _cleared_basket_bound_for_australia(api)

    ok(
        api.amend_itinerary(
            basket.itinerary["id"],
            f.amend_payload("NZ", "NZ", has_connection=False),
            SALES_ASSOCIATE_HEADERS,
        )
    )
    rescanned = ok(
        api.scan_boarding_pass(
            basket.itinerary["id"],
            f.scan_payload(basket.itinerary["boarding_pass_barcode"]),
            SALES_ASSOCIATE_HEADERS,
        )
    )
    assert rescanned["scan_status"] == "SCANNED"
    assert rescanned["amend_count"] == 1
    assert rescanned["scanned_at"] is not None

    recleared = fx.clear_basket(api, basket.sale["id"])
    assert_sale_dimensions(recleared, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")
    assert recleared["effective_destination_country"] == "NZ"
    assert_sale_amounts(recleared, gross=24000, exempt=24000, duty=0)

    line = ok(api.get_sale_line(basket.line["id"], SALES_ASSOCIATE_HEADERS))
    assert_line_split(line, excess_qty=0, exempt_cents=24000, duty_cents=0)


def test_a_domestic_journey_and_a_wrong_barcode_are_both_refused_at_the_till(api):
    """``is_international`` is derived at creation, and neither refusal moves the scan status
    or the terminal's observed mix.

    PRD 3.4: "A scan is admissible only from `UNSCANNED` or from `AMENDED` — scanning an itinerary that is already `SCANNED` is refused with `ERR_ITINERARY_SCAN_STATE_INVALID` — the journey must be international, else `ERR_ITINERARY_NOT_INTERNATIONAL`, and the logical clock must be strictly before `departure_utc`, else `ERR_DEPARTURE_PASSED`."

    Design: Corner/validations/domestic_itinerary_and_barcode_mismatch_are_rejected_at_scan
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    domestic = fx.record_itinerary(
        api,
        terminal["id"],
        nationality_code="SG",
        boarding_pass_barcode="BP-0118",
        departure_utc="2026-08-25T10:00:00Z",
        destination_country="SG",
        final_destination_country="SG",
    )
    international = fx.record_itinerary(
        api,
        terminal["id"],
        nationality_code="CN",
        boarding_pass_barcode="BP-0119",
        departure_utc="2026-08-25T11:00:00Z",
        destination_country="AU",
        final_destination_country="AU",
    )
    assert domestic["is_international"] is False
    assert international["is_international"] is True

    validate_error(
        api.scan_boarding_pass(domestic["id"], f.scan_payload("BP-0118"), SALES_ASSOCIATE_HEADERS),
        ERR_ITINERARY_NOT_INTERNATIONAL,
    )
    assert ok(api.get_itinerary(domestic["id"], SALES_ASSOCIATE_HEADERS))["scan_status"] == "UNSCANNED"

    validate_error(
        api.scan_boarding_pass(international["id"], f.scan_payload("BP-0118"), SALES_ASSOCIATE_HEADERS),
        ERR_BOARDING_PASS_MISMATCH,
    )
    assert ok(api.get_itinerary(international["id"], SALES_ASSOCIATE_HEADERS))["scan_status"] == "UNSCANNED"
    assert ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))["scanned_itinerary_count_30d"] == 0

    scanned = ok(
        api.scan_boarding_pass(international["id"], f.scan_payload("BP-0119"), SALES_ASSOCIATE_HEADERS)
    )
    assert scanned["scan_status"] == "SCANNED"
    stored_terminal = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_terminal["scanned_itinerary_count_30d"] == 1
    assert stored_terminal["traveler_nationality_mix"]["CN"] == 10000


def test_the_clock_reaching_departure_closes_the_till_and_cannot_be_rewound(api):
    """One second before departure the basket clears; at exactly ``departure_utc`` both
    handover and amendment are refused, and the clock refuses to go backwards.

    PRD 3.7: "The basket must not be voided (`ERR_SALE_ALREADY_TERMINAL`), its till dimension must be `ELIGIBILITY_CLEARED` (`ERR_SALE_NOT_CLEARED`), its itinerary must still be verified with a `scan_status` of `SCANNED` or `AMENDED` (`ERR_ITINERARY_NOT_SCANNED`), and the logical clock must still be strictly before `departure_utc` (`ERR_DEPARTURE_PASSED`) — goods cannot be handed over after the aircraft has left."

    Design: Corner/validations/departure_instant_is_exclusive_so_the_clock_reaching_it_closes_the_sale
    """
    estate = fx.liquor_estate(api, allowance_units=10)
    basket = fx.till_ready_basket(
        api,
        estate,
        qty=1,
        itinerary_overrides={"departure_utc": "2026-08-10T00:00:00Z"},
    )

    fx.advance_clock(api, "2026-08-09T23:59:59Z")
    cleared = fx.clear_basket(api, basket.sale["id"])
    assert_sale_dimensions(cleared, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")

    fx.advance_clock(api, "2026-08-10T00:00:00Z")
    validate_error(api.pickup_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_DEPARTURE_PASSED)
    validate_error(
        api.amend_itinerary(
            basket.itinerary["id"], f.amend_payload("NZ", "NZ"), SALES_ASSOCIATE_HEADERS
        ),
        ERR_DEPARTURE_PASSED,
    )

    itinerary = ok(api.get_itinerary(basket.itinerary["id"], SALES_ASSOCIATE_HEADERS))
    assert itinerary["scan_status"] == "SCANNED"
    assert itinerary["amend_count"] == 0

    validate_error(api.set_clock("2026-08-05T00:00:00Z", TERMINAL_ADMIN_HEADERS), ERR_INVALID_REQUEST)
    assert ok(api.set_clock("2026-08-10T00:00:00Z", TERMINAL_ADMIN_HEADERS))["current_utc"].startswith(
        "2026-08-10T00:00:00"
    )

    assert ok(api.get_stock_item(estate.stock_item["id"], TERMINAL_ADMIN_HEADERS))["on_hand_qty"] == 10
    assert ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 0

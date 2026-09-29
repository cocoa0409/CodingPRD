"""Till-dimension ordering, the terminal VOIDED state and the optimistic guard on line append."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_EMPTY_BASKET,
    ERR_ITINERARY_NOT_SCANNED,
    ERR_ITINERARY_SCAN_STATE_INVALID,
    ERR_PRODUCT_NOT_LISTED,
    ERR_SALE_ALREADY_TERMINAL,
    ERR_SALE_NOT_CLEARED,
    ERR_SALE_NOT_IN_CART,
    ERR_STALE_SALE_VERSION,
)
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    assert_sale_dimensions,
    assert_stock_quantities,
    created,
    ids_of,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
)


def test_handover_and_bag_issuance_from_cart_report_the_uncleared_basket(api):
    """Both triggers belong to a cleared basket, so both answer ERR_SALE_NOT_CLEARED.

    PRD 3.6: "A bag may only be issued for a basket whose till dimension is `ELIGIBILITY_CLEARED`, else `ERR_SALE_NOT_CLEARED`."

    Design: Corner/state_machines/out_of_order_sale_triggers_are_refused_with_the_dimension_specific_state_error
    """
    estate = fx.liquor_estate(api, allowance_units=5)
    basket = fx.till_ready_basket(api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"})
    version_before = basket.sale["version"]

    validate_error(api.pickup_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_NOT_CLEARED)
    validate_error(
        api.create_sealed_bag(
            f.sealed_bag_payload(basket.sale["id"], "STEB-0003"), SALES_ASSOCIATE_HEADERS
        ),
        ERR_SALE_NOT_CLEARED,
    )

    sale = ok(api.get_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(sale, fulfillment_status="CART", duty_status="SUSPENDED")
    assert sale["version"] == version_before

    bags, _ = page(api.list_sealed_bags(SALES_ASSOCIATE_HEADERS, {"sale_id": basket.sale["id"]}))
    assert bags == []
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 10


def test_a_cleared_basket_refuses_a_further_line_and_a_second_clearance(api):
    """The state check answers before the optimistic guard does, and neither refusal bumps
    the basket's version.

    PRD 3.5: "The basket must not already be voided, else `ERR_SALE_ALREADY_TERMINAL`, and must still be in `CART`, else `ERR_SALE_NOT_IN_CART`."

    Design: Corner/state_machines/out_of_order_sale_triggers_are_refused_with_the_dimension_specific_state_error
    """
    estate = fx.liquor_estate(api, allowance_units=5)
    basket = fx.till_ready_basket(api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"})

    cleared = fx.clear_basket(api, basket.sale["id"])
    version_after_clearance = cleared["version"]

    validate_error(
        api.add_sale_line(
            basket.sale["id"],
            f.sale_line_payload(estate.product["id"], 1, version_after_clearance),
            SALES_ASSOCIATE_HEADERS,
        ),
        ERR_SALE_NOT_IN_CART,
    )
    validate_error(api.clear_eligibility(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_NOT_IN_CART)

    sale = ok(api.get_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert sale["version"] == version_after_clearance
    assert sale["gross_amount_cents"] == 16000

    lines, _ = page(api.list_sale_lines(SALES_ASSOCIATE_HEADERS, {"sale_id": basket.sale["id"]}))
    assert len(lines) == 1


def test_a_voided_basket_answers_the_terminal_state_error_for_every_trigger(api):
    """VOIDED sits above the ordinary state errors, so void, clearance, handover and line
    append all report ERR_SALE_ALREADY_TERMINAL.

    PRD 3.7: "Voiding is available from all three non-terminal till states and always produces the same visible outcome: the till dimension moves to `VOIDED` — from `CART`, from `ELIGIBILITY_CLEARED`, or from `PICKED_UP` — the duty dimension moves to `REVERSED`, `voided_at` is stamped with the logical clock, `exempt_amount_cents` and `duty_liability_cents` are both set to 0, and every sealed bag of the basket is voided as described in §3.6."

    Design: Corner/state_machines/voided_sale_refuses_every_further_trigger_at_priority_59
    """
    estate = fx.liquor_estate(api, allowance_units=5)
    basket = fx.till_ready_basket(api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"})

    voided = fx.void_basket(api, basket.sale["id"])
    assert_sale_dimensions(voided, fulfillment_status="VOIDED", duty_status="REVERSED")
    assert_instant(voided["voided_at"], CLOCK_START, "voided_at")
    version_after_void = voided["version"]

    validate_error(api.void_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_ALREADY_TERMINAL)
    validate_error(api.clear_eligibility(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_ALREADY_TERMINAL)
    validate_error(api.pickup_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_ALREADY_TERMINAL)
    validate_error(
        api.add_sale_line(
            basket.sale["id"],
            f.sale_line_payload(estate.product["id"], 1, version_after_void),
            SALES_ASSOCIATE_HEADERS,
        ),
        ERR_SALE_ALREADY_TERMINAL,
    )

    sale = ok(api.get_sale(basket.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert sale["version"] == version_after_void
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 10
    movements, _ = page(
        api.list_movements(STOCK_CONTROLLER_HEADERS, {"stock_item_id": estate.stock_item["id"]})
    )
    assert len(movements) == 1


def test_the_unscanned_itinerary_answers_before_the_empty_basket_does(api):
    """Two rules are broken at once; the state tier reports first and the constraint tier
    only surfaces once the pass is scanned.

    PRD 2.8: "Within this tier, the resource named in the path is checked before the resources it references: a basket's own status precedes its itinerary's scan status, which precedes the product's assortment status."

    Design: Corner/validations/unscanned_state_error_outranks_empty_basket_constraint_error
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    fx.active_agreement(api, terminal["id"])
    itinerary = fx.record_itinerary(
        api,
        terminal["id"],
        boarding_pass_barcode="BP-0125",
        departure_utc="2026-08-25T10:00:00Z",
    )
    sale = fx.open_basket(api, itinerary["id"])

    validate_error(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_ITINERARY_NOT_SCANNED)

    fx.scan_itinerary(api, itinerary)

    validate_error(api.clear_eligibility(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_EMPTY_BASKET)

    stored = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(stored, fulfillment_status="CART", duty_status="SUSPENDED")
    assert_nulls(stored, "eligibility_variant")


def test_a_reused_sale_version_is_refused_while_the_fresh_one_is_accepted(api):
    """Every accepted line bumps the basket's version, so the guard quoted for line one is
    already stale for line two.

    PRD 2.7: "`POST /sales/{sale_id}/lines` requires a non-optional `expected_sale_version` field carrying the `version` of the parent `Sale` as the client last observed it. If that value does not equal the sale's current `version`, the line append is rejected with `ERR_STALE_SALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_sale_version_on_line_append_is_a_precondition_failure
    """
    estate = fx.liquor_estate(api, allowance_units=10)
    gin = fx.listed_product(
        api,
        estate.brand["id"],
        sku="AUR-GIN-500",
        category="LIQUOR",
        unit_price_cents=6000,
        is_liquid=True,
        liquid_ml=500,
    )
    fx.stocked_ledger(api, estate.terminal["id"], gin["id"], 10)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T10:00:00Z")
    sale = fx.open_basket(api, itinerary["id"])
    version_zero = sale["version"]

    first_line = created(
        api.add_sale_line(
            sale["id"],
            f.sale_line_payload(estate.product["id"], 1, version_zero),
            SALES_ASSOCIATE_HEADERS,
        )
    )
    assert first_line["line_total_cents"] == 8000

    validate_error(
        api.add_sale_line(
            sale["id"], f.sale_line_payload(gin["id"], 1, version_zero), SALES_ASSOCIATE_HEADERS
        ),
        ERR_STALE_SALE_VERSION,
    )
    lines, _ = page(api.list_sale_lines(SALES_ASSOCIATE_HEADERS, {"sale_id": sale["id"]}))
    assert ids_of(lines) == [first_line["id"]]

    after_first = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert after_first["version"] == version_zero + 1

    second_line = created(
        api.add_sale_line(
            sale["id"], f.sale_line_payload(gin["id"], 1, after_first["version"]), SALES_ASSOCIATE_HEADERS
        )
    )
    assert second_line["line_total_cents"] == 6000

    after_second = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert after_second["version"] == after_first["version"] + 1
    assert after_second["gross_amount_cents"] == 14000

    gin_ledger, _ = page(api.list_stock_items(STOCK_CONTROLLER_HEADERS, {"product_id": gin["id"]}))
    assert_stock_quantities(gin_ledger[0], on_hand=10, reserved=0, available=10)


def test_a_second_scan_a_second_activation_and_a_pending_sku_are_all_refused(api):
    """Three state refusals that leave their targets exactly as they were.

    PRD 3.5: "The product must be in `LISTED` standing, else `ERR_PRODUCT_NOT_LISTED` — a `PENDING` SKU has never been admitted and a `DELISTED` one has been withdrawn, and neither may be sold."

    Design: Corner/errors/scan_listing_and_agreement_triggers_from_the_wrong_state_are_rejected
    """
    estate = fx.liquor_estate(api, allowance_units=10)
    pending = fx.register_product(
        api,
        estate.brand["id"],
        sku="AUR-GIN-500",
        category="LIQUOR",
        unit_price_cents=6000,
        is_liquid=True,
        liquid_ml=500,
    )
    pending_ledger = fx.stocked_ledger(api, estate.terminal["id"], pending["id"], 10)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], departure_utc="2026-08-25T10:00:00Z")
    sale = fx.open_basket(api, itinerary["id"])

    validate_error(
        api.scan_boarding_pass(
            itinerary["id"], f.scan_payload(itinerary["boarding_pass_barcode"]), SALES_ASSOCIATE_HEADERS
        ),
        ERR_ITINERARY_SCAN_STATE_INVALID,
    )
    stored_itinerary = ok(api.get_itinerary(itinerary["id"], SALES_ASSOCIATE_HEADERS))
    assert stored_itinerary["scan_status"] == "SCANNED"
    assert_instant(stored_itinerary["scanned_at"], CLOCK_START, "scanned_at")

    validate_error(
        api.activate_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS), ERR_AGREEMENT_NOT_ACTIVE
    )
    stored_agreement = ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert stored_agreement["status"] == "ACTIVE"
    assert stored_agreement["gross_sales_cents"] == 0

    validate_error(
        api.add_sale_line(
            sale["id"], f.sale_line_payload(pending["id"], 1, sale["version"]), SALES_ASSOCIATE_HEADERS
        ),
        ERR_PRODUCT_NOT_LISTED,
    )
    assert_stock_quantities(
        ok(api.get_stock_item(pending_ledger["id"], STOCK_CONTROLLER_HEADERS)),
        on_hand=10,
        reserved=0,
        available=10,
    )

    accepted = created(
        api.add_sale_line(
            sale["id"], f.sale_line_payload(estate.product["id"], 1, sale["version"]), SALES_ASSOCIATE_HEADERS
        )
    )
    lines, _ = page(api.list_sale_lines(SALES_ASSOCIATE_HEADERS, {"sale_id": sale["id"]}))
    assert ids_of(lines) == [accepted["id"]]
    assert lines[0]["product_id"] == estate.product["id"]

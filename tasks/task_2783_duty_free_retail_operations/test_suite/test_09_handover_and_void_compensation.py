"""Handover's four-level cascade, its guard order and the money it gives back on a void."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BONDED_STOCK_INSUFFICIENT,
    ERR_SALE_NOT_CLEARED,
)
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    assert_sale_amounts,
    assert_sale_dimensions,
    assert_stock_quantities,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
)


def _watch_estate_with_cleared_basket(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE"):
    """A twenty-unit watch ledger and one cleared five-unit basket worth 100000 cents."""
    terminal = fx.register_terminal(
        api, iata_code=iata_code, country_code=country_code, sealed_bag_regime=sealed_bag_regime
    )
    brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    stock_item = fx.stocked_ledger(api, terminal["id"], watch["id"], 20)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="ELECTRONICS",
        allowance_units=10,
        advisory_text="Australia: general goods allowance AUD 900 per adult.",
    )
    agreement = fx.active_agreement(api, terminal["id"])
    itinerary = fx.scanned_itinerary(api, terminal["id"], departure_utc="2026-08-25T10:00:00Z")
    sale = fx.open_basket(api, itinerary["id"])
    line = fx.append_line(api, sale["id"], watch["id"], 5)
    fx.clear_basket(api, sale["id"])
    return terminal, stock_item, agreement, sale, line


def test_the_handover_drives_the_ledger_entry_that_drains_the_bonded_position(api):
    """Levels one and two: the duty dimension resolves, and because it left suspension a single
    SALE_ISSUE entry re-derives the whole bonded position.

    PRD 3.7: "**Second**, because the duty dimension has left `SUSPENDED`, the goods must leave bond: one `SALE_ISSUE` ledger entry is appended per line, processed in the lines' ascending `created_at` order, each with a `qty_delta` of the negated line `qty`, an `affects` of `ON_HAND`, a `source_ref_type` of `SALE`, a `source_ref_id` of the basket's identifier and an `agreement_period_code` of the `period_code` of the terminal's `ACTIVE` agreement."

    Design: Difficulty/transitive_cascade/pickup_cascade_depth_four_duty_status_to_ledger_to_rent_to_basis
    """
    _terminal, stock_item, agreement, sale, _line = _watch_estate_with_cleared_basket(api)

    before = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(before, on_hand=20, reserved=0, available=20)
    assert before["duty_suspended_value_cents"] == 28000
    assert ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 0

    handed_over = fx.hand_over(api, sale["id"])
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")

    issues, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert len(issues) == 1
    assert issues[0]["qty_delta"] == -5
    assert issues[0]["affects"] == "ON_HAND"
    assert issues[0]["source_ref_type"] == "SALE"
    assert issues[0]["source_ref_id"] == sale["id"]
    assert issues[0]["agreement_period_code"] == "2026-08"

    after = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(after, on_hand=15, reserved=0, available=15)
    assert after["duty_suspended_value_cents"] == 21000


def test_the_ledger_entry_lifts_the_turnover_and_the_turnover_flips_the_rent_basis(api):
    """Levels three and four: 100000 cents of turnover produce 12000 of percentage rent, which
    overtakes the guarantee and re-derives the basis.

    PRD 3.7: "**Third**, because those entries carry an `agreement_period_code`, the concession ledger moves: the agreement's `gross_sales_cents` increases by the basket's `gross_amount_cents` and its `percentage_rent_cents` is recomputed. **Fourth**, because `percentage_rent_cents` changed, the agreement's `rent_basis` is re-derived, becoming `PERCENTAGE` when `percentage_rent_cents` is greater than or equal to `minimum_guarantee_cents` and `MINIMUM_GUARANTEE` otherwise."

    Design: Difficulty/transitive_cascade/pickup_cascade_depth_four_duty_status_to_ledger_to_rent_to_basis
    """
    _terminal, _stock_item, agreement, sale, _line = _watch_estate_with_cleared_basket(api)

    assert ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))["rent_basis"] == "MINIMUM_GUARANTEE"

    handed_over = fx.hand_over(api, sale["id"])
    assert handed_over["gross_amount_cents"] == 100000

    settled = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert settled["gross_sales_cents"] == 100000
    assert settled["percentage_rent_cents"] == 12000
    assert settled["rent_basis"] == "PERCENTAGE"


def _drained_ledger_with_a_cart_basket(api):
    """A three-unit line added while stock was plentiful, then drained to two units."""
    estate = fx.liquor_estate(api, receipt_qty=100, allowance_units=3)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], departure_utc="2026-08-25T10:00:00Z")
    sale = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, sale["id"], estate.product["id"], 3)
    fx.post_adjustment(api, estate.stock_item["id"], -98)
    return estate, sale


def test_the_uncleared_basket_answers_before_the_drained_ledger(api):
    """The pickup breaks both rules at once; the state tier is what reports.

    PRD 3.7: "The basket must not be voided (`ERR_SALE_ALREADY_TERMINAL`), its till dimension must be `ELIGIBILITY_CLEARED` (`ERR_SALE_NOT_CLEARED`), its itinerary must still be verified with a `scan_status` of `SCANNED` or `AMENDED` (`ERR_ITINERARY_NOT_SCANNED`), and the logical clock must still be strictly before `departure_utc` (`ERR_DEPARTURE_PASSED`)"

    Design: Difficulty/priority_pair_validation_conflict/sale_not_cleared_state_error_outranks_bonded_stock_insufficient_fiscal_error
    """
    estate, sale = _drained_ledger_with_a_cart_basket(api)

    drained = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(drained, on_hand=2, reserved=0, available=2)

    response = api.pickup_sale(sale["id"], SALES_ASSOCIATE_HEADERS)
    validate_error(response, ERR_SALE_NOT_CLEARED)
    assert response.json()["data"]["error_id"] != ERR_BONDED_STOCK_INSUFFICIENT

    assert ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))["fulfillment_status"] == "CART"


def test_clearing_the_basket_isolates_the_drained_ledger(api):
    """Once the till dimension is right, the fiscal coverage rule is the live one and the
    refused handover leaves the bonded position untouched.

    PRD 3.7: "Lastly, every line must still be coverable: for each line, the bonded ledger of that product at the basket's terminal must have an `available_qty` of at least the line's `qty`, else `ERR_BONDED_STOCK_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/sale_not_cleared_state_error_outranks_bonded_stock_insufficient_fiscal_error
    """
    estate, sale = _drained_ledger_with_a_cart_basket(api)

    validate_error(api.pickup_sale(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SALE_NOT_CLEARED)

    cleared = fx.clear_basket(api, sale["id"])
    assert cleared["fulfillment_status"] == "ELIGIBILITY_CLEARED"

    validate_error(api.pickup_sale(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_BONDED_STOCK_INSUFFICIENT)

    stalled = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert stalled["fulfillment_status"] == "ELIGIBILITY_CLEARED"
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 2
    issues, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert issues == []


def _picked_up_watch_basket(api):
    """A collected 100000-cent basket whose turnover has already flipped the rent basis."""
    terminal, stock_item, agreement, sale, line = _watch_estate_with_cleared_basket(
        api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB"
    )
    fx.hand_over(api, sale["id"])
    return terminal, stock_item, agreement, sale, line


def test_voiding_a_collected_basket_gives_the_turnover_back_and_re_derives_the_basis(api):
    """The rent rolls all the way back to the guarantee while the basket keeps its gross as the
    audit trail.

    PRD 3.7: "Because those compensating entries carry the same `agreement_period_code` as the originals, the agreement's `gross_sales_cents` decreases by the basket's `gross_amount_cents`, its `percentage_rent_cents` is recomputed from the reduced turnover, its `rent_basis` is re-derived from that new figure, and its `version` increments by 1."

    Design: Difficulty/compensating_invariant/void_of_picked_up_sale_conserves_concession_gross_sales_and_rent_basis
    """
    _terminal, _stock_item, agreement, sale, _line = _picked_up_watch_basket(api)

    before = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert before["gross_sales_cents"] == 100000
    assert before["percentage_rent_cents"] == 12000
    assert before["rent_basis"] == "PERCENTAGE"

    voided = fx.void_basket(api, sale["id"])
    assert_sale_dimensions(voided, fulfillment_status="VOIDED", duty_status="REVERSED")
    assert_sale_amounts(voided, gross=100000, exempt=0, duty=0)
    assert_instant(voided["voided_at"], CLOCK_START, "voided_at")

    after = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert after["gross_sales_cents"] == 0
    assert after["percentage_rent_cents"] == 0
    assert after["rent_basis"] == "MINIMUM_GUARANTEE"


def test_the_same_void_restores_the_bonded_units_through_a_compensating_entry(api):
    """The reversal is appended rather than the issue being edited, and both conserved
    quantities land back where they started.

    PRD 3.7: "Both conserved quantities — bonded units on hand and accrued turnover — end exactly where they stood before the handover."

    Design: Difficulty/compensating_invariant/void_of_picked_up_sale_conserves_concession_gross_sales_and_rent_basis
    """
    _terminal, stock_item, _agreement, sale, _line = _picked_up_watch_basket(api)

    issued = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(issued, on_hand=15, reserved=0, available=15)
    assert issued["duty_suspended_value_cents"] == 21000

    originals, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert len(originals) == 1

    fx.void_basket(api, sale["id"])

    reversals, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": stock_item["id"], "movement_type": "REVERSAL"},
        )
    )
    assert len(reversals) == 1
    assert reversals[0]["qty_delta"] == 5
    assert reversals[0]["affects"] == "ON_HAND"
    assert reversals[0]["source_ref_type"] == "SALE"
    assert reversals[0]["source_ref_id"] == sale["id"]
    assert reversals[0]["reversal_of_movement_id"] == originals[0]["id"]
    assert ok(api.get_movement(originals[0]["id"], STOCK_CONTROLLER_HEADERS))["reversed"] is True

    restored = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(restored, on_hand=20, reserved=0, available=20)
    assert restored["duty_suspended_value_cents"] == 28000


def test_two_individually_valid_baskets_cannot_both_draw_the_same_units(api):
    """Each basket of four is coverable on its own against six units, but the coverage test runs
    per handover, so the second one finds only two units left.

    PRD 3.7: "Lastly, every line must still be coverable: for each line, the bonded ledger of that product at the basket's terminal must have an `available_qty` of at least the line's `qty`, else `ERR_BONDED_STOCK_INSUFFICIENT`."

    Design: Corner/validations/two_individually_valid_baskets_cannot_both_draw_the_same_bonded_units
    """
    estate = fx.liquor_estate(api, receipt_qty=6, allowance_units=10)
    first = fx.till_ready_basket(
        api, estate, qty=4, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )
    second = fx.till_ready_basket(
        api, estate, qty=4, itinerary_overrides={"departure_utc": "2026-08-26T10:00:00Z"}
    )
    fx.clear_basket(api, first.sale["id"])
    fx.clear_basket(api, second.sale["id"])

    collected = fx.hand_over(api, first.sale["id"])
    assert collected["fulfillment_status"] == "PICKED_UP"
    assert_stock_quantities(
        ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS)),
        on_hand=2,
        reserved=0,
        available=2,
    )

    validate_error(api.pickup_sale(second.sale["id"], SALES_ASSOCIATE_HEADERS), ERR_BONDED_STOCK_INSUFFICIENT)

    refused = ok(api.get_sale(second.sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(refused, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")
    assert_nulls(refused, "picked_up_at")

    unchanged = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert unchanged["on_hand_qty"] == 2
    assert unchanged["duty_suspended_value_cents"] == 3840

    assert ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 32000
    issues, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert len(issues) == 1


def test_only_the_collected_basket_counts_as_concessionable_turnover(api):
    """A basket in the cart and a basket merely cleared both contribute nothing to the rent.

    PRD 3.10: "`gross_sales_cents` counts the `gross_amount_cents` of exactly those baskets whose `agreement_id` is this agreement and whose till dimension is `PICKED_UP`. Baskets still in `CART`, baskets merely `ELIGIBILITY_CLEARED`, and baskets that were voided are all excluded — only goods that physically left the store are concessionable turnover."

    Design: Corner/calculations/concession_gross_sales_counts_only_picked_up_sales
    """
    estate = fx.liquor_estate(api, receipt_qty=30, allowance_units=5)
    in_cart = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-25T10:00:00Z"}
    )
    cleared_only = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-26T10:00:00Z"}
    )
    collected = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-27T10:00:00Z"}
    )
    fx.clear_basket(api, cleared_only.sale["id"])
    fx.clear_basket(api, collected.sale["id"])
    fx.hand_over(api, collected.sale["id"])

    assert ok(api.get_sale(in_cart.sale["id"], SALES_ASSOCIATE_HEADERS))["fulfillment_status"] == "CART"
    assert (
        ok(api.get_sale(cleared_only.sale["id"], SALES_ASSOCIATE_HEADERS))["fulfillment_status"]
        == "ELIGIBILITY_CLEARED"
    )

    settled = ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert settled["gross_sales_cents"] == 16000
    assert settled["percentage_rent_cents"] == 1920
    assert settled["rent_basis"] == "MINIMUM_GUARANTEE"

    projection = ok(api.get_rent_projection(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert projection["gross_sales_cents"] == 16000
    assert projection["percentage_rent_cents"] == 1920
    assert projection["prorated_minimum_guarantee_cents"] == 323
    assert projection["provisional_rent_cents"] == 1920
    assert projection["rent_basis"] == "PERCENTAGE"

    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 28


def test_the_pickup_response_already_carries_every_level_of_the_cascade(api):
    """The triggering response holds the finalised totals, and the very next reads of the
    agreement, the ledger and the movement list agree with it.

    PRD 3.7: "A successful handover runs a four-level cascade, and each level exists because of the one above it."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response_that_caused_it
    """
    estate = fx.liquor_estate(api, allowance_units=1, with_agreement=False)
    agreement = fx.active_agreement(api, estate.terminal["id"], minimum_guarantee_cents=1000)
    basket = fx.till_ready_basket(
        api, estate, qty=2, itinerary_overrides={"departure_utc": "2026-08-20T10:00:00Z"}
    )
    fx.clear_basket(api, basket.sale["id"])

    handed_over = fx.hand_over(api, basket.sale["id"])
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="DUTY_LIABLE")
    assert_sale_amounts(handed_over, gross=16000, exempt=8000, duty=1920)
    assert handed_over["effective_destination_country"] == "AU"
    assert_instant(handed_over["picked_up_at"], CLOCK_START, "picked_up_at")

    settled = ok(api.get_agreement(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert settled["gross_sales_cents"] == 16000
    assert settled["percentage_rent_cents"] == 1920
    assert settled["rent_basis"] == "PERCENTAGE"

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=8, reserved=0, available=8)
    assert ledger["duty_suspended_value_cents"] == 15360

    issues, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "SALE_ISSUE"},
        )
    )
    assert len(issues) == 1
    assert issues[0]["qty_delta"] == -2

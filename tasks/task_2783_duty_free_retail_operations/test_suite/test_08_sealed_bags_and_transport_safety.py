"""Tamper-evident bags: volume snapshots, seal windows and the tamper forfeiture."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUDIT_NOT_SUBMITTED,
    ERR_AUDIT_PERIOD_NOT_CLOSED,
    ERR_BAG_NOT_ISSUED,
    ERR_DUPLICATE_BOARDING_PASS,
    ERR_DUPLICATE_SEAL_NUMBER,
    ERR_LIQUID_LIMIT_EXCEEDED,
    ERR_SEAL_WINDOW_EXPIRED,
    ERR_SEALED_BAG_REQUIRED,
)
from test_helpers.assertions import (
    assert_instant,
    assert_line_split,
    assert_nulls,
    assert_sale_amounts,
    assert_sale_dimensions,
    created,
    ids_of,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CUSTOMS_AUDITOR_HEADERS,
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
)

CONNECTING = {
    "departure_utc": "2026-08-05T10:00:00Z",
    "destination_country": "AU",
    "final_destination_country": "AU",
    "has_connection": True,
    "connection_country": "US",
    "connection_departure_utc": "2026-08-05T20:00:00Z",
}


def _sealed_basket_awaiting_inspection(api, qty=3, allowance_units=2):
    """A cleared connecting basket at an ICAO_STEB terminal with its seal issued."""
    estate = fx.liquor_estate(
        api,
        iata_code="HKG",
        country_code="HK",
        sealed_bag_regime="ICAO_STEB",
        allowance_units=allowance_units,
    )
    itinerary = fx.scanned_itinerary(
        api,
        estate.terminal["id"],
        departure_utc="2026-08-05T10:00:00Z",
        has_connection=True,
        connection_country="AU",
        connection_departure_utc="2026-08-06T02:00:00Z",
    )
    sale = fx.open_basket(api, itinerary["id"])
    line = fx.append_line(api, sale["id"], estate.product["id"], qty)
    cleared = fx.clear_basket(api, sale["id"])
    assert cleared["sealed_bag_required"] is True
    bag = fx.issue_bag(api, sale["id"], "STEB-0005")
    return estate, sale, line, bag


def test_a_tampered_seal_forfeits_the_allowance_without_moving_the_till(api):
    """The duty dimension advances to DUTY_LIABLE and the whole basket becomes dutiable, while
    the till dimension stays exactly where it was.

    PRD 3.6: "When the basket's `duty_status` is `SUSPENDED`, a tampered seal moves that dimension `SUSPENDED → DUTY_LIABLE` while leaving the till dimension exactly where it was, at `ELIGIBILITY_CLEARED`."

    Design: Difficulty/non_linear_state_machine/sale_parallel_dimensions_tamper_advances_duty_status_only
    """
    _estate, sale, line, bag = _sealed_basket_awaiting_inspection(api)

    before = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(before, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="SUSPENDED")
    assert_sale_amounts(before, gross=24000, exempt=16000, duty=1920)

    tampered = fx.verify_bag(api, bag["id"], "TAMPERED")
    assert tampered["status"] == "TAMPERED"
    assert_instant(tampered["verified_at"], CLOCK_START, "verified_at")

    after = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(after, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="DUTY_LIABLE")
    assert_sale_amounts(after, gross=24000, exempt=0, duty=5760)
    assert_line_split(
        ok(api.get_sale_line(line["id"], SALES_ASSOCIATE_HEADERS)),
        excess_qty=3,
        exempt_cents=0,
        duty_cents=5760,
    )


def test_the_tampered_basket_can_no_longer_be_handed_over(api):
    """A tampered bag is not an intact one, so the basket that required a bag is stuck.

    PRD 3.6: "Nothing about the basket's till standing has changed — but because a tampered bag is not an `INTACT_VERIFIED` one, a basket that required a bag can no longer be handed over, and the attempt is refused with `ERR_SEALED_BAG_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/sale_parallel_dimensions_tamper_advances_duty_status_only
    """
    estate, sale, _line, bag = _sealed_basket_awaiting_inspection(api)

    fx.verify_bag(api, bag["id"], "TAMPERED")

    validate_error(api.pickup_sale(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SEALED_BAG_REQUIRED)

    stuck = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert_sale_dimensions(stuck, fulfillment_status="ELIGIBILITY_CLEARED", duty_status="DUTY_LIABLE")
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 10
    assert ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 0


def _two_baskets_on_a_late_connection(api):
    """One 2100 ml basket and one 700 ml basket on a journey whose onward leg is far too late."""
    estate = fx.liquor_estate(
        api,
        iata_code="HKG",
        country_code="HK",
        sealed_bag_regime="ICAO_STEB",
        liquid_limit_ml=None,
        allowance_units=3,
    )
    itinerary = fx.scanned_itinerary(
        api,
        estate.terminal["id"],
        departure_utc="2026-08-05T10:00:00Z",
        destination_country="AU",
        final_destination_country="NZ",
        has_connection=True,
        connection_country="AU",
        connection_departure_utc="2026-08-20T00:00:00Z",
    )
    assert ok(api.get_terminal(estate.terminal["id"], TERMINAL_ADMIN_HEADERS))["liquid_limit_ml"] == 1000

    bulky = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, bulky["id"], estate.product["id"], 3)
    assert fx.clear_basket(api, bulky["id"])["sealed_bag_required"] is True

    slim = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, slim["id"], estate.product["id"], 1)
    assert fx.clear_basket(api, slim["id"])["sealed_bag_required"] is True

    return bulky, slim


def test_the_volume_breach_answers_before_the_lapsed_seal_window(api):
    """Both compliance checks fail on the bulky bag; the safety limit is the one reported.

    PRD 3.6: "The volume must not exceed the departure terminal's `liquid_limit_ml`; a bag whose `total_liquid_ml` is exactly equal to the limit is accepted, and one over it is refused with `ERR_LIQUID_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/liquid_limit_safety_error_outranks_seal_window_temporal_error
    """
    bulky, _slim = _two_baskets_on_a_late_connection(api)

    response = api.create_sealed_bag(
        f.sealed_bag_payload(bulky["id"], "STEB-0010A"), SALES_ASSOCIATE_HEADERS
    )
    validate_error(response, ERR_LIQUID_LIMIT_EXCEEDED)
    assert response.json()["data"]["error_id"] != ERR_SEAL_WINDOW_EXPIRED

    bags, _ = page(api.list_sealed_bags(SALES_ASSOCIATE_HEADERS, {"sale_id": bulky["id"]}))
    assert bags == []


def test_a_bag_inside_the_volume_limit_isolates_the_lapsed_seal_window(api):
    """With 700 ml the safety rule is satisfied, and the onward leg's lateness is what refuses.

    PRD 3.6: "And when the itinerary's `has_connection` is true, the onward leg must depart no later than the seal's expiry: a `connection_departure_utc` at or before `expires_at` is accepted, and one strictly after it is refused with `ERR_SEAL_WINDOW_EXPIRED`, because the seal would already have lapsed by the time the transfer screening looked at it."

    Design: Difficulty/priority_pair_validation_conflict/liquid_limit_safety_error_outranks_seal_window_temporal_error
    """
    _bulky, slim = _two_baskets_on_a_late_connection(api)

    validate_error(
        api.create_sealed_bag(f.sealed_bag_payload(slim["id"], "STEB-0010B"), SALES_ASSOCIATE_HEADERS),
        ERR_SEAL_WINDOW_EXPIRED,
    )

    bags, _ = page(api.list_sealed_bags(SALES_ASSOCIATE_HEADERS, {"sale_id": slim["id"]}))
    assert bags == []


def _mixed_liquid_and_dry_basket(api):
    """A cleared connecting basket of three bottles and one watch at an ICAO_STEB terminal."""
    estate = fx.liquor_estate(
        api,
        iata_code="HKG",
        country_code="HK",
        sealed_bag_regime="ICAO_STEB",
        allowance_units=5,
    )
    watch_brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        watch_brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    fx.stocked_ledger(api, estate.terminal["id"], watch["id"], 10)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="ELECTRONICS",
        allowance_units=5,
        advisory_text="Australia: general goods allowance AUD 900 per adult.",
    )
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], **CONNECTING)
    sale = fx.open_basket(api, itinerary["id"])
    fx.append_line(api, sale["id"], estate.product["id"], 3)
    fx.append_line(api, sale["id"], watch["id"], 1)
    return estate, sale


def test_the_bag_snapshots_only_liquid_volume_and_expires_96_hours_after_departure(api):
    """The dry watch contributes nothing to the volume, and the window is measured from the
    flight rather than from the moment of sealing.

    PRD 3.6: "`total_liquid_ml` is the sum, over the basket's lines whose product has `is_liquid` true, of the line's `qty` multiplied by that product's `liquid_ml`; lines whose product is not a liquid contribute nothing. `expires_at` is the itinerary's `departure_utc` advanced by the seal validity period of 96 hours — four full days, which is the window the operator's seals are certified for."

    Design: Corner/state_machines/sealed_bag_issuance_computes_liquid_volume_and_seal_expiry
    """
    estate, sale = _mixed_liquid_and_dry_basket(api)

    cleared = fx.clear_basket(api, sale["id"])
    assert cleared["sealed_bag_required"] is True
    assert cleared["gross_amount_cents"] == 44000
    assert len(cleared["arrival_advisory"]) == 2

    bag = created(
        api.create_sealed_bag(f.sealed_bag_payload(sale["id"], "STEB-0001"), SALES_ASSOCIATE_HEADERS)
    )
    assert bag["status"] == "ISSUED"
    assert bag["terminal_id"] == estate.terminal["id"]
    assert bag["total_liquid_ml"] == 2100
    assert_instant(bag["expires_at"], "2026-08-09T10:00:00Z", "expires_at")
    assert_instant(bag["issued_at"], CLOCK_START, "issued_at")
    assert_nulls(bag, "verified_at")


def test_pickup_waits_for_the_seal_to_be_verified_intact(api):
    """An ISSUED bag is not enough; only the intact verification opens the gate, and the
    verification itself leaves the duty dimension alone.

    PRD 3.7: "When the basket's `sealed_bag_required` is true, a bag of that basket in `INTACT_VERIFIED` standing must exist, else `ERR_SEALED_BAG_REQUIRED`."

    Design: Corner/state_machines/pickup_is_blocked_until_a_required_sealed_bag_is_intact_verified
    """
    estate, sale, _line, bag = _sealed_basket_awaiting_inspection(api, qty=3, allowance_units=5)

    validate_error(api.pickup_sale(sale["id"], SALES_ASSOCIATE_HEADERS), ERR_SEALED_BAG_REQUIRED)
    blocked = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert blocked["fulfillment_status"] == "ELIGIBILITY_CLEARED"
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 10

    verified = fx.verify_bag(api, bag["id"], "INTACT")
    assert verified["status"] == "INTACT_VERIFIED"
    assert_instant(verified["verified_at"], CLOCK_START, "verified_at")
    assert ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))["duty_status"] == "SUSPENDED"

    handed_over = fx.hand_over(api, sale["id"])
    assert_sale_dimensions(handed_over, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")
    assert handed_over["duty_liability_cents"] == 0
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["on_hand_qty"] == 7
    assert ok(api.get_agreement(estate.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 24000


def test_the_bag_requirement_needs_all_three_conditions_together(api):
    """A connecting liquid basket under a NONE regime and a connecting dry basket under
    ICAO_STEB both come out false and both hand over with no bag at all.

    PRD 3.5: "If any of the three fails — the terminal's regime is `NONE`, the journey is direct, or nothing in the basket is a liquid — `sealed_bag_required` is false and no bag is needed at handover."

    Design: Corner/validations/sealed_bag_requirement_applies_only_under_the_full_three_way_condition
    """
    unregulated = fx.liquor_estate(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", allowance_units=10)
    regulated = fx.liquor_estate(
        api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB", allowance_units=10
    )
    watch_brand = fx.register_brand(api, name="Meridian Timepieces", category="ELECTRONICS")
    watch = fx.listed_product(
        api,
        watch_brand["id"],
        sku="MER-WATCH-01",
        category="ELECTRONICS",
        unit_price_cents=20000,
        duty_rate_bps=0,
        vat_rate_bps=700,
    )
    fx.stocked_ledger(api, regulated.terminal["id"], watch["id"], 10)
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="ELECTRONICS",
        allowance_units=10,
        advisory_text="Australia: general goods allowance AUD 900 per adult.",
    )

    liquid_itinerary = fx.scanned_itinerary(api, unregulated.terminal["id"], **CONNECTING)
    liquid_sale = fx.open_basket(api, liquid_itinerary["id"])
    fx.append_line(api, liquid_sale["id"], unregulated.product["id"], 2)

    dry_itinerary = fx.scanned_itinerary(api, regulated.terminal["id"], **CONNECTING)
    dry_sale = fx.open_basket(api, dry_itinerary["id"])
    fx.append_line(api, dry_sale["id"], watch["id"], 1)

    assert fx.clear_basket(api, liquid_sale["id"])["sealed_bag_required"] is False
    assert fx.clear_basket(api, dry_sale["id"])["sealed_bag_required"] is False

    liquid_done = fx.hand_over(api, liquid_sale["id"])
    dry_done = fx.hand_over(api, dry_sale["id"])
    assert_sale_dimensions(liquid_done, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")
    assert_sale_dimensions(dry_done, fulfillment_status="PICKED_UP", duty_status="EXEMPT_CONFIRMED")

    bags, _ = page(api.list_sealed_bags(SALES_ASSOCIATE_HEADERS, {"sale_id": liquid_sale["id"]}))
    assert bags == []

    assert ok(api.get_agreement(unregulated.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 16000
    assert ok(api.get_agreement(regulated.agreement["id"], TERMINAL_ADMIN_HEADERS))["gross_sales_cents"] == 20000


def test_a_reused_boarding_pass_and_a_reused_seal_serial_are_both_refused(api):
    """Each aggregate answers with its own duplicate error and neither existing record moves.

    PRD 3.6: "A `SalesAssociate` issues one by naming the `sale_id` and the printed `seal_number`; the seal serial must be unique across all bags, and a repeat is refused with `ERR_DUPLICATE_SEAL_NUMBER`."

    Design: Corner/errors/duplicate_boarding_pass_and_seal_number_are_rejected_at_their_scoped_unique_keys
    """
    estate = fx.liquor_estate(
        api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB", allowance_units=5
    )
    first_itinerary = fx.scanned_itinerary(
        api, estate.terminal["id"], passenger_ref="PAX-0140", boarding_pass_barcode="BP-0140", **CONNECTING
    )
    first_sale = fx.open_basket(api, first_itinerary["id"])
    fx.append_line(api, first_sale["id"], estate.product["id"], 1)
    fx.clear_basket(api, first_sale["id"])

    second_itinerary = fx.scanned_itinerary(
        api, estate.terminal["id"], passenger_ref="PAX-0141", boarding_pass_barcode="BP-0141", **CONNECTING
    )
    second_sale = fx.open_basket(api, second_itinerary["id"])
    fx.append_line(api, second_sale["id"], estate.product["id"], 1)
    fx.clear_basket(api, second_sale["id"])

    validate_error(
        api.create_itinerary(
            f.itinerary_payload(
                estate.terminal["id"],
                passenger_ref="PAX-0142",
                nationality_code="JP",
                boarding_pass_barcode="BP-0140",
                departure_utc="2026-08-06T10:00:00Z",
                destination_country="NZ",
                final_destination_country="NZ",
            ),
            SALES_ASSOCIATE_HEADERS,
        ),
        ERR_DUPLICATE_BOARDING_PASS,
    )
    preserved = ok(api.get_itinerary(first_itinerary["id"], SALES_ASSOCIATE_HEADERS))
    assert preserved["passenger_ref"] == "PAX-0140"
    assert preserved["destination_country"] == "AU"

    first_bag = created(
        api.create_sealed_bag(f.sealed_bag_payload(first_sale["id"], "STEB-0100"), SALES_ASSOCIATE_HEADERS)
    )
    assert first_bag["seal_number"] == "STEB-0100"
    assert first_bag["status"] == "ISSUED"

    validate_error(
        api.create_sealed_bag(
            f.sealed_bag_payload(second_sale["id"], "STEB-0100"), SALES_ASSOCIATE_HEADERS
        ),
        ERR_DUPLICATE_SEAL_NUMBER,
    )
    assert ok(api.get_sealed_bag(first_bag["id"], SALES_ASSOCIATE_HEADERS))["sale_id"] == first_sale["id"]

    second_bag = created(
        api.create_sealed_bag(f.sealed_bag_payload(second_sale["id"], "STEB-0101"), SALES_ASSOCIATE_HEADERS)
    )
    assert second_bag["sale_id"] == second_sale["id"]

    bags, _ = page(api.list_sealed_bags(SALES_ASSOCIATE_HEADERS, {"terminal_id": estate.terminal["id"]}))
    assert sorted(ids_of(bags)) == sorted([first_bag["id"], second_bag["id"]])


def test_a_draft_audit_and_an_already_verified_bag_refuse_their_triggers(api):
    """The audit's own standing answers before segregation of duties or period closure, and a
    terminal bag refuses a second inspection without re-running the tamper cascade.

    PRD 3.6: "Either outcome requires the bag to still be in `ISSUED` standing — a bag already verified, tampered or voided is refused with `ERR_BAG_NOT_ISSUED`"

    Design: Corner/errors/audit_review_and_bag_verification_from_the_wrong_state_are_rejected
    """
    estate, sale, _line, bag = _sealed_basket_awaiting_inspection(api, qty=1, allowance_units=5)
    fx.verify_bag(api, bag["id"], "INTACT")

    audit = fx.open_audit(api, estate.terminal["id"], estate.stock_item["id"], "2026-08")
    assert audit["status"] == "DRAFT"

    validate_error(
        api.request_audit_info(
            audit["id"], f.audit_info_payload("Recount before I look at this."), CUSTOMS_AUDITOR_HEADERS
        ),
        ERR_AUDIT_NOT_SUBMITTED,
    )
    close_response = api.close_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS)
    validate_error(close_response, ERR_AUDIT_NOT_SUBMITTED)
    assert close_response.json()["data"]["error_id"] != ERR_AUDIT_PERIOD_NOT_CLOSED

    stored = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert stored["status"] == "DRAFT"
    assert stored["round_count"] == 1
    assert_nulls(stored, "info_request_note", "counted_qty", "expected_qty_snapshot")

    validate_error(
        api.verify_sealed_bag(bag["id"], f.verify_payload("TAMPERED"), SALES_ASSOCIATE_HEADERS),
        ERR_BAG_NOT_ISSUED,
    )
    unchanged = ok(api.get_sealed_bag(bag["id"], SALES_ASSOCIATE_HEADERS))
    assert unchanged["status"] == "INTACT_VERIFIED"
    assert_instant(unchanged["verified_at"], CLOCK_START, "verified_at")
    assert ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))["duty_status"] == "SUSPENDED"

"""Reservations: the buffered capacity check, the optimistic guard and the release paths."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ITINERARY_NOT_SCANNED,
    ERR_PREORDER_NOT_RESERVED,
    ERR_RESERVATION_CAPACITY_OVERLAP,
    ERR_RESERVATION_WINDOW_INVALID,
    ERR_STALE_STOCK_ITEM_VERSION,
)
from test_helpers.assertions import (
    assert_instant,
    assert_stock_quantities,
    created,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    make_passenger_headers,
)


def _ledger_with_a_six_unit_hold(api):
    """Ten bonded units with a RESERVED hold of six over the window [08-10, 08-12]."""
    estate = fx.liquor_estate(api, with_agreement=False)
    itinerary = fx.record_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T00:00:00Z")
    first = fx.place_reservation(
        api,
        itinerary["id"],
        estate.stock_item,
        6,
        reservation_window_start="2026-08-10T00:00:00Z",
        reservation_window_end="2026-08-12T00:00:00Z",
    )
    assert first["status"] == "RESERVED"
    return estate, itinerary, first


def test_a_window_that_only_the_buffer_makes_adjacent_is_still_a_conflict(api):
    """A start of 08-13 is disjoint from a window ending 08-12, but the 24-hour buffer pulls
    them together and the aggregate of 6 and 5 will not fit in ten units.

    PRD 3.8: "The conflicting reservations are those on the same bonded item that are still in `RESERVED` standing and whose window comes within one day of the requested one: precisely, those whose `reservation_window_start` is at or before the requested `reservation_window_end` advanced by 24 hours, and whose `reservation_window_end` is at or after the requested `reservation_window_start` set back by 24 hours."

    Design: Difficulty/resource_temporal_overlap/reservation_capacity_closed_windows_with_24h_buffer_aggregate_against_on_hand
    """
    estate, itinerary, _first = _ledger_with_a_six_unit_hold(api)

    held = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(held, on_hand=10, reserved=6, available=4)

    validate_error(
        api.create_pre_order(
            f.pre_order_payload(
                itinerary["id"],
                estate.stock_item["id"],
                5,
                held["version"],
                reservation_window_start="2026-08-13T00:00:00Z",
                reservation_window_end="2026-08-14T00:00:00Z",
            ),
            make_passenger_headers(itinerary["id"]),
        ),
        ERR_RESERVATION_CAPACITY_OVERLAP,
    )

    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["reserved_qty"] == 6


def test_a_window_beyond_the_buffer_may_fill_the_bonded_position_exactly(api):
    """A start of 08-14 sits one day clear of the incumbent, so its four units are judged on
    their own and take the reservations up to the ten units physically in bond.

    PRD 3.8: "The sum of the `qty` of those conflicting reservations plus the requested `qty` must not exceed the bonded item's `on_hand_qty`; note that the comparison is against units physically in bond, not against `available_qty`."

    Design: Difficulty/resource_temporal_overlap/reservation_capacity_closed_windows_with_24h_buffer_aggregate_against_on_hand
    """
    estate, itinerary, _first = _ledger_with_a_six_unit_hold(api)

    held = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    third = created(
        api.create_pre_order(
            f.pre_order_payload(
                itinerary["id"],
                estate.stock_item["id"],
                4,
                held["version"],
                reservation_window_start="2026-08-14T00:00:00Z",
                reservation_window_end="2026-08-15T00:00:00Z",
            ),
            make_passenger_headers(itinerary["id"]),
        )
    )
    assert third["status"] == "RESERVED"
    assert third["qty"] == 4

    full = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(full, on_hand=10, reserved=10, available=0)
    assert full["duty_suspended_value_cents"] == 19200

    holds, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "RESERVATION_HOLD"},
        )
    )
    assert [movement["qty_delta"] for movement in holds] == [6, 4]


def _hundred_unit_ledger_with_a_reservation(api):
    """A 100-unit ledger carrying one RESERVED hold of 25 units."""
    estate = fx.liquor_estate(api, receipt_qty=100, with_agreement=False)
    itinerary = fx.record_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T00:00:00Z")
    reservation = fx.place_reservation(api, itinerary["id"], estate.stock_item, 25)
    return estate, itinerary, reservation


def test_cancelling_a_reservation_returns_the_capacity_it_was_holding(api):
    """The release entry is appended against the reserved dimension only.

    PRD 3.8: "It moves the reservation `RESERVED → CANCELLED`, stamps `closed_at` with the logical clock, and appends a `RESERVATION_RELEASE` entry with a `qty_delta` of the negated `qty` and an `affects` of `RESERVED`, restoring `reserved_qty` to exactly its pre-reservation value and re-deriving `available_qty`."

    Design: Difficulty/compensating_invariant/preorder_cancellation_conserves_reserved_capacity_without_touching_on_hand
    """
    estate, itinerary, reservation = _hundred_unit_ledger_with_a_reservation(api)

    before = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(before, on_hand=100, reserved=25, available=75)
    assert before["duty_suspended_value_cents"] == 192000

    cancelled = fx.cancel_reservation(api, reservation["id"], itinerary["id"])
    assert cancelled["status"] == "CANCELLED"
    assert_instant(cancelled["closed_at"], CLOCK_START, "closed_at")

    releases, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "RESERVATION_RELEASE"},
        )
    )
    assert len(releases) == 1
    assert releases[0]["qty_delta"] == -25
    assert releases[0]["affects"] == "RESERVED"
    assert releases[0]["source_ref_type"] == "PRE_ORDER"
    assert releases[0]["source_ref_id"] == reservation["id"]


def test_the_duty_exposure_never_moved_and_the_cancellation_cannot_be_repeated(api):
    """`on_hand_qty` and the suspended duty value are functions of physical stock alone, so the
    whole reserve-then-cancel cycle leaves them untouched.

    PRD 3.8: "`CONVERTED`, `CANCELLED` and `RELEASED` are all terminal, and converting or cancelling a reservation in any of them is refused with `ERR_PREORDER_NOT_RESERVED`."

    Design: Difficulty/compensating_invariant/preorder_cancellation_conserves_reserved_capacity_without_touching_on_hand
    """
    estate, itinerary, reservation = _hundred_unit_ledger_with_a_reservation(api)

    fx.cancel_reservation(api, reservation["id"], itinerary["id"])

    restored = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(restored, on_hand=100, reserved=0, available=100)
    assert restored["duty_suspended_value_cents"] == 192000

    validate_error(
        api.cancel_pre_order(reservation["id"], make_passenger_headers(itinerary["id"])),
        ERR_PREORDER_NOT_RESERVED,
    )
    assert ok(api.get_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS))["status"] == "CANCELLED"

    movements, _ = page(
        api.list_movements(STOCK_CONTROLLER_HEADERS, {"stock_item_id": estate.stock_item["id"]})
    )
    assert len(movements) == 3


def test_conversion_needs_the_scan_and_the_window_together_before_it_builds_a_basket(api):
    """The itinerary's standing answers first, the collection window second, and only the third
    attempt produces a pre-order basket without issuing any stock.

    PRD 3.8: "It requires the reservation to be `RESERVED` (`ERR_PREORDER_NOT_RESERVED`), the traveller's itinerary to be verified with a `scan_status` of `SCANNED` or `AMENDED` (`ERR_ITINERARY_NOT_SCANNED`), the logical clock to fall inside the collection window with both bounds inclusive (`ERR_RESERVATION_WINDOW_INVALID`), the terminal to have a concession agreement in `ACTIVE` standing (`ERR_AGREEMENT_NOT_ACTIVE`) and the reserved product to still be `LISTED` (`ERR_PRODUCT_NOT_LISTED`)."

    Design: Corner/state_machines/preorder_conversion_requires_scan_window_agreement_and_listing_together
    """
    estate = fx.liquor_estate(api, allowance_units=5)
    itinerary = fx.record_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T00:00:00Z")
    reservation = fx.place_reservation(
        api,
        itinerary["id"],
        estate.stock_item,
        4,
        reservation_window_start="2026-08-10T00:00:00Z",
        reservation_window_end="2026-08-12T00:00:00Z",
    )

    validate_error(api.convert_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS), ERR_ITINERARY_NOT_SCANNED)

    fx.scan_itinerary(api, itinerary)

    validate_error(
        api.convert_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS), ERR_RESERVATION_WINDOW_INVALID
    )
    assert ok(api.get_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS))["status"] == "RESERVED"
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["reserved_qty"] == 4

    fx.advance_clock(api, "2026-08-11T00:00:00Z")

    converted = fx.convert_reservation(api, reservation["id"])
    assert converted["status"] == "CONVERTED"
    assert_instant(converted["closed_at"], "2026-08-11T00:00:00Z", "closed_at")
    assert converted["converted_sale_id"] is not None

    basket = ok(api.get_sale(converted["converted_sale_id"], SALES_ASSOCIATE_HEADERS))
    assert basket["channel"] == "PRE_ORDER"
    assert basket["fulfillment_status"] == "CART"
    assert basket["duty_status"] == "SUSPENDED"
    assert basket["terminal_id"] == estate.terminal["id"]
    assert basket["gross_amount_cents"] == 32000

    lines, _ = page(api.list_sale_lines(SALES_ASSOCIATE_HEADERS, {"sale_id": basket["id"]}))
    assert len(lines) == 1
    assert lines[0]["qty"] == 4
    assert lines[0]["unit_price_cents"] == 8000
    assert lines[0]["line_total_cents"] == 32000

    released = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(released, on_hand=10, reserved=0, available=10)

    releases, _ = page(
        api.list_movements(
            STOCK_CONTROLLER_HEADERS,
            {"stock_item_id": estate.stock_item["id"], "movement_type": "RESERVATION_RELEASE"},
        )
    )
    assert len(releases) == 1
    assert releases[0]["qty_delta"] == -4


def test_a_stale_stock_snapshot_reserves_nothing_and_a_fresh_one_reserves_once(api):
    """The reservation surface has no state gate to catch a stale client, so the optimistic
    guard is the only protection — and the accepted reservation makes its own quote stale.

    PRD 2.7: "`POST /pre-orders` requires a non-optional `expected_stock_item_version` field carrying the `version` of the target `BondedStockItem` as the client last observed it. If that value does not equal the stock item's current `version`, the reservation is rejected with `ERR_STALE_STOCK_ITEM_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_stock_item_version_on_pre_order_create_is_a_precondition_failure
    """
    estate = fx.liquor_estate(api, with_agreement=False)
    stale_version = estate.stock_item["version"]
    fx.post_receipt(api, estate.stock_item["id"], 5)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"])

    window = {
        "reservation_window_start": "2026-08-02T00:00:00Z",
        "reservation_window_end": "2026-08-20T09:00:00Z",
    }

    validate_error(
        api.create_pre_order(
            f.pre_order_payload(itinerary["id"], estate.stock_item["id"], 2, stale_version, **window),
            make_passenger_headers(itinerary["id"]),
        ),
        ERR_STALE_STOCK_ITEM_VERSION,
    )
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["reserved_qty"] == 0
    reservations, _ = page(
        api.list_pre_orders(STOCK_CONTROLLER_HEADERS, {"stock_item_id": estate.stock_item["id"]})
    )
    assert reservations == []

    fresh = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert fresh["version"] > stale_version

    accepted = created(
        api.create_pre_order(
            f.pre_order_payload(itinerary["id"], estate.stock_item["id"], 2, fresh["version"], **window),
            make_passenger_headers(itinerary["id"]),
        )
    )
    assert accepted["status"] == "RESERVED"
    assert_stock_quantities(
        ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS)),
        on_hand=15,
        reserved=2,
        available=13,
    )

    validate_error(
        api.create_pre_order(
            f.pre_order_payload(itinerary["id"], estate.stock_item["id"], 1, fresh["version"], **window),
            make_passenger_headers(itinerary["id"]),
        ),
        ERR_STALE_STOCK_ITEM_VERSION,
    )
    assert ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))["reserved_qty"] == 2

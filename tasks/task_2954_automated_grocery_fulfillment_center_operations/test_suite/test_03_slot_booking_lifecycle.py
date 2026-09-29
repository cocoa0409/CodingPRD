"""The life of one delivery-slot reservation, from the moment a shopper claims
capacity to the moment the van pulls away from the dock. A basket worth at least
ten dollars claims units on a slot serving the shopper's own home route and the
reservation is admitted onto one of two branches: it is HELD when the slot still
has free units, and it is parked on the waitlist when it asks for more than the
slot currently has free — parked reservations occupy no capacity at all, yet they
still freeze the surge multiplier of the moment into their quoted fee.
Confirming a HELD reservation is what actually slots the order: the units move
from held to confirmed on the slot's capacity ledger while the basket advances on
both of its status dimensions at once, and the amount authorised is snapshotted
so the delta against the final charge stays observable. A confirmation is a
one-shot event — a second attempt finds nothing to confirm, and once the delivery
window has opened the reservation can no longer be confirmed at all. Capacity put
back on sale drains the waitlist by exactly one shopper, never two. And at the
far end of the journey the wave is dispatched: the groceries leave, the money is
captured, and the basket is locked against any later cancellation.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_customer_order_shape,
    assert_delivery_wave_shape,
    assert_field_absent_or_null,
    assert_load_sequence,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_slot_booking_shape,
    assert_slot_ledger,
    assert_status,
    assert_surge_multiplier,
    assert_version_is,
    list_items_and_meta,
    read_object,
)
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    LineStatus,
    TemperatureZone,
    ToteStatus,
    WaveStatus,
)


def _standing_site(api, **slot_overrides):
    """One route, one ambient grid zone, one ambient SKU and one delivery slot.

    The route charges a 599-cent pre-surge delivery fee and 150 cents per
    kilometre; the SKU sells for 700 cents a unit; the slot opens far enough in
    the future that the boot clock leaves no lead-time premium at all.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
        unit_price_cents=700,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, **slot_overrides
    )
    return {"route": route, "zone": zone, "sku": sku, "slot": slot}


def test_confirming_a_held_booking_slots_the_order_and_authorizes_the_charge(
    api, make_customer_headers
):
    """Confirming a held reservation moves the booking, both order dimensions and
    the slot's capacity ledger in one request.

    Cites the requirement it rests on: "In the same request the order advances on
    both dimensions at once: `fulfillment_status` goes `DRAFT → SLOTTED` and
    `billing_status` goes `PENDING_AUTH → AUTHORIZED`, with
    `authorized_amount_cents` snapshotted from the order's `order_total_cents`,
    and the money dimension only advances if the waterfall has produced a
    non-null total."

    Design: Corner/state_machines/booking_confirm_slots_the_order_and_authorizes_the_charge
    """
    site = _standing_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    booking = fixtures.create_slot_booking(
        api,
        basket["account"]["id"],
        site["slot"]["id"],
        basket["order"]["id"],
        units=2,
    )
    assert_status(booking, BookingStatus.HELD.value)

    confirmed = read_object(api.confirm_slot_booking(booking["id"], shopper))

    assert_slot_booking_shape(confirmed)
    assert_status(confirmed, BookingStatus.CONFIRMED.value)

    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_customer_order_shape(order)
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )
    assert_field_absent_or_null(order, "captured_amount_cents")

    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=2,
        available_units=8,
    )


def test_confirming_a_booking_twice_is_rejected(api, make_customer_headers):
    """A confirmation is not repeatable: the second attempt finds the reservation
    already confirmed and neither charges the basket again nor books the units
    twice.

    Cites the requirement it rests on: "The target resource is in a state from
    which the requested transition exists, and every precondition of that
    transition that concerns the target resource itself holds — for instance a
    tote must be `OPEN` to be sealed, a retrieval task must be `RETRIEVING` to be
    completed, a wave must be `CONSOLIDATED` to be sequenced for loading, and a
    booking must be `HELD` to be confirmed. Violation: `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/booking_confirm_twice_returns_invalid_state
    """
    site = _standing_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    booking = fixtures.create_slot_booking(
        api,
        basket["account"]["id"],
        site["slot"]["id"],
        basket["order"]["id"],
        units=2,
    )
    fixtures.confirm_slot_booking(api, basket["account"]["id"], booking["id"])
    order_before = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )

    validate_error(
        api.confirm_slot_booking(booking["id"], shopper),
        ApiError.INVALID_STATE.value,
    )

    assert_status(
        fixtures.read_slot_booking(api, booking["id"]),
        BookingStatus.CONFIRMED.value,
    )
    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot, held_units=0, confirmed_units=2, available_units=8
    )
    order_after = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_version_is(order_after, order_before["version"])
    assert_order_money(order_after, authorized_amount_cents=1999)
    assert_order_statuses(
        order_after,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )


def test_confirming_a_booking_once_the_delivery_window_has_opened_is_rejected(
    api, make_customer_headers
):
    """The open-window test is applied again at confirmation time, so a
    reservation taken while the window was still ahead can no longer be confirmed
    once the clock has reached the window's opening instant.

    Cites the requirement it rests on: "The delivery slot's booking window is
    still open, meaning the clock is strictly earlier than the slot's
    `window_start`. Violation: `ERR_SLOT_WINDOW_CLOSED` (409). Applies to `POST
    /slot-bookings` and `POST /slot-bookings/{bookingId}/confirm`."

    Design: Corner/state_machines/booking_confirm_after_window_start_returns_slot_window_closed
    """
    site = _standing_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    booking = fixtures.create_slot_booking(
        api,
        basket["account"]["id"],
        site["slot"]["id"],
        basket["order"]["id"],
        units=2,
    )
    assert_status(booking, BookingStatus.HELD.value)
    fixtures.set_clock(api, site["slot"]["window_start"])

    validate_error(
        api.confirm_slot_booking(booking["id"], shopper),
        ApiError.SLOT_WINDOW_CLOSED.value,
    )

    assert_status(
        fixtures.read_slot_booking(api, booking["id"]), BookingStatus.HELD.value
    )
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_field_absent_or_null(order, "authorized_amount_cents")
    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot, held_units=2, confirmed_units=0, available_units=8
    )


def test_booking_a_slot_with_a_basket_below_the_ten_dollar_minimum_is_rejected(
    api, make_customer_headers
):
    """A single 700-cent item does not clear the ten-dollar minimum basket value,
    so no capacity is reserved for it at all.

    Cites the requirement it rests on: "The order meets the minimum basket value:
    its `merchandise_subtotal_cents` is at least ten dollars, that is 1,000
    cents, at the moment a slot booking is created. Violation:
    `ERR_MINIMUM_ORDER_NOT_MET` (422). Applies to `POST /slot-bookings`."

    Design: Corner/state_machines/slot_booking_below_minimum_order_returns_minimum_order_not_met
    """
    site = _standing_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=1
    )
    shopper = make_customer_headers(basket["account"]["id"])
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_money(order, merchandise_subtotal_cents=700)

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                site["slot"]["id"], order["id"], order["version"], units=2
            ),
            shopper,
        ),
        ApiError.MINIMUM_ORDER_NOT_MET.value,
    )

    order_after = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_money(order_after, merchandise_subtotal_cents=700)
    assert_field_absent_or_null(order_after, "delivery_fee_cents")
    assert_field_absent_or_null(order_after, "order_total_cents")
    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot, held_units=0, confirmed_units=0, available_units=10
    )
    items, meta = list_items_and_meta(
        api.list_slot_bookings(shopper, params={"customer_order_id": order["id"]})
    )
    assert items == [], f"no reservation should exist, found {items}"
    assert meta["total_count"] == 0, (
        f"expected no slot bookings for the basket, got {meta['total_count']}"
    )


def test_booking_more_units_than_the_slot_could_ever_sell_is_rejected(
    api, make_customer_headers
):
    """The bookable ceiling is the slot's capacity less what has been held back
    from sale, so a request above that ceiling is refused outright rather than
    waitlisted, while a request of exactly the ceiling is admitted.

    Cites the requirement it rests on: "And the requested `units` may not exceed
    the slot's `total_capacity_units` less its `withheld_units`, because such a
    booking could never be satisfied even from a completely empty slot; that
    refusal is `ERR_SLOT_UNITS_EXCEED_CAPACITY`."

    Design: Corner/state_machines/slot_booking_units_above_bookable_capacity_returns_slot_units_exceed_capacity
    """
    site = _standing_site(api, withheld_units=4)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                site["slot"]["id"], order["id"], order["version"], units=7
            ),
            shopper,
        ),
        ApiError.SLOT_UNITS_EXCEED_CAPACITY.value,
    )

    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=4,
        held_units=0,
        confirmed_units=0,
        available_units=6,
    )
    items, meta = list_items_and_meta(
        api.list_slot_bookings(
            shopper, params={"delivery_slot_id": site["slot"]["id"]}
        )
    )
    assert items == [], f"no reservation should exist, found {items}"
    assert meta["total_count"] == 0, (
        f"expected no slot bookings on the slot, got {meta['total_count']}"
    )

    admitted = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                site["slot"]["id"], order["id"], order["version"], units=6
            ),
            shopper,
        ),
        201,
    )
    assert_status(admitted, BookingStatus.HELD.value)
    slot_after = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot_after,
        withheld_units=4,
        held_units=6,
        confirmed_units=0,
        available_units=0,
    )


def test_booking_beyond_the_slots_free_units_joins_the_waitlist(
    api, make_customer_headers
):
    """Asking for more units than the slot currently has free is not an error: the
    reservation is parked on the waitlist, occupies no capacity, and still freezes
    the surge multiplier of the moment into its quoted fee.

    Cites the requirement it rests on: "If `available_units` is less than
    `units`, the booking is instead created in status `WAITLISTED`; it occupies no
    capacity at all, so `available_units` is unchanged, the order stays at
    `fulfillment_status` `DRAFT`, and the charge waterfall still runs — the
    waitlisted booking counts as the order's booking for the purposes of step 2,
    so the totals still become non-null."

    Design: Corner/state_machines/slot_booking_beyond_available_units_is_waitlisted_not_rejected
    """
    site = _standing_site(api)
    early = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    early_booking = fixtures.create_slot_booking(
        api, early["account"]["id"], site["slot"]["id"], early["order"]["id"], units=8
    )
    assert_status(early_booking, BookingStatus.HELD.value)

    late = fixtures.build_shopper_with_basket(
        api,
        site["route"]["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        stop_distance_km=7.00,
    )
    late_shopper = make_customer_headers(late["account"]["id"])
    late_order = fixtures.read_order(
        api, late["account"]["id"], late["order"]["id"]
    )

    waitlisted = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                site["slot"]["id"],
                late_order["id"],
                late_order["version"],
                units=5,
            ),
            late_shopper,
        ),
        201,
    )

    assert_slot_booking_shape(waitlisted)
    assert_status(waitlisted, BookingStatus.WAITLISTED.value)
    assert_ratio(waitlisted, "surge_multiplier_at_booking", 1.15, places=2)
    assert_money(waitlisted, "quoted_fee_cents", 689)
    assert_status(
        fixtures.read_slot_booking(api, early_booking["id"]),
        BookingStatus.HELD.value,
    )

    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=0,
        held_units=8,
        confirmed_units=0,
        available_units=2,
    )
    assert_surge_multiplier(slot, 1.15)

    parked_order = fixtures.read_order(
        api, late["account"]["id"], late["order"]["id"]
    )
    assert_order_statuses(
        parked_order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_order_money(
        parked_order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=689,
        loyalty_discount_cents=0,
        order_total_cents=2089,
    )


def test_a_second_live_booking_on_one_basket_is_rejected(api, make_customer_headers):
    """One basket may hold only one live reservation, so a second booking is
    refused even when it names a different delivery slot.

    Cites the requirement it rests on: "A shopper may hold at most one live
    booking per order, so an order that already has a booking in `HELD`,
    `CONFIRMED` or `WAITLISTED` is refused with `ERR_DUPLICATE_SLOT_BOOKING`."

    Design: Corner/state_machines/second_booking_on_the_same_order_returns_duplicate_slot_booking
    """
    site = _standing_site(api)
    later_slot = fixtures.create_delivery_slot(
        api,
        site["route"]["id"],
        total_capacity_units=10,
        window_start="2026-08-05T14:00:00.000Z",
        window_end="2026-08-05T16:00:00.000Z",
    )
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    first = fixtures.create_slot_booking(
        api,
        basket["account"]["id"],
        site["slot"]["id"],
        basket["order"]["id"],
        units=2,
    )
    assert_status(first, BookingStatus.HELD.value)
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                later_slot["id"], order["id"], order["version"], units=2
            ),
            shopper,
        ),
        ApiError.DUPLICATE_SLOT_BOOKING.value,
    )

    assert_status(
        fixtures.read_slot_booking(api, first["id"]), BookingStatus.HELD.value
    )
    untouched = fixtures.read_delivery_slot(api, later_slot["id"])
    assert_slot_ledger(
        untouched,
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=0,
        available_units=10,
    )
    items, meta = list_items_and_meta(
        api.list_slot_bookings(shopper, params={"customer_order_id": order["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the basket should hold exactly one reservation, got {meta['total_count']}"
    )
    assert [item["id"] for item in items] == [first["id"]]


def test_booking_a_slot_off_the_shoppers_home_route_is_rejected(
    api, make_customer_headers
):
    """A shopper may only reserve capacity on the route their account is bound to,
    however much room the foreign route's slot has.

    Cites the requirement it rests on: "The slot's route must be the shopper's
    home route, or the request is refused with `ERR_ROUTE_MISMATCH`."

    Design: Corner/state_machines/slot_booking_on_foreign_route_returns_route_mismatch
    """
    site = _standing_site(api)
    foreign_route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=499, per_km_cost_cents=120
    )
    foreign_slot = fixtures.create_delivery_slot(
        api, foreign_route["id"], total_capacity_units=10
    )
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = make_customer_headers(basket["account"]["id"])
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_money(order, merchandise_subtotal_cents=1400)

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                foreign_slot["id"], order["id"], order["version"], units=2
            ),
            shopper,
        ),
        ApiError.ROUTE_MISMATCH.value,
    )

    untouched = fixtures.read_delivery_slot(api, foreign_slot["id"])
    assert_slot_ledger(
        untouched,
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=0,
        available_units=10,
    )
    order_after = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_statuses(
        order_after,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_field_absent_or_null(order_after, "delivery_fee_cents")
    assert_field_absent_or_null(order_after, "order_total_cents")


def test_releasing_withheld_capacity_promotes_exactly_one_waitlisted_booking(
    api, make_customer_headers
):
    """Putting four held-back units back on sale frees room for both parked
    reservations, yet only the earliest-parked shopper is promoted and slotted;
    the later one stays on the waitlist.

    Cites the requirement it rests on: "The single winner is promoted to
    `CONFIRMED`, and then the selector stops: at most one promotion happens per
    request, the ledger is recomputed once more, and no second promotion is
    attempted even if further capacity remains."

    Design: Corner/state_machines/release_capacity_promotes_at_most_one_waitlisted_booking
    """
    site = _standing_site(api, withheld_units=8)
    holder = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    holder_booking = fixtures.create_slot_booking(
        api,
        holder["account"]["id"],
        site["slot"]["id"],
        holder["order"]["id"],
        units=2,
    )
    assert_status(holder_booking, BookingStatus.HELD.value)

    fixtures.set_clock(api, "2026-08-01T01:00:00.000Z")
    first_parked = fixtures.build_shopper_with_basket(
        api,
        site["route"]["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        stop_distance_km=6.00,
    )
    first_parked_booking = fixtures.create_slot_booking(
        api,
        first_parked["account"]["id"],
        site["slot"]["id"],
        first_parked["order"]["id"],
        units=2,
    )
    assert_status(first_parked_booking, BookingStatus.WAITLISTED.value)

    fixtures.set_clock(api, "2026-08-01T02:00:00.000Z")
    second_parked = fixtures.build_shopper_with_basket(
        api,
        site["route"]["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        stop_distance_km=7.00,
    )
    second_parked_booking = fixtures.create_slot_booking(
        api,
        second_parked["account"]["id"],
        site["slot"]["id"],
        second_parked["order"]["id"],
        units=2,
    )
    assert_status(second_parked_booking, BookingStatus.WAITLISTED.value)

    fixtures.release_capacity(api, site["slot"]["id"], 4)

    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=4,
        held_units=2,
        confirmed_units=2,
        available_units=2,
    )
    assert_surge_multiplier(slot, 1.15)

    assert_status(
        fixtures.read_slot_booking(api, holder_booking["id"]),
        BookingStatus.HELD.value,
    )
    assert_status(
        fixtures.read_slot_booking(api, first_parked_booking["id"]),
        BookingStatus.CONFIRMED.value,
    )
    assert_status(
        fixtures.read_slot_booking(api, second_parked_booking["id"]),
        BookingStatus.WAITLISTED.value,
    )

    promoted_order = fixtures.read_order(
        api, first_parked["account"]["id"], first_parked["order"]["id"]
    )
    assert_order_statuses(
        promoted_order,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        promoted_order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=809,
        order_total_cents=2209,
        authorized_amount_cents=2209,
    )

    passed_over_order = fixtures.read_order(
        api, second_parked["account"]["id"], second_parked["order"]["id"]
    )
    assert_order_statuses(
        passed_over_order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_field_absent_or_null(passed_over_order, "authorized_amount_cents")


def test_dispatching_captures_the_charge_and_locks_the_order_against_cancellation(
    api, make_customer_headers, wave_planner_headers, second_wave_planner_headers
):
    """Dispatch is the end of the line: the van leaves, the basket's money is
    captured, and the shopper can no longer cancel the order afterwards.

    Cites the requirement it rests on: "Every member order whose
    `fulfillment_status` is `LOADED` advances `LOADED → DISPATCHED`, and on the
    money dimension every such order moves to `CAPTURED` — from `AUTHORIZED →
    CAPTURED` if it was never adjusted and from `ADJUSTED → CAPTURED` if it was —
    with `captured_amount_cents` snapshotted from that order's
    `order_total_cents`."

    Design: Corner/state_machines/dispatch_captures_the_charge_then_locks_the_order_against_cancel
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150},
        station={"max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
        unit_price_cents=700,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    waved = fixtures.build_waved_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
        stop_distance_km=5.00,
    )
    shopper = make_customer_headers(waved["account"]["id"])
    fixtures.assign_dock(
        api,
        waved["wave"]["id"],
        plant["bay"]["id"],
        "2026-08-05T09:00:00.000Z",
        "2026-08-05T10:00:00.000Z",
    )
    fixtures.start_picking(api, waved["wave"]["id"])
    task = fixtures.pick_task_for_line(api, waved["lines"][0]["id"])
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        waved["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, driven["tote"]["id"])
    fixtures.consolidate_wave(api, waved["wave"]["id"], wave_planner_headers)
    fixtures.compute_loading_sequence(
        api, waved["wave"]["id"], wave_planner_headers
    )

    dispatched = read_object(
        api.dispatch_wave(waved["wave"]["id"], second_wave_planner_headers)
    )

    assert_delivery_wave_shape(dispatched)
    assert_status(dispatched, WaveStatus.DISPATCHED.value)
    assert_money(dispatched, "transport_cost_cents", 750)
    assert_load_sequence(dispatched, [driven["tote"]["id"]])
    assert_status(
        fixtures.read_tote(api, driven["tote"]["id"]), ToteStatus.LOADED.value
    )

    order = fixtures.read_order(api, waved["account"]["id"], waved["order"]["id"])
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DISPATCHED.value,
        billing_status=BillingStatus.CAPTURED.value,
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        order_total_cents=1999,
        authorized_amount_cents=1999,
        captured_amount_cents=1999,
    )
    line = fixtures.read_order_line(
        api, waved["account"]["id"], waved["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_money(line, "final_line_price_cents", 1400)

    validate_error(
        api.cancel_customer_order(waved["order"]["id"], shopper),
        ApiError.INVALID_STATE.value,
    )

    order_after = fixtures.read_order(
        api, waved["account"]["id"], waved["order"]["id"]
    )
    assert_order_statuses(
        order_after,
        fulfillment_status=FulfillmentStatus.DISPATCHED.value,
        billing_status=BillingStatus.CAPTURED.value,
    )
    assert_order_money(
        order_after,
        captured_amount_cents=1999,
        authorized_amount_cents=1999,
    )

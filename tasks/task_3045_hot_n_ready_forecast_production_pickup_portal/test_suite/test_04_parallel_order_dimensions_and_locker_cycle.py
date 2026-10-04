"""Parallel order state dimensions and the reusable locker-slot cycle."""

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    make_shift_lead_headers,
    validate_success,
)


def test_counter_order_prepares_unpaid_dimensions_evolve_independently(client):
    """A COUNTER order advances fulfillment to IN_PREPARATION while payment stays
    UNPAID, and accrues no portal fee.

    "A new order is born with `payment_status` `UNPAID` and `fulfillment_status`
    `PLACED` — two parallel dimensions that evolve independently."
    "the order must be `PAID` unless it is a `COUNTER` order (otherwise
    `ERR_ORDER_NOT_PAID`)"
    "`COUNTER` lines accrue no fee."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-09-14", "2026-09-14T11:00:00Z"
    )
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "walk-in-1",
                OrderKind.COUNTER,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_shift_lead_headers(),
        ),
        201,
    )
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "PLACED"

    prepared = validate_success(
        client.start_preparation(order["id"], make_crew_headers()), 200
    )
    assert prepared["fulfillment_status"] == "IN_PREPARATION"
    assert prepared["payment_status"] == "UNPAID", (
        "COUNTER orders may prepare unpaid — the dimensions evolve independently"
    )
    assert prepared["portal_fee_cents"] == 0

    stored = fixtures.read_order(client, order["id"])
    assert stored["fulfillment_status"] == "IN_PREPARATION"
    assert stored["payment_status"] == "UNPAID"


def test_counter_order_mark_ready_mints_no_code_and_still_unpaid(client):
    """A COUNTER order reaches READY with no locker and no code, still UNPAID.

    "A `COUNTER` order is simply stamped `ready_at` — no locker, no code."
    "two parallel dimensions that evolve independently."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-09-14", "2026-09-14T11:00:00Z"
    )
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "walk-in-1",
                OrderKind.COUNTER,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_shift_lead_headers(),
        ),
        201,
    )
    fixtures.start_preparation(client, order["id"])
    ready = validate_success(client.mark_ready(order["id"], make_crew_headers()), 200)
    assert ready["fulfillment_status"] == "READY"
    assert ready["payment_status"] == "UNPAID"
    assert ready.get("pickup_code") is None
    assert ready.get("locker_slot_id") is None


def test_locker_slot_cycle_reusable_after_cleaning(client):
    """The same physical slot hosts a second order after the full
    IDLE -> OCCUPIED -> CLEANING -> IDLE cycle.

    "From `OCCUPIED`, a slot moves to `CLEANING` — with `cleaning_started_at`
    stamped and `current_order_id` retained for audit — when its order is
    claimed"
    "Once the clock reaches `cleaning_started_at` plus 15 minutes, the slot
    returns to `IDLE` and its `current_order_id` is cleared."
    "The winner is deterministic — the `IDLE` slot with the lowest
    `slot_number`, with the slot's `id` never consulted"

    Design: Difficulty/non_linear_state_machine/locker_slot_idle_occupied_cleaning_idle_cycle_reusable
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-09-15", "2026-09-15T11:00:00Z"
    )
    slot = fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)

    # Order A: full pickup; the slot goes OCCUPIED then CLEANING on claim.
    order_a = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-a", product["id"]
    )
    assert order_a["locker_slot_id"] == slot["id"]
    slot_a = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_a["status"] == "OCCUPIED"
    fixtures.claim_order(client, order_a["id"], "cust-a", order_a["pickup_code"])
    slot_cleaning = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_cleaning["status"] == "CLEANING"

    # 11:30Z is past the 15-minute cleaning interval started at 11:00Z.
    fixtures.set_clock(client, "2026-09-15T11:30:00Z")
    slot_idle = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_idle["status"] == "IDLE", (
        "the slot must return to IDLE once the clock reaches cleaning_started_at + 15 minutes"
    )

    # Order B reuses the same physical slot.
    order_b = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-b", product["id"]
    )
    assert order_b["locker_slot_id"] == slot["id"], (
        "the lowest-slot_number IDLE slot is reused after the cycle"
    )
    slot_b = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_b["status"] == "OCCUPIED"
    assert slot_b["current_order_id"] == order_b["id"]


def test_slot_goes_cleaning_exactly_at_claim_and_recovers_after_interval(client):
    """Claim flips the slot to CLEANING immediately; it is still CLEANING one
    minute before the 15-minute mark and IDLE at it.

    "A successful claim moves the order to the terminal `PICKED_UP` state and
    sends its locker slot to `CLEANING`."
    "Once the clock reaches `cleaning_started_at` plus 15 minutes, the slot
    returns to `IDLE` and its `current_order_id` is cleared."

    Design: Difficulty/non_linear_state_machine/locker_slot_idle_occupied_cleaning_idle_cycle_reusable
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-09-15", "2026-09-15T11:00:00Z"
    )
    slot = fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-a", product["id"]
    )
    assert order["locker_slot_id"] == slot["id"]
    fixtures.claim_order(client, order["id"], "cust-a", order["pickup_code"])

    slot_cleaning = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_cleaning["status"] == "CLEANING"

    fixtures.set_clock(client, "2026-09-15T11:14:00Z")
    slot_before = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_before["status"] == "CLEANING"

    fixtures.set_clock(client, "2026-09-15T11:15:00Z")
    slot_after = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_after["status"] == "IDLE"
    assert slot_after.get("current_order_id") is None

"""Cross-entity state gates: order fulfillment gated by lot state, booking
gated by event state."""

from test_helpers import (
    ApiErrorId,
    brooder_verify,
    create_account,
    create_open_store,
    create_published_event,
    create_service_event_payload,
    make_customer_headers,
    post_care_log,
    set_clock,
    setup_reserved_order,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_fulfill_blocked_after_lot_closure_expires_order(api):
    """PRD §3.4: "an order that a cascade has already moved to `CANCELLED` or `EXPIRED` fails with `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.3: "Closing from `ON_SALE` — whether by explicit call or by schedule-closure or posture-flip cascade — expires every `RESERVED` or `BROODER_VERIFIED` chick order against the lot, releasing the reserved birds back to `quantity_on_hand`."

    Design: Difficulty/cross_entity_state_dependency/chick_fulfill_gated_by_lot_state
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    # Close the lot beneath the verified order.
    validate_success(api.close_lot_sale(ctx["lot"]["id"], {}, MGR))

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "EXPIRED"

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_on_hand"] == 100

    resp = api.fulfill_chick_order(ctx["order"]["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_fulfill_succeeds_while_lot_remains_on_sale(api):
    """PRD §3.4: "The lot must be `ON_SALE` at fulfill time (otherwise `ERR_LOT_NOT_ON_SALE`)."
    PRD §3.4: "A successful fulfillment stamps `fulfilled_at`, adds the order's quantity to the lot's `quantity_sold`, and leaves `quantity_on_hand` unchanged, because the reservation simply converts to a sale."

    Design: Difficulty/cross_entity_state_dependency/chick_fulfill_gated_by_lot_state
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    fulfilled = validate_success(api.fulfill_chick_order(ctx["order"]["id"], ASSOC))
    assert fulfilled["status"] == "FULFILLED"

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_sold"] == 6
    assert lot["quantity_on_hand"] == 94


def test_booking_rejected_while_event_is_draft(api):
    """PRD §3.9: "A `Customer` books a slot on a published event — booking against an event that is not `PUBLISHED` fails with `ERR_EVENT_NOT_PUBLISHED`"

    Design: Difficulty/cross_entity_state_dependency/booking_gated_by_service_event_state
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account()
    ev = validate_success(
        api.create_service_event(create_service_event_payload(store["id"]), MGR),
        expected_status=201,
    )
    assert ev["status"] == "DRAFT"

    resp = api.create_event_booking(
        {
            "service_event_id": ev["id"],
            "loyalty_account_id": account["id"],
            "slot_start": "2026-09-15T10:00:00Z",
        },
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED)


def test_booking_accepted_once_event_published_with_computed_slot_end(api):
    """PRD §3.9: "A `Customer` books a slot on a published event — booking against an event that is not `PUBLISHED` fails with `ERR_EVENT_NOT_PUBLISHED`"
    PRD §3.9: "the `slot_end` itself is computed as the start plus the event's slot length."
    PRD §3.9: "Publishing moves the event `DRAFT → PUBLISHED`"

    Design: Difficulty/cross_entity_state_dependency/booking_gated_by_service_event_state
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account()
    ev = validate_success(
        api.create_service_event(create_service_event_payload(store["id"]), MGR),
        expected_status=201,
    )
    validate_success(api.publish_service_event(ev["id"], MGR))

    booking = validate_success(
        api.create_event_booking(
            {
                "service_event_id": ev["id"],
                "loyalty_account_id": account["id"],
                "slot_start": "2026-09-15T10:00:00Z",
            },
            make_customer_headers(account["id"]),
        ),
        expected_status=201,
    )
    assert booking["status"] == "BOOKED"
    assert booking["slot_end"] == ts_iso("2026-09-15T10:30:00Z")

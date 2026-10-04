"""Service event and booking corners: idempotent check-in rejection, vaccine
gate, slot-grid shape, staging selector."""

from test_helpers import (
    ApiErrorId,
    create_account,
    create_booking,
    create_open_store,
    create_pickup_order,
    create_published_event,
    create_service_event_payload,
    create_staging_bay,
    create_store,
    make_customer_headers,
    set_clock,
    setup_ready_pickup,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_event_booking_double_checkin_rejected(api):
    """PRD §3.9: "On the day, an associate checks in a `BOOKED` booking within a window that opens 15 minutes before `slot_start` and closes at `slot_end`"
    PRD §2.9: "resource state preconditions at priority 7 (the campaign, schedule, lot, order, sale, account, and event state errors, plus the generic `ERR_INVALID_STATE_TRANSITION`, HTTP 409)."

    Design: Corner/state_machines/event_booking_double_checkin_idempotency_rejected
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    event = create_published_event(store)
    account = create_account()
    booking = create_booking(event, account, "2026-09-15T10:00:00Z")

    # Inside the check-in window (10 minutes before slot start).
    set_clock("2026-09-15T09:50:00Z")
    first = validate_success(api.check_in_booking(booking["id"], ASSOC))
    assert first["status"] == "CHECKED_IN"

    second = api.check_in_booking(booking["id"], ASSOC)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_vaccine_record_required_for_vet_clinic(api):
    """PRD §3.9: "the `slot_start`, and, when the event requires it, `vaccine_record_confirmed` set true (absent that confirmation on a requiring event, the booking fails with `ERR_VACCINE_RECORD_REQUIRED`)."

    Design: Corner/validations/vaccine_record_required_for_vet_clinic
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    event = create_published_event(
        store,
        event_kind="VET_CLINIC",
        resource_name="clinic-room",
        slot_window_start="2026-09-15T13:00:00Z",
        slot_window_end="2026-09-15T17:00:00Z",
        slot_length_minutes=45,
        cleanup_buffer_minutes=15,
        requires_vaccine_record=True,
    )
    account = create_account()

    missing = api.create_event_booking(
        {
            "service_event_id": event["id"],
            "loyalty_account_id": account["id"],
            "slot_start": "2026-09-15T13:00:00Z",
            "vaccine_record_confirmed": False,
        },
        make_customer_headers(account["id"]),
    )
    validate_error(missing, ApiErrorId.ERR_VACCINE_RECORD_REQUIRED)

    confirmed = validate_success(
        api.create_event_booking(
            {
                "service_event_id": event["id"],
                "loyalty_account_id": account["id"],
                "slot_start": "2026-09-15T13:00:00Z",
                "vaccine_record_confirmed": True,
            },
            make_customer_headers(account["id"]),
        ),
        expected_status=201,
    )
    assert confirmed["status"] == "BOOKED"


def test_booking_slot_end_beyond_window_rejected(api):
    """PRD §3.9: "The `slot_start` must fall on the `event_date`, must not precede `slot_window_start`, and the slot it opens must end no later than `slot_window_end`; the `slot_end` itself is computed as the start plus the event's slot length. Shape violations of these bounds are `ERR_INVALID_REQUEST`."

    Design: Corner/errors/booking_outside_slot_window_and_misaligned_grid
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    event = create_published_event(store)
    account = create_account()

    # On-grid start 11:45 with slot_end 12:15 exceeds the 12:00 window end.
    resp = api.create_event_booking(
        {
            "service_event_id": event["id"],
            "loyalty_account_id": account["id"],
            "slot_start": "2026-09-15T11:45:00Z",
        },
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_staging_bay_selector_smallest_sufficient_and_tiebreak(api):
    """PRD §3.8: "eligible bays are `AVAILABLE` and have a `size_class` large enough for the item, with capacity ordered `M` smaller than `L` smaller than `XL` — a bay holds anything its own size or smaller. Among eligible bays the smallest sufficient one wins, and ties break by ascending `bay_no`."

    Design: Corner/calculations/staging_bay_selector_smallest_sufficient_and_tiebreak
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    create_staging_bay(store, bay_no=1, size_class="XL")
    bay2 = create_staging_bay(store, bay_no=2, size_class="L")
    create_staging_bay(store, bay_no=3, size_class="L")
    bay4 = create_staging_bay(store, bay_no=4, size_class="M")
    account = create_account()

    po_l = create_pickup_order(
        store, account, item_sku="WELDER-250", item_size_class="L",
    )
    po_m = create_pickup_order(
        store, account, item_sku="TOOLBOX-52", item_size_class="M",
    )

    staged_l = validate_success(api.stage_pickup_order(po_l["id"], ASSOC))
    # Smallest sufficient for L is an L bay; bay_no 2 beats bay_no 3.
    assert staged_l["staging_bay_id"] == bay2["id"]

    staged_m = validate_success(api.stage_pickup_order(po_m["id"], ASSOC))
    # Exact fit: the M bay beats the free L bay.
    assert staged_m["staging_bay_id"] == bay4["id"]


def test_pickup_order_computed_bay_and_deadline(api):
    """PRD §3.8: "A successful stage records the chosen `staging_bay_id`, marks the bay `OCCUPIED`, and moves the order `PLACED → STAGED`."
    PRD §3.8: "A `StoreAssociate` marks a `STAGED` order ready, stamping `ready_at` with the logical now and computing the `pickup_deadline` as exactly 5 days later, moving the order `STAGED → READY_FOR_PICKUP`."

    Design: Corner/entities/pickup_order_computed_bay_and_deadline_ignore_client_input
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    bay = create_staging_bay(store, bay_no=3, size_class="M")
    account = create_account()

    order = create_pickup_order(
        store, account, item_sku="GENERATOR-9K", item_size_class="M",
        requires_loadout_assistance=False,
    )
    assert order["staging_bay_id"] is None

    staged = validate_success(api.stage_pickup_order(order["id"], ASSOC))
    assert staged["staging_bay_id"] == bay["id"]

    ready = validate_success(api.mark_pickup_ready(order["id"], ASSOC))
    assert ready["ready_at"] == ts_iso(FLOOR_NOW)
    assert ready["pickup_deadline"] == ts_iso("2026-09-15T09:00:00Z")


def test_staging_empty_pool_rejected_then_freed_by_cancel(api):
    """PRD §3.8: "An empty pool rejects the stage outright with `ERR_NO_STAGING_BAY_AVAILABLE`; there is no queuing."
    PRD §3.8: "cancelling a staged or ready order releases its bay to `AVAILABLE`."

    Design: Corner/endpoints/staging_empty_pool_rejected_then_freed_by_cancel
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    bay = create_staging_bay(store, bay_no=1, size_class="M")
    account = create_account()
    cust = make_customer_headers(account["id"])

    po1 = create_pickup_order(store, account, item_sku="TOOLBOX-52",
                              item_size_class="M")
    po2 = create_pickup_order(store, account, item_sku="GENERATOR-9K",
                              item_size_class="M")

    staged1 = validate_success(api.stage_pickup_order(po1["id"], ASSOC))
    assert staged1["staging_bay_id"] == bay["id"]
    bay_state = validate_success(api.get_staging_bay(bay["id"], MGR))
    assert bay_state["status"] == "OCCUPIED"

    resp = api.stage_pickup_order(po2["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_NO_STAGING_BAY_AVAILABLE)

    validate_success(api.cancel_pickup_order(po1["id"], cust))
    bay_released = validate_success(api.get_staging_bay(bay["id"], MGR))
    assert bay_released["status"] == "AVAILABLE"

    staged2 = validate_success(api.stage_pickup_order(po2["id"], ASSOC))
    assert staged2["staging_bay_id"] == bay["id"]


def test_pickup_complete_after_deadline_expires_order_and_releases_bay(api):
    """PRD §3.8: "if the logical now has passed the `pickup_deadline`, the order transitions to `EXPIRED`, its bay is released back to `AVAILABLE`, and the call fails with `ERR_PICKUP_WINDOW_EXPIRED`."

    Design: Corner/endpoints/pickup_complete_after_deadline_expires_order_and_releases_bay
    """
    ctx = setup_ready_pickup(
        clock=FLOOR_NOW, item_size_class="M", requires_loadout_assistance=False,
        item_sku="TOOLBOX-52",
    )
    order_id = ctx["order"]["id"]
    bay_id = ctx["order"]["staging_bay_id"]
    assert ctx["order"]["pickup_deadline"] == ts_iso("2026-09-15T09:00:00Z")

    # One second past the deadline.
    set_clock("2026-09-15T09:00:01Z")
    resp = api.complete_pickup_order(order_id, ASSOC)
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_EXPIRED)

    order = validate_success(api.get_pickup_order(order_id, ASSOC))
    assert order["fulfillment_status"] == "EXPIRED"

    bay = validate_success(api.get_staging_bay(bay_id, MGR))
    assert bay["status"] == "AVAILABLE"

"""Resource temporal overlap: pet-wash half-open capacity vs hatchery
sanitization gap."""

from test_helpers import (
    ApiErrorId,
    create_account,
    create_booking,
    create_hatchery_schedule_payload,
    create_open_store,
    create_published_event,
    make_customer_headers,
    set_clock,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def _setup_published_pet_wash(api, capacity=1):
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    event = create_published_event(store, capacity_per_slot=capacity)
    return store, event


def test_pet_wash_adjacent_slots_do_not_overlap(api):
    """PRD §3.9: "For a `PET_WASH`, slots are half-open intervals: a booking occupies from its start up to but not including its end, so a booking starting exactly when another ends does not overlap"

    Design: Difficulty/resource_temporal_overlap/pet_wash_half_open_adjacency_allowed_overlap_rejected
    """
    _store, event = _setup_published_pet_wash(api, capacity=1)
    account_a = create_account(full_name="Nan Booker")
    account_b = create_account(full_name="Otto Booker")

    bk1 = create_booking(event, account_a, "2026-09-15T10:00:00Z")
    assert bk1["status"] == "BOOKED"
    assert bk1["slot_end"] == ts_iso("2026-09-15T10:30:00Z")

    bk2 = create_booking(event, account_b, "2026-09-15T10:30:00Z")
    assert bk2["status"] == "BOOKED"


def test_pet_wash_staggered_overlap_exceeds_capacity(api):
    """PRD §3.9: "the candidate is rejected with `ERR_BOOKING_OVERLAP` only when the number of already-occupying bookings whose start precedes the candidate's end and whose end follows the candidate's start reaches the event's `capacity_per_slot`."

    Design: Difficulty/resource_temporal_overlap/pet_wash_half_open_adjacency_allowed_overlap_rejected
    """
    _store, event = _setup_published_pet_wash(api, capacity=1)
    account_a = create_account(full_name="Nan Booker")
    account_b = create_account(full_name="Otto Booker")

    create_booking(event, account_a, "2026-09-15T10:00:00Z")
    create_booking(event, account_b, "2026-09-15T10:30:00Z")

    # 10:15-10:45 overlaps both neighbors at capacity 1.
    resp = api.create_event_booking(
        {
            "service_event_id": event["id"],
            "loyalty_account_id": account_b["id"],
            "slot_start": "2026-09-15T10:15:00Z",
        },
        make_customer_headers(account_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP)


def test_hatchery_gap_under_seven_days_rejected(api):
    """PRD §3.2: "For the same store and the same `species`, the candidate's closed sale window must be separated from every other `PUBLISHED` schedule's closed window by a sanitization gap of at least 7 full days on both sides ... A violation rejects the publish with `ERR_SCHEDULE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/hatchery_window_seven_day_sanitization_gap
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")

    s1 = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"],
                sale_window_start="2026-03-01T00:00:00Z",
                sale_window_end="2026-03-31T23:59:59Z",
            ),
            MGR,
        ),
        expected_status=201,
    )
    validate_success(api.publish_hatchery_schedule(s1["id"], MGR))

    s2 = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"],
                breed="Barred Rock",
                hatch_date="2026-03-20T00:00:00Z",
                sale_window_start="2026-04-05T00:00:00Z",
                sale_window_end="2026-04-30T23:59:59Z",
            ),
            MGR,
        ),
        expected_status=201,
    )
    # Apr 5 start is only ~5 days after the Mar 31 end: under the 7-day gap.
    resp = api.publish_hatchery_schedule(s2["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP)


def test_hatchery_gap_exactly_seven_days_accepted(api):
    """PRD §3.2: "Exactly 7 days of gap is allowed."
    PRD §3.2: "either the candidate's `sale_window_start` falls at least 7 days after the other's `sale_window_end`, or the candidate's `sale_window_end` falls at least 7 days before the other's `sale_window_start`."

    Design: Difficulty/resource_temporal_overlap/hatchery_window_seven_day_sanitization_gap
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")

    s1 = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"],
                sale_window_start="2026-03-01T00:00:00Z",
                sale_window_end="2026-03-31T23:59:59Z",
            ),
            MGR,
        ),
        expected_status=201,
    )
    validate_success(api.publish_hatchery_schedule(s1["id"], MGR))

    s3 = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"],
                breed="Buff Orpington",
                hatch_date="2026-03-22T00:00:00Z",
                sale_window_start="2026-04-08T00:00:00Z",
                sale_window_end="2026-05-10T23:59:59Z",
                min_purchase_qty=4,
                base_price_cents_per_bird=429,
            ),
            MGR,
        ),
        expected_status=201,
    )
    published = validate_success(api.publish_hatchery_schedule(s3["id"], MGR))
    assert published["status"] == "PUBLISHED"

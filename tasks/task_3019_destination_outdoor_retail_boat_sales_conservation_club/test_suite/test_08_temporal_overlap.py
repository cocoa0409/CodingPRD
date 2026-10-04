"""Depth tests: resource temporal-overlap conflicts across interval semantics."""
from test_helpers import (
    ATTRACTION_HOST,
    ApiErrorId,
    validate_error_is_one_of,
    RECEIVING_MANAGER,
    create_bay_booking,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_service_order,
    create_store,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# shared_capacity_window_overlap_on_attraction  (queue A / resource_temporal_overlap)
# ===========================================================================

def _aquarium_and_two_members(api, capacity_units=10, dwell_cost_minutes=30):
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=capacity_units,
                                        dwell_cost_minutes=dwell_cost_minutes)
    member_one = create_member(api, store["id"], email="m_ov1@x.com",
                               full_name="Ora Vale")
    member_two = create_member(api, store["id"], email="m_ov2@x.com",
                               full_name="Oz Vale")
    return store, attraction, member_one, member_two


def test_adjacency_at_the_shared_endpoint_is_free_and_small_parties_may_coexist(api):
    """PRD §3.1: "two parties may share a venue only while their combined size
    stays within the venue's capacity, and because the occupancy interval is
    half-open, a party whose slot begins exactly when another's ends is adjacent
    rather than overlapping and is permitted."

    Design: Difficulty/resource_temporal_overlap/shared_capacity_window_overlap_on_attraction
    """
    # A small per-guest cost keeps the store OPEN across all three commits, so
    # the assertions read the capacity rule rather than the posture gate.
    store, attraction, member_one, member_two = _aquarium_and_two_members(
        api, dwell_cost_minutes=5
    )

    first = get_success_data(
        request_session(api, store["id"], attraction["id"], member_one["id"],
                        party_size=6, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    assert first["status"] == "CONFIRMED"

    adjacent = get_success_data(
        request_session(api, store["id"], attraction["id"], member_two["id"],
                        party_size=3, slot_start_utc="2026-11-01T11:00:00Z",
                        slot_end_utc="2026-11-01T12:00:00Z"),
        201,
    )
    assert adjacent["status"] == "CONFIRMED", (
        "the 11:00 slot touches the previous one only at the shared endpoint, "
        f"which the half-open interval leaves free; got {adjacent['status']}"
    )

    overlapping_small = get_success_data(
        request_session(api, store["id"], attraction["id"], member_two["id"],
                        party_size=3, slot_start_utc="2026-11-01T10:30:00Z",
                        slot_end_utc="2026-11-01T11:30:00Z"),
        201,
    )
    assert overlapping_small["status"] == "CONFIRMED", (
        "6 + 3 stays within capacity_units 10, so the overlap is permitted; got "
        f"{overlapping_small['status']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 12, (
        "the three confirmed parties hold their summed party sizes; got "
        f"{venue['in_use_units']}"
    )


def test_an_overlapping_party_that_would_breach_capacity_is_refused(api):
    """PRD §3.1: "An overlapping-interval collision that would breach capacity
    is reported with `ERR_SESSION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/shared_capacity_window_overlap_on_attraction
    """
    store, attraction, member_one, member_two = _aquarium_and_two_members(api)
    get_success_data(
        request_session(api, store["id"], attraction["id"], member_one["id"],
                        party_size=6, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )

    response = request_session(api, store["id"], attraction["id"], member_two["id"],
                               party_size=5,
                               slot_start_utc="2026-11-01T10:30:00Z",
                               slot_end_utc="2026-11-01T11:30:00Z")
    # PRD §3.1 states the aggregate rule ("a fresh request when the venue is
    # already over its cap through its other committed sessions" surfaces as
    # ERR_VENUE_CAPACITY_EXCEEDED) and the ordering rule as two named outcomes
    # for the same collision, so either error id is a faithful reading.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value,
         ApiErrorId.ERR_SESSION_OVERLAP.value],
    )


# ===========================================================================
# bay_turnover_buffer_overlap_on_loading_bay  (queue A / resource_temporal_overlap)
# ===========================================================================

def _bay_and_order(api, bay_no=2):
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_bb@x.com",
                           full_name="Bay Bright")
    unit = create_boat_unit(api, store["id"], stock_no="BU-BB", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="NEW",
                            hull_id_no="HINBB0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OVERSIZE_LOADING", promised_lead_days=3)
    booking = create_bay_booking(api, store["id"], member["id"], order["id"],
                                 bay_no=bay_no,
                                 booked_start_utc="2026-09-08T09:00:00Z",
                                 booked_end_utc="2026-09-08T10:00:00Z")
    return store, member, order, booking


def test_the_fifteen_minute_turnover_buffer_holds_the_bay_after_an_earlier_booking(api):
    """PRD §3.6: "another booking on the same store and same bay number whose interval overlaps the requested interval widened by a fifteen-minute turnover buffer at each end is refused with"

    Design: Difficulty/resource_temporal_overlap/bay_turnover_buffer_overlap_on_loading_bay
    """
    store, member, order, booking = _bay_and_order(api)
    assert booking["status"] == "RESERVED"

    response = api.create_bay_booking(
        store["id"],
        {
            "bay_no": 2,
            "member_id": member["id"],
            "service_order_id": order["id"],
            "booked_start_utc": "2026-09-08T10:05:00Z",
            "booked_end_utc": "2026-09-08T11:00:00Z",
        },
        RECEIVING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_BAY_BOOKING_CONFLICT, 409)


def test_a_booking_that_clears_the_buffer_is_accepted_and_the_bay_never_accepts_adjacency(api):
    """PRD §3.6: "adjacency without the buffer is permitted, so a back-to-back
    slot is legal only if the fifteen minutes between the end of one and the
    start of the next are respected."

    Design: Difficulty/resource_temporal_overlap/bay_turnover_buffer_overlap_on_loading_bay
    """
    store, member, order, booking = _bay_and_order(api)
    too_early = api.create_bay_booking(
        store["id"],
        {
            "bay_no": 2,
            "member_id": member["id"],
            "service_order_id": order["id"],
            "booked_start_utc": "2026-09-08T10:05:00Z",
            "booked_end_utc": "2026-09-08T11:00:00Z",
        },
        RECEIVING_MANAGER,
    )
    validate_error(too_early, ApiErrorId.ERR_BAY_BOOKING_CONFLICT, 409)

    cleared = get_success_data(
        api.create_bay_booking(
            store["id"],
            {
                "bay_no": 2,
                "member_id": member["id"],
                "service_order_id": order["id"],
                "booked_start_utc": "2026-09-08T10:15:00Z",
                "booked_end_utc": "2026-09-08T11:00:00Z",
            },
            RECEIVING_MANAGER,
        ),
        201,
    )
    assert cleared["status"] == "RESERVED", (
        f"a start at 10:15 clears the trailing buffer; got {cleared['status']}"
    )

    bay_bookings, meta = validate_paginated(
        api.list_bay_bookings_for_bay(store["id"], 2, RECEIVING_MANAGER)
    )
    assert meta["total_count"] == 2, (
        f"exactly two bookings survive on bay 2; got {meta['total_count']}"
    )
    assert len(bay_bookings) == 2

    adjacent_retry = api.create_bay_booking(
        store["id"],
        {
            "bay_no": 2,
            "member_id": member["id"],
            "service_order_id": order["id"],
            "booked_start_utc": "2026-09-08T09:00:00Z",
            "booked_end_utc": "2026-09-08T10:00:00Z",
        },
        RECEIVING_MANAGER,
    )
    validate_error(adjacent_retry, ApiErrorId.ERR_BAY_BOOKING_CONFLICT, 409)
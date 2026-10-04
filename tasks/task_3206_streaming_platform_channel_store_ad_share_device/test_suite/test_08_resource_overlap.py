"""Resource overlap tests: half-open placement windows on home-screen slots
and closed-plus-buffer lab-bench windows."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_active_campaign,
    create_placement_booking,
    create_manufacturer,
    create_device_model,
    book_lab,
    make_publisher_headers,
    make_manufacturer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def _setup_two_campaigns():
    publisher = create_publisher(legal_name="Ovl Pub")
    channel = create_published_channel(publisher)
    k1 = create_active_campaign(publisher, channel["id"])
    k2 = create_active_campaign(publisher, channel["id"])
    return publisher, k1, k2


def test_placement_overlap_rejected_while_held():
    """PRD §3.5: "Booking windows use half-open interval semantics: a
    conflict exists exactly when another booking on the same `slot_code` in
    `HELD` or `CONFIRMED` status satisfies both that the new start is strictly
    before the existing end and the new end is strictly after the existing
    start — and pure adjacency, where the new start equals an existing end or
    the new end equals an existing start, does not conflict. A conflicting
    booking is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/placement_half_open_overlap_rejected_on_home_screen_slot
    """
    publisher, k1, k2 = _setup_two_campaigns()
    create_placement_booking(
        k1["id"], publisher["id"], slot_code="HOME_ROW_4",
        window_start="2026-09-12T10:00:00Z",
        window_end="2026-09-12T12:00:00Z",
    )

    resp = api_client.create_placement_booking(
        {
            "campaign_id": k2["id"],
            "slot_code": "HOME_ROW_4",
            "window_start": "2026-09-12T11:00:00Z",
            "window_end": "2026-09-12T13:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, 409)


def test_placement_released_booking_never_blocks():
    """PRD §3.5: "`RELEASED` and `EXPIRED` bookings never block anything."

    Design: Difficulty/resource_temporal_overlap/placement_half_open_overlap_rejected_on_home_screen_slot
    """
    publisher, k1, k2 = _setup_two_campaigns()
    b1 = create_placement_booking(
        k1["id"], publisher["id"], slot_code="HOME_ROW_4",
        window_start="2026-09-12T10:00:00Z",
        window_end="2026-09-12T12:00:00Z",
    )
    get_success_data(api_client.release_placement_booking(b1["id"], ADOPS))

    resp = api_client.create_placement_booking(
        {
            "campaign_id": k2["id"],
            "slot_code": "HOME_ROW_4",
            "window_start": "2026-09-12T11:00:00Z",
            "window_end": "2026-09-12T13:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    probe = validate_success(resp, expected_status=201)
    assert probe["status"] == "HELD"
    assert get_success_data(
        api_client.get_placement_booking(b1["id"], ADMIN)
    )["status"] == "RELEASED"


def _setup_lab_bench_7():
    manufacturer = create_manufacturer(legal_name="Lab TV")
    m1 = create_device_model(
        manufacturer, model_code="L-1", recovery_policy="STRAIGHT_LINE",
    )
    m2 = create_device_model(
        manufacturer, model_code="L-2", recovery_policy="STRAIGHT_LINE",
    )
    book_lab(
        m1["id"], manufacturer["id"], bench_code="LAB_BENCH_7",
        window_start="2026-09-03T09:00:00Z",
        window_end="2026-09-03T17:00:00Z",
    )
    return manufacturer, m1, m2


def test_lab_bench_closed_interval_forbids_adjacency():
    """PRD §3.8: "Lab windows use closed-interval semantics — unlike
    placement bookings, both endpoints are inclusive, so a new window whose
    start exactly equals another's end does conflict — and for conflict
    purposes every window is buffered by 24 hours on each side: the effective
    window runs from 24 hours before `window_start` to 24 hours after
    `window_end`."

    Design: Difficulty/resource_temporal_overlap/lab_bench_closed_interval_with_buffer_blocks_adjacent_booking
    """
    manufacturer, m1, m2 = _setup_lab_bench_7()

    # Adjacent: new start == existing end. Under closed semantics this
    # conflicts even without the buffer.
    resp = api_client.create_lab_booking(
        m2["id"],
        {
            "bench_code": "LAB_BENCH_7",
            "window_start": "2026-09-03T17:00:00Z",
            "window_end": "2026-09-03T20:00:00Z",
        },
        make_manufacturer_headers(manufacturer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BENCH_OVERLAP, 409)


def test_lab_bench_buffer_blocks_and_exact_24h_passes():
    """PRD §3.8: "Lab windows use closed-interval semantics — unlike
    placement bookings, both endpoints are inclusive ... and for conflict
    purposes every window is buffered by 24 hours on each side: the effective
    window runs from 24 hours before `window_start` to 24 hours after
    `window_end`. A new booking whose buffered window intersects any `BOOKED`
    booking's buffered window on the same `bench_code` is rejected with
    `ERR_BENCH_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lab_bench_closed_interval_with_buffer_blocks_adjacent_booking
    """
    manufacturer, m1, m2 = _setup_lab_bench_7()

    # 23 hours after the prior end: inside the 24h post-buffer.
    resp = api_client.create_lab_booking(
        m2["id"],
        {
            "bench_code": "LAB_BENCH_7",
            "window_start": "2026-09-04T16:00:00Z",
            "window_end": "2026-09-04T18:00:00Z",
        },
        make_manufacturer_headers(manufacturer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BENCH_OVERLAP, 409)

    # Exactly 24 hours after the prior end: the buffered windows touch.
    # Lab windows are closed intervals with inclusive endpoints, so a touch
    # is an intersection and this conflicts.
    resp = api_client.create_lab_booking(
        m2["id"],
        {
            "bench_code": "LAB_BENCH_7",
            "window_start": "2026-09-04T17:00:00Z",
            "window_end": "2026-09-04T20:00:00Z",
        },
        make_manufacturer_headers(manufacturer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BENCH_OVERLAP, 409)

    # 49 hours after the prior end: the new booking's own 24h pre-buffer
    # still does not reach the prior booking's 24h post-buffer, so the
    # buffered windows do not intersect.
    resp = api_client.create_lab_booking(
        m2["id"],
        {
            "bench_code": "LAB_BENCH_7",
            "window_start": "2026-09-05T18:00:00Z",
            "window_end": "2026-09-05T20:00:00Z",
        },
        make_manufacturer_headers(manufacturer["id"]),
    )
    booking = validate_success(resp, expected_status=201)
    assert booking["status"] == "BOOKED"
    model_state = get_success_data(api_client.get_device_model(m2["id"], ADMIN))
    assert model_state["cert_status"] == "LAB_TESTING"

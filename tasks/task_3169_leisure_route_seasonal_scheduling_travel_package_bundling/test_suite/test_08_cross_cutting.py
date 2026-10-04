"""Corner queue B — cross_cutting_layers and consistency_model sections.

Covers instances:
- cross_cutting_layers / cross_cutting_occ_stale_booking_create
- cross_cutting_layers / cross_cutting_occ_stale_publication_create
- cross_cutting_layers / cross_cutting_clock_default_is_fixed
- consistency_model / booking_creation_immediately_reflects_in_flight_and_list
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_publication,
    setup_published_pipeline,
    setup_route_with_open_window,
    validate_error,
    validate_paginated,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_occ_stale_booking_create_rejected(api):
    """PRD §2.9: "Creating a booking requires `expected_flight_version`, the
    client-observed value of the target flight's `version`." and "In each
    case the supplied value must equal the parent entity's current `version`
    at the moment the write is attempted; if another writer has advanced the
    entity's version since the client last read it, the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/cross_cutting_occ_stale_booking_create
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]
    stale_version = flight["version"]

    first = validate_success(
        api.create_booking(
            {
                "flight_instance_id": flight["id"],
                "passenger_count": 1,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": stale_version,
            },
            CS,
        ),
        expected_status=201,
    )
    assert first["booking_status"] == "CONFIRMED"

    # The first booking advanced the flight's version; reusing the stale
    # version is rejected.
    resp = api.create_booking(
        {
            "flight_instance_id": flight["id"],
            "passenger_count": 1,
            "booking_kind": "AIR_ONLY",
            "expected_flight_version": stale_version,
        },
        CS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_publication_create_rejected(api):
    """PRD §3.2: "Because publication is a concurrency-sensitive write on the
    window, the publication request must also carry `expected_window_version`
    equal to the window's current `version`; if the window's version has
    advanced since the planner last observed it — for instance because
    another planner has just suspended or re-opened it — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)." and "The act of publishing
    mutates the window as well, incrementing the window's `version` by one"

    Design: Corner/cross_cutting_layers/cross_cutting_occ_stale_publication_create
    """
    ctx = setup_route_with_open_window(weekly_frequency_cap=4)
    route_id = ctx["route"]["id"]
    window = ctx["window"]
    stale_window_version = window["version"]

    # A first successful publication bumps the window's version by one.
    create_publication(route_id, window)
    from test_helpers import get_fresh_window

    bumped = get_fresh_window(route_id, window["id"])
    assert bumped["version"] == stale_window_version + 1

    # Reusing the pre-bump version is stale.
    resp = api.create_publication(
        route_id,
        {
            "season_window_id": window["id"],
            "operating_days_mask": [5],
            "first_operating_date": "2027-03-05",
            "last_operating_date": "2027-03-05",
            "departure_time_local": "12:30",
            "block_minutes": 240,
            "expected_window_version": stale_window_version,
        },
        NP,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_clock_default_is_fixed(api):
    """PRD §2.4: "Before any client call, the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and it never silently falls back to wall-clock
    time thereafter." and PRD §3.2: "the number of whole days between the
    logical clock's current date and `first_operating_date` must be at least
    180 days, and a shorter lead time is rejected with
    `ERR_PUBLISH_HORIZON_VIOLATION`. A first operating date exactly 180 days
    ahead is allowed — only a strictly smaller lead time rejects."

    Design: Corner/cross_cutting_layers/cross_cutting_clock_default_is_fixed
    """
    # NOTE: the clock is NEVER set in this test — the default instant must be
    # exactly 2026-09-01T00:00:00Z. 2027-03-01 is 181 days ahead of that
    # default, so the publish satisfies the 180-day horizon without any
    # clock call.
    from test_helpers import (
        activate_route,
        create_route,
        create_window,
        setup_station_pair,
    )

    pair = setup_station_pair()
    route = create_route(pair["origin"]["id"], pair["destination"]["id"])
    window = create_window(route["id"])
    activate_route(route["id"])

    publication = create_publication(route["id"], window)
    assert publication["publication_status"] == "PUBLISHED"


def test_booking_creation_immediately_reflects_in_flight_and_list(api):
    """PRD §3.5: "Creating the booking increments the flight's `seats_sold` by
    the passenger count and increments the flight's `version` by one." and
    PRD §3.5: "A new booking's `booking_status` begins at `CONFIRMED`"

    Design: Corner/consistency_model/booking_creation_immediately_reflects_in_flight_and_list
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]

    booking = validate_success(
        api.create_booking(
            {
                "flight_instance_id": flight["id"],
                "passenger_count": 2,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": flight["version"],
            },
            CS,
        ),
        expected_status=201,
    )

    # Immediate consistency: the seat consumption is visible on re-read.
    from test_helpers import get_flight

    assert get_flight(flight["id"])["seats_sold"] == 2

    data, meta = validate_paginated(
        api.list_bookings(
            CS,
            params={
                "flight_instance_id": flight["id"],
                "booking_status": "CONFIRMED",
            },
        )
    )
    assert len(data) == 1
    assert data[0]["id"] == booking["id"]

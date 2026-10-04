"""Half-open interval semantics (queue A, rule `resource_temporal_overlap`).

Both the station's own broadcast schedule and a shared feed's reservation book
treat their intervals as half-open, so touching instants are adjacent and only a
genuine overlap is refused.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_agreement,
    create_online_feed,
    create_program,
    create_slot,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    set_clock,
    validate_error,
)

WINDOW_STATION = dict(
    call_sign="WUWM", licensee_name="Lakeshore Licensee", state_code="WI",
    dma_market_rank=36, dma_households=850000, coverage_population=85000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)

FEED_STATION = dict(
    call_sign="KUNM", licensee_name="High Desert Licensee", state_code="NM",
    dma_market_rank=70, dma_households=420000, coverage_population=65000,
    full_time_staff_count=5, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)


def setup_agreement_with_first_window():
    """An agreement carrying one 14:00-15:00 window on the station."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**WINDOW_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1007", program_title="Great Lakes Report")
    agreement = create_agreement(station, program_code=program["program_code"])
    first = create_window(agreement, station,
                          window_start="2026-10-05T14:00:00Z",
                          window_end="2026-10-05T15:00:00Z")
    return {"station": station, "headers": headers, "program": program,
            "agreement": agreement, "first": first}


def test_window_starting_at_the_prior_end_instant_is_admitted():
    """PRD §3.3: "The interval is half-open: the start instant is inside the window
    and the end instant is the first instant outside it, so two windows that touch
    at exactly one instant are adjacent and do not overlap."
    PRD §3.3: "touching intervals are permitted".

    Design: Difficulty/resource_temporal_overlap/overlap_touching_boundary_adjacent_windows
    """
    ctx = setup_agreement_with_first_window()
    resp = api_client.create_window(
        {"parent_agreement_id": ctx["agreement"]["id"], "station_id": ctx["station"]["id"],
         "program_code": ctx["agreement"]["program_code"],
         "window_start": "2026-10-05T15:00:00Z",
         "window_end": "2026-10-05T16:00:00Z"},
        ctx["headers"])
    data = get_success_data(resp, 201)

    # PRD §2.4: a stored instant is ISO 8601 UTC with three fractional digits,
    # so the half-open boundary is echoed at millisecond precision.
    assert data["window_start"] == "2026-10-05T15:00:00.000Z", (
        f"the adjacent window should carry its own start, got {data['window_start']}"
    )


def test_window_overlapping_by_one_second_is_refused():
    """PRD §3.3: "no sibling window under the same agreement on the same station
    may overlap the requested interval — touching intervals are permitted, genuine
    overlap fails with `ERR_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/overlap_touching_boundary_adjacent_windows
    """
    ctx = setup_agreement_with_first_window()
    resp = api_client.create_window(
        {"parent_agreement_id": ctx["agreement"]["id"], "station_id": ctx["station"]["id"],
         "program_code": ctx["agreement"]["program_code"],
         "window_start": "2026-10-05T14:59:59Z",
         "window_end": "2026-10-05T16:00:00Z"},
        ctx["headers"])

    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def setup_feed_with_first_slot():
    """An ONLINE feed holding one 09:00-12:00 reservation."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**FEED_STATION)
    headers = make_station_manager_headers(station["id"])
    feed = create_online_feed(feed_code="FEED-B002", feed_type="DIGITAL",
                              total_capacity_units=10)
    program = create_program(program_code="NP-1008", program_title="Desert Voices",
                             strand_type="CULTURE")
    agreement = create_agreement(station, program_code=program["program_code"],
                                 obligation_type="OPTIONAL")
    window = create_window(agreement, station,
                           window_start="2026-10-06T09:00:00Z",
                           window_end="2026-10-06T12:00:00Z")
    slot = create_slot(feed, station, window,
                       slot_start="2026-10-06T09:00:00Z",
                       slot_end="2026-10-06T12:00:00Z", priority_rank=3)
    return {"station": station, "headers": headers, "feed": feed,
            "agreement": agreement, "window": window, "slot": slot}


def _second_window_for_slot(ctx, window_start, window_end):
    """A sibling window for the feed fixture's agreement and station.

    PRD §3.4: the slot's own station must match the station named by its window,
    so the sibling window is created on the same agreement and station.
    """
    return create_window(ctx["agreement"], ctx["station"],
                         window_start=window_start, window_end=window_end)


def test_slot_starting_at_the_prior_end_instant_is_admitted():
    """PRD §3.4: "No sibling slot on the same feed may overlap the requested
    interval — touching intervals are adjacent and permitted, genuine overlap
    fails with `ERR_UPLINK_CAPACITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_adjacent_capacity_units_on_feed
    """
    ctx = setup_feed_with_first_slot()
    second_window = _second_window_for_slot(
        ctx, "2026-10-06T12:00:00Z", "2026-10-06T13:00:00Z")
    resp = api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": second_window["id"],
         "slot_start": "2026-10-06T12:00:00Z",
         "slot_end": "2026-10-06T13:00:00Z", "priority_rank": 3},
        ctx["headers"])
    data = get_success_data(resp, 201)

    assert data["slot_status"] == "RESERVED", (
        f"an adjacent reservation should be admitted, got {data['slot_status']}"
    )


def test_slot_overlapping_the_prior_reservation_is_refused():
    """PRD §3.4: "No sibling slot on the same feed may overlap the requested
    interval — touching intervals are adjacent and permitted, genuine overlap
    fails with `ERR_UPLINK_CAPACITY_CONFLICT`."

    PRD §3.3 makes the sibling-window check a window-level rule, so the second
    window is placed adjacent to the first (08:00-09:00 against 09:00-12:00) and
    it is the slot interval that genuinely overlaps the prior reservation.

    Design: Difficulty/resource_temporal_overlap/overlap_adjacent_capacity_units_on_feed
    """
    ctx = setup_feed_with_first_slot()
    second_window = _second_window_for_slot(
        ctx, "2026-10-06T08:00:00Z", "2026-10-06T09:00:00Z")
    resp = api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": second_window["id"],
         "slot_start": "2026-10-06T08:59:59Z",
         "slot_end": "2026-10-06T10:00:00Z", "priority_rank": 3},
        ctx["headers"])

    validate_error(resp, ApiErrorId.ERR_UPLINK_CAPACITY_CONFLICT)
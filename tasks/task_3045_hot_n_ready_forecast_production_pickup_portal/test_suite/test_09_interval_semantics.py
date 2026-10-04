"""Two interval semantics: half-open crew shifts vs closed demand-event windows."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    factories,
    make_manager_headers,
    make_shift_lead_headers,
    validate_error,
    validate_success,
)


def test_back_to_back_crew_shifts_allowed_overlap_rejected(client):
    """Half-open [start, end): start == existing end is permitted; one minute of
    real overlap is rejected.

    "Two conflict rules guard assignment, both evaluated under the half-open
    minute semantics of §2.7, and a violation of either is rejected with
    `ERR_SHIFT_CONFLICT`. First, the same crew member may not be double-booked:
    the candidate conflicts with any existing `SCHEDULED` shift of the same
    `crew_member_id` when the candidate's start is strictly before the existing
    shift's end and the existing shift's start is strictly before the
    candidate's end — back-to-back shifts, where the candidate starts at the
    exact minute the other ends, do not conflict and are permitted."

    Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_overlap_back_to_back_allowed
    """
    sd = fixtures.create_store_day(client, "2026-09-24")
    lead = make_shift_lead_headers()
    first = validate_success(
        client.create_crew_shift(
            sd["id"],
            factories.crew_shift_payload(
                crew_member_id="crew-9", station="OVEN", start_minute=600, end_minute=780
            ),
            lead,
        ),
        201,
    )
    assert first["status"] == "SCHEDULED"

    # Back-to-back: starts at the exact minute the other ends -> permitted.
    second = validate_success(
        client.create_crew_shift(
            sd["id"],
            factories.crew_shift_payload(
                crew_member_id="crew-9", station="CUT_TABLE",
                start_minute=780, end_minute=900,
            ),
            lead,
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"

    # One minute of real overlap with [780, 900) -> conflict.
    resp = client.create_crew_shift(
        sd["id"],
        factories.crew_shift_payload(
            crew_member_id="crew-9", station="LOCKER_BAY",
            start_minute=899, end_minute=960,
        ),
        lead,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_CONFLICT)


def test_one_minute_short_of_adjacency_conflicts(client):
    """start == existing.end - 1 shares one minute under half-open semantics.

    "the candidate conflicts with any existing `SCHEDULED` shift of the same
    `crew_member_id` when the candidate's start is strictly before the existing
    shift's end and the existing shift's start is strictly before the
    candidate's end"

    Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_overlap_back_to_back_allowed
    """
    sd = fixtures.create_store_day(client, "2026-09-24")
    lead = make_shift_lead_headers()
    validate_success(
        client.create_crew_shift(
            sd["id"],
            factories.crew_shift_payload(
                crew_member_id="crew-9", station="OVEN", start_minute=600, end_minute=780
            ),
            lead,
        ),
        201,
    )

    resp = client.create_crew_shift(
        sd["id"],
        factories.crew_shift_payload(
            crew_member_id="crew-9", station="CUT_TABLE",
            start_minute=779, end_minute=900,
        ),
        lead,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_CONFLICT)


def test_adjacent_demand_events_intersect_under_closed_semantics(client):
    """An event starting exactly at another's window_end_at shares the boundary
    instant and is rejected — the opposite treatment from crew shifts.

    "A new event is rejected with `ERR_EVENT_WINDOW_OVERLAP` when any other
    non-cancelled event of the same store day intersects its window under
    closed-interval semantics — and because the semantics are closed, two events
    that merely touch, one's `window_end_at` landing exactly on the other's
    `window_start_at`, do intersect and are rejected."

    Design: Difficulty/resource_temporal_overlap/demand_event_closed_interval_adjacency_is_overlap
    """
    sd = fixtures.create_store_day(client, "2026-09-25")
    manager = make_manager_headers()
    first = fixtures.create_demand_event(
        client,
        sd["id"],
        name="Lunch Rush",
        window_start_at="2026-09-25T12:00:00Z",
        window_end_at="2026-09-25T14:00:00Z",
        demand_multiplier=1.5,
    )
    assert first["status"] == "SCHEDULED"

    resp = client.create_demand_event(
        sd["id"],
        factories.demand_event_payload(
            name="Adjacent Rally",
            window_start_at="2026-09-25T14:00:00Z",
            window_end_at="2026-09-25T16:00:00Z",
            demand_multiplier=2.0,
        ),
        manager,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)

    stored = validate_success(client.get_demand_event(first["id"], manager), 200)
    assert stored["status"] == "SCHEDULED"


def test_truly_disjoint_demand_events_are_accepted(client):
    """Leave a gap between the windows and both events stand — the closed rule
    rejects only genuine intersection.

    "A new event is rejected with `ERR_EVENT_WINDOW_OVERLAP` when any other
    non-cancelled event of the same store day intersects its window under
    closed-interval semantics"

    Design: Difficulty/resource_temporal_overlap/demand_event_closed_interval_adjacency_is_overlap
    """
    sd = fixtures.create_store_day(client, "2026-09-25")
    manager = make_manager_headers()
    fixtures.create_demand_event(
        client,
        sd["id"],
        name="Lunch Rush",
        window_start_at="2026-09-25T12:00:00Z",
        window_end_at="2026-09-25T14:00:00Z",
        demand_multiplier=1.5,
    )

    second = validate_success(
        client.create_demand_event(
            sd["id"],
            factories.demand_event_payload(
                name="Late Rally",
                window_start_at="2026-09-25T14:01:00Z",
                window_end_at="2026-09-25T16:00:00Z",
                demand_multiplier=2.0,
            ),
            manager,
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"

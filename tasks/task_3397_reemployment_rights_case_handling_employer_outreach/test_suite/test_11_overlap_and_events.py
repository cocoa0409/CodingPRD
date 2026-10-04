"""Temporal overlap and outreach events: half-open service-period intervals
with adjacency and ongoing-period infinity, closed-interval venue booking
with the 60-minute teardown buffer, and the event conclude gate."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_outreach_event,
    assert_service_period,
    create_employer,
    create_event,
    create_member,
    create_service_period,
    event_payload,
    event_state_payload,
    make_service_member_headers,
    set_clock,
    transition_event,
    validate_error,
    validate_success,
)


def _setup_member_two_employers(api: ApiClient) -> dict:
    set_clock(api)
    employer = create_employer(api)
    other = create_employer(api, legal_name="Riverstone Clinics", sector="HEALTHCARE", size_tier="MEDIUM")
    member = create_member(api, full_name="Mel Ames", email="mel@example.com",
                           branch="AIR_FORCE", component="AIR_GUARD")
    first = create_service_period(api, member["id"], employer["id"],
                                  start_date="2026-01-01T00:00:00Z", end_date="2026-03-01T00:00:00Z",
                                  orders_type="ACTIVE_DUTY")
    return {"employer": employer, "other": other, "member": member, "first": first}


def test_service_periods_half_open_adjacency_allows_end_equals_start(api: ApiClient):
    """PRD §3.2: "One member's periods may not overlap, across all employers. Each period occupies the half-open interval from its `start_date` up to but not including its `end_date`; two periods of the same member — regardless of which employer each names — whose intervals intersect are rejected with `ERR_SERVICE_PERIOD_OVERLAP` (HTTP 422). Adjacency is not overlap: one period ending on exactly the day another begins is permitted."

    Design: Difficulty/resource_temporal_overlap/member_service_periods_half_open_adjacency
    """
    world = _setup_member_two_employers(api)
    member_id = world["member"]["id"]

    adjacent = api.create_service_period(
        {
            "member_id": member_id,
            "employer_id": world["other"]["id"],
            "start_date": "2026-03-01T00:00:00Z",
            "end_date": "2026-05-01T00:00:00Z",
            "orders_type": "DRILL",
        },
        make_service_member_headers(member_id),
    )
    adjacent_period = validate_success(adjacent, 201)
    assert_service_period(adjacent_period)

    overlapping = api.create_service_period(
        {
            "member_id": member_id,
            "employer_id": world["other"]["id"],
            "start_date": "2026-02-28T00:00:00Z",
            "end_date": "2026-04-01T00:00:00Z",
            "orders_type": "DRILL",
        },
        make_service_member_headers(member_id),
    )
    validate_error(overlapping, ApiErrorId.ERR_SERVICE_PERIOD_OVERLAP)
    assert overlapping.status_code == 422


def test_service_periods_ongoing_period_extends_to_infinity(api: ApiClient, coordinator_headers: dict):
    """PRD §3.2: "An ongoing period, having no end, is treated as extending indefinitely, so it collides with anything that starts after it."
    PRD §3.2: "a null `end_date` marks an ongoing period"

    Design: Difficulty/resource_temporal_overlap/member_service_periods_half_open_adjacency
    """
    world = _setup_member_two_employers(api)
    member_id = world["member"]["id"]
    create_service_period(api, member_id, world["other"]["id"],
                          start_date="2026-03-01T00:00:00Z", end_date="2026-05-01T00:00:00Z",
                          orders_type="DRILL")

    ongoing = api.create_service_period(
        {
            "member_id": member_id,
            "employer_id": world["employer"]["id"],
            "start_date": "2026-06-01T00:00:00Z",
            "orders_type": "ANNUAL_TRAINING",
        },
        make_service_member_headers(member_id),
    )
    ongoing_period = validate_success(ongoing, 201)
    assert ongoing_period["end_date"] is None and ongoing_period["duration_days"] is None

    after_ongoing = api.create_service_period(
        {
            "member_id": member_id,
            "employer_id": world["other"]["id"],
            "start_date": "2026-07-01T00:00:00Z",
            "end_date": "2026-08-01T00:00:00Z",
            "orders_type": "DRILL",
        },
        make_service_member_headers(member_id),
    )
    validate_error(after_ongoing, ApiErrorId.ERR_SERVICE_PERIOD_OVERLAP)

    periods = validate_success(api.list_member_service_periods(member_id, coordinator_headers))
    assert len(periods) == 3, "the two rejected periods persisted nothing"


def test_venue_buffer_rejects_start_inside_teardown_window(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "Venues cannot be double-booked: an event whose venue matches another event's is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 422) when their intervals overlap, where each event occupies a closed interval that includes its full running time plus a 60-minute teardown buffer after it — so unlike adjacent service periods, two events that merely touch count as overlapping — and `CANCELLED` events are excluded from the comparison set."

    Design: Difficulty/resource_temporal_overlap/venue_booking_closed_interval_with_buffer
    """
    set_clock(api)
    create_event(api, title="Employer Briefing A", venue="Hall-A",
                 starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T12:00:00Z",
                 topic="RIGHTS_OVERVIEW")

    inside_buffer = api.create_event(
        event_payload(title="Briefing B too soon", venue="Hall-A",
                      starts_at="2026-10-10T12:30:00Z", ends_at="2026-10-10T13:30:00Z",
                      topic="BENEFITS_BRIEFING"),
        coordinator_headers,
    )
    validate_error(inside_buffer, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED)
    assert inside_buffer.status_code == 422, \
        "a 12:30 start falls inside the 60-minute teardown buffer after the 12:00 end"

    clear_of_buffer = api.create_event(
        event_payload(title="Briefing C clear of the buffer", venue="Hall-A",
                      starts_at="2026-10-10T13:00:01Z", ends_at="2026-10-10T14:00:01Z",
                      topic="BENEFITS_BRIEFING"),
        coordinator_headers,
    )
    created = validate_success(clear_of_buffer, 201)
    assert_outreach_event(created)
    assert created["status"] == "PLANNED"


def test_venue_buffer_scoped_per_venue_and_excludes_cancelled(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "an event whose venue matches another event's is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 422) when their intervals overlap"
    PRD §3.9: "Either a planned or an open event may be cancelled into `CANCELLED`, which removes it from the venue overlap set."

    Design: Difficulty/resource_temporal_overlap/venue_booking_closed_interval_with_buffer
    """
    set_clock(api)
    event_a = create_event(api, title="Employer Briefing A", venue="Hall-A",
                           starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T12:00:00Z",
                           topic="RIGHTS_OVERVIEW")

    other_venue = api.create_event(
        event_payload(title="Briefing D other venue", venue="Hall-B",
                      starts_at="2026-10-10T11:00:00Z", ends_at="2026-10-10T12:00:00Z",
                      topic="HIRING_FAIR"),
        coordinator_headers,
    )
    assert_outreach_event(validate_success(other_venue, 201))

    cancelled = transition_event(api, event_a["id"], "CANCELLED")
    assert cancelled["status"] == "CANCELLED"

    reused = api.create_event(
        event_payload(title="Briefing E reuses cancelled slot", venue="Hall-A",
                      starts_at="2026-10-10T10:30:00Z", ends_at="2026-10-10T11:30:00Z",
                      topic="EMPLOYER_RECOGNITION"),
        coordinator_headers,
    )
    reused_event = validate_success(reused, 201)
    assert reused_event["status"] == "PLANNED", \
        "the cancelled event no longer participates in the venue overlap set"


def test_event_conclude_before_ends_at_returns_invalid_state(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "A planned event opens from `PLANNED` into `OPEN`, and an event in `OPEN` concludes into `CONCLUDED` only once the logical clock has reached its `ends_at`; concluding earlier fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/event_conclude_before_ends_at_returns_invalid_state
    """
    set_clock(api)
    event = create_event(api, title="Rights Briefing", venue="Hall-C",
                         starts_at="2026-10-10T10:00:00Z", ends_at="2026-10-10T12:00:00Z",
                         topic="RIGHTS_OVERVIEW")
    transition_event(api, event["id"], "OPEN")

    early = api.transition_event(event["id"], event_state_payload("CONCLUDED"), coordinator_headers)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    assert early.status_code == 409

    set_clock(api, "2026-10-10T12:00:00Z")
    concluded = api.transition_event(event["id"], event_state_payload("CONCLUDED"), coordinator_headers)
    assert validate_success(concluded)["status"] == "CONCLUDED", \
        "at clock exactly == ends_at the conclude succeeds"

"""The three calendar rules that gate approval: daily tier slots, pairwise
half-open occupancy, and buffered aggregate event-space capacity."""
from test_helpers import (
    approve_application,
    approve_application_raw,
    create_application,
    current_store_version,
    get_application,
    setup_release_context,
    validate_error,
)


def test_a_second_qualifier_on_the_same_calendar_day_breaks_the_slot_capacity(api):
    """PRD §3.3: "The daily tier-slot rule asks whether the store already holds at
    least its `daily_event_capacity` worth of applications counted together across
    `SUBMITTED` and `APPROVED` whose tier is `QUALIFIER` or `CHAMPIONSHIP`, whose
    `scheduled_date` falls on the same UTC calendar day as this application's own;
    any two events sharing that calendar day collide once the store's capacity is
    reached, and the rejection is `ERR_TIER_SLOT_CONFLICT`."

    Design: Corner/errors/tier_slot_conflict_beyond_daily_capacity
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=1, event_space_capacity=4
    )

    first = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=30,
    )
    approve_application(first["id"], store["id"])

    second = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date="2026-09-26T09:00:00Z", expected_headcount=30,
    )
    refused = approve_application_raw(
        second["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_TIER_SLOT_CONFLICT", expected_status=422)
    assert get_application(second["id"])["status"] == "SUBMITTED"


def test_a_local_event_never_consumes_a_store_daily_competitive_slot(api):
    """PRD §3.2: "Capacity governs only the two competitive rungs: a `LOCAL` event
    never consumes a store's daily competitive slot."
    PRD §3.3: "The daily tier-slot rule asks whether the store already holds at
    least its `daily_event_capacity` worth of applications counted together across
    `SUBMITTED` and `APPROVED` whose tier is `QUALIFIER` or `CHAMPIONSHIP`, whose
    `scheduled_date` falls on the same UTC calendar day as this application's own;
    any two events sharing that calendar day collide once the store's capacity is
    reached, and the rejection is `ERR_TIER_SLOT_CONFLICT`."

    Design: Corner/errors/tier_slot_conflict_beyond_daily_capacity
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=1, event_space_capacity=4
    )

    competitive = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date="2026-09-26T09:00:00Z", expected_headcount=30,
    )
    approve_application(competitive["id"], store["id"])

    # A LOCAL event on the same UTC calendar day but outside the first event's
    # occupancy window: it consumes no competitive slot and overlaps nothing.
    local = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approved = approve_application(local["id"], store["id"])
    assert approved["status"] == "APPROVED"
    assert approved["prize_allocation_id"] is not None


def test_buffered_padded_windows_collide_where_raw_windows_merely_touch(api):
    """PRD §3.3: "The event-space rule asks whether any single instant in the
    store's event space would be covered by more than `event_space_capacity`
    buffered occupancy intervals drawn from the store's non-terminal
    applications, where each interval runs from thirty minutes before the event's
    `scheduled_date` to thirty minutes after an event-length window of six hours
    that starts at the `scheduled_date`; the rejection is
    `ERR_EVENT_SPACE_CAPACITY`."
    PRD §3.3: "Note the deliberate asymmetry between the last two rules: a pair of
    events that is legal under the pairwise rule can still be illegal under the
    buffered aggregate rule, because the padding added on either side makes the
    two occupancies cover an instant in common."

    Design: Difficulty/resource_temporal_overlap/event_space_capacity_aggregate_with_buffer
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=8, event_space_capacity=1
    )

    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approve_application(first["id"], store["id"])

    second = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T00:00:00Z", expected_headcount=12,
    )
    refused = approve_application_raw(
        second["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_EVENT_SPACE_CAPACITY", expected_status=422)
    assert get_application(second["id"])["status"] == "SUBMITTED"


def test_padded_windows_that_share_no_instant_stay_under_the_capacity(api):
    """PRD §3.3: "The event-space rule asks whether any single instant in the
    store's event space would be covered by more than `event_space_capacity`
    buffered occupancy intervals drawn from the store's non-terminal
    applications, where each interval runs from thirty minutes before the event's
    `scheduled_date` to thirty minutes after an event-length window of six hours
    that starts at the `scheduled_date`; the rejection is
    `ERR_EVENT_SPACE_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/event_space_capacity_aggregate_with_buffer
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=8, event_space_capacity=1
    )

    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T09:00:00Z", expected_headcount=12,
    )
    approve_application(first["id"], store["id"])

    # Padded 08:30-15:30 versus padded 19:30-02:30: no instant is covered twice.
    second = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T20:00:00Z", expected_headcount=12,
    )
    approved = approve_application(second["id"], store["id"])
    assert approved["status"] == "APPROVED"


def test_a_window_that_touches_the_previous_one_is_accepted(api):
    """PRD §3.3: "The pairwise rule asks whether another non-terminal application
    of the same store has an occupancy window running from its `scheduled_date`
    for six hours that overlaps this application's own window, where the windows
    are half-open, so a prior event that ends at exactly the instant this one is
    scheduled to begin does not overlap and the pair is legal; the rejection is
    `ERR_EVENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pairwise_half_open_boundary_is_legal
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=8, event_space_capacity=4
    )
    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approve_application(first["id"], store["id"])

    touching = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T00:00:00Z", expected_headcount=12,
    )
    approved = approve_application(touching["id"], store["id"])
    assert approved["status"] == "APPROVED", (
        "the half-open windows [18:00, 24:00) and [00:00, 06:00) share no instant"
    )


def test_a_one_minute_inward_shift_is_refused_as_an_overlap(api):
    """PRD §3.3: "The pairwise rule asks whether another non-terminal application
    of the same store has an occupancy window running from its `scheduled_date`
    for six hours that overlaps this application's own window, where the windows
    are half-open, so a prior event that ends at exactly the instant this one is
    scheduled to begin does not overlap and the pair is legal; the rejection is
    `ERR_EVENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pairwise_half_open_boundary_is_legal
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=8, event_space_capacity=4
    )
    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    approve_application(first["id"], store["id"])

    touching = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T00:00:00Z", expected_headcount=12,
    )
    approve_application(touching["id"], store["id"])

    shifted = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T00:01:00Z", expected_headcount=12,
    )
    refused = approve_application_raw(
        shifted["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_EVENT_WINDOW_OVERLAP", expected_status=422)
    assert get_application(shifted["id"])["status"] == "SUBMITTED"
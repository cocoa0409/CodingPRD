"""Two temporal-overlap rules with different geometry: the buffered half-open
chamber occupancy interval and the unbuffered closed permit dwell interval."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_chamber,
    create_cycle,
    create_cycle_payload,
    operator,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def _gamma_chamber_with_buffer():
    env = setup_reference_data(chamber_overrides={"turnaround_minutes": 60}, qualify=False)
    env["cycle_a"] = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        cycle_code="C-A",
        scheduled_start_at="2026-08-11T00:00:00Z",
        scheduled_end_at="2026-08-11T06:00:00Z",
    )
    return env


def test_turnaround_buffer_extends_the_chamber_occupancy_interval():
    """PRD 3.4: "At creation the server derives `occupancy_end_at` as
    `scheduled_end_at` advanced by the chamber's `turnaround_minutes`, which is
    the outer edge of the chamber's occupancy."
    PRD 3.4: "**The chamber rule** is pairwise and exclusive: the new cycle's
    occupancy interval runs from `scheduled_start_at` up to but not including
    `occupancy_end_at`, and the request is refused with
    `ERR_CHAMBER_WINDOW_CONFLICT` if any other cycle in the same chamber whose
    `status` is none of `CANCELLED`, `DOSE_CONFORMING` or `DOSE_DEVIATION` has
    an occupancy interval that intersects it — that is, when the new cycle's
    start is strictly earlier than that cycle's occupancy end and that cycle's
    start is strictly earlier than the new cycle's occupancy end."

    Design: Difficulty/resource_temporal_overlap/chamber_occupancy_half_open_with_turnaround_buffer
    """
    env = _gamma_chamber_with_buffer()
    assert_instant_equals(
        env["cycle_a"]["occupancy_end_at"], "2026-08-11T07:00:00Z", "occupancy_end_at"
    )

    response = api_client.create_cycle(
        create_cycle_payload(
            env["chamber"]["id"],
            env["recipe"]["id"],
            cycle_code="C-B",
            scheduled_start_at="2026-08-11T06:30:00Z",
            scheduled_end_at="2026-08-11T12:30:00Z",
        ),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_CHAMBER_WINDOW_CONFLICT)


def test_a_cycle_beginning_on_the_occupancy_edge_is_accepted():
    """PRD 3.4: "Touching endpoints do not collide: a cycle beginning exactly
    at the instant another cycle's occupancy ends is accepted."

    Design: Difficulty/resource_temporal_overlap/chamber_occupancy_half_open_with_turnaround_buffer
    """
    env = _gamma_chamber_with_buffer()

    response = api_client.create_cycle(
        create_cycle_payload(
            env["chamber"]["id"],
            env["recipe"]["id"],
            cycle_code="C-C",
            scheduled_start_at="2026-08-11T07:00:00Z",
            scheduled_end_at="2026-08-11T13:00:00Z",
        ),
        operator(),
    )

    created = validate_success(response, 201)
    assert_instant_equals(
        created["occupancy_end_at"], "2026-08-11T14:00:00Z", "occupancy_end_at"
    )
    _, meta = validate_paginated(
        api_client.list_cycles(operator(), params={"chamber_id": env["chamber"]["id"]})
    )
    assert meta["total_count"] == 2


def _two_eto_chambers_under_a_single_slot_permit():
    env = setup_reference_data(
        modality="ETO",
        permit_overrides={"max_concurrent_eto_cycles": 1},
        chamber_overrides={"turnaround_minutes": 0},
        qualify=False,
    )
    env["chamber_b"] = create_chamber(
        env["permit"]["id"], "ETO", chamber_code="CH-E2", turnaround_minutes=0
    )
    env["cycle_a"] = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        cycle_code="C-A",
        scheduled_start_at="2026-08-11T00:00:00Z",
        scheduled_end_at="2026-08-11T06:00:00Z",
        raw_eto_charge_kg=100.0,
    )
    return env


def test_permit_concurrency_counts_dwells_that_merely_touch():
    """PRD 3.4: "**The permit rule** is aggregate, unbuffered and closed at
    both ends, and applies only when the chamber's `modality` is `ETO`. The
    server counts the cycles whose chamber sits under the same permit, whose
    chamber `modality` is also `ETO`, whose `status` is none of `CANCELLED`,
    `DOSE_CONFORMING` or `DOSE_DEVIATION`, and whose dwell interval from
    `scheduled_start_at` to `scheduled_end_at` inclusive touches or overlaps
    the new cycle's dwell interval — the new cycle's start at or before the
    other's end, and the other's start at or before the new cycle's end, so
    that merely touching dwells do count as concurrent. If that count is
    already equal to or greater than the permit's `max_concurrent_eto_cycles`,
    the request is refused with `ERR_PERMIT_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/permit_eto_concurrency_closed_interval_aggregate_cap
    """
    env = _two_eto_chambers_under_a_single_slot_permit()

    response = api_client.create_cycle(
        create_cycle_payload(
            env["chamber_b"]["id"],
            env["recipe"]["id"],
            cycle_code="C-B",
            scheduled_start_at="2026-08-11T06:00:00Z",
            scheduled_end_at="2026-08-11T12:00:00Z",
            raw_eto_charge_kg=100.0,
        ),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_PERMIT_CONCURRENCY_EXCEEDED)


def test_permit_concurrency_releases_one_second_after_the_dwell_ends():
    """PRD 3.4: "**The permit rule** is aggregate, unbuffered and closed at
    both ends, and applies only when the chamber's `modality` is `ETO`. The
    server counts the cycles whose chamber sits under the same permit, whose
    chamber `modality` is also `ETO`, whose `status` is none of `CANCELLED`,
    `DOSE_CONFORMING` or `DOSE_DEVIATION`, and whose dwell interval from
    `scheduled_start_at` to `scheduled_end_at` inclusive touches or overlaps
    the new cycle's dwell interval — the new cycle's start at or before the
    other's end, and the other's start at or before the new cycle's end, so
    that merely touching dwells do count as concurrent. If that count is
    already equal to or greater than the permit's `max_concurrent_eto_cycles`,
    the request is refused with `ERR_PERMIT_CONCURRENCY_EXCEEDED`."
    PRD 2.5: "**Instants** used in scheduling overlap tests are compared to the
    second."

    Design: Difficulty/resource_temporal_overlap/permit_eto_concurrency_closed_interval_aggregate_cap
    """
    env = _two_eto_chambers_under_a_single_slot_permit()

    response = api_client.create_cycle(
        create_cycle_payload(
            env["chamber_b"]["id"],
            env["recipe"]["id"],
            cycle_code="C-C",
            scheduled_start_at="2026-08-11T06:00:01Z",
            scheduled_end_at="2026-08-11T12:00:00Z",
            raw_eto_charge_kg=100.0,
        ),
        operator(),
    )

    created = validate_success(response, 201)
    assert_instant_equals(
        created["occupancy_end_at"], "2026-08-11T12:00:00Z", "occupancy_end_at"
    )
    _, meta = validate_paginated(
        api_client.list_cycles(operator(), params={"chamber_id": env["chamber_b"]["id"]})
    )
    assert meta["total_count"] == 1

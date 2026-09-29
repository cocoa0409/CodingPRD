"""Occupied intervals: the closed floater interval, the buffered window and the calendar bucket."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals
from test_helpers.test_users import UNDERWRITER


def site_holding_one_autumn_floater(api):
    """A surveyed TIER_2 site whose single PENDING floater runs to the first of December."""
    ctx = fixtures.build_installation_file(
        api, jobsite_controls=factories.SURVEY_TIER_2,
        floater_kwargs=dict(coverage_start_date="2026-09-01",
                            coverage_end_date="2026-12-01",
                            installed_value_limit_cents=20000000,
                            project_name="Tower A fit-out"))
    return ctx


def floaters_on_the_site(api, ctx):
    """Every floater the jobsite listing reports, with its pagination envelope."""
    return validate_paginated(api.list_installation_floaters(
        UNDERWRITER, limit=50, offset=0, jobsite_id=ctx.jobsite_id))


def test_a_floater_starting_on_the_day_the_last_one_ends_collides(api):
    """One shared endpoint is an intersection, because both intervals are closed.

    PRD: The coverage interval is closed at both ends: the first covered day is `coverage_start_date` and the last covered day is `coverage_end_date`.
    PRD: Second, a jobsite may carry at most one live floater at a time: the new floater's closed interval must not intersect the closed interval of any floater on the same jobsite whose status is `PENDING` or `ACTIVE`, and a single shared endpoint counts as an intersection, so a floater ending on a given day and another beginning on that same day collide.
    Design: Difficulty/resource_temporal_overlap/jobsite_floater_closed_interval_adjacency_collides
    """
    ctx = site_holding_one_autumn_floater(api)
    assert ctx.floater["status"] == "PENDING"
    assert ctx.floater["term_days"] == 92
    assert ctx.floater["rated_premium_cents"] == 70575

    refused = api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Tower B fit-out",
            installed_value_limit_cents=15000000,
            coverage_start_date="2026-12-01", coverage_end_date="2027-03-01"),
        UNDERWRITER)

    validate_error(refused, "ERR_JOBSITE_FLOATER_OVERLAP", 409)
    rows, meta = floaters_on_the_site(api, ctx)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx.floater_id


def test_a_floater_starting_the_next_day_is_accepted_and_priced_on_its_own_term(api):
    """Moving the start one day clear frees the site and shortens the term by one day.

    PRD: `term_days` counts both endpoints: take the whole days from `coverage_start_date` to `coverage_end_date` and add one.
    PRD: Multiply `installed_value_limit_cents` by 140, by the tier's installation security factor in basis points, and by `term_days`; then divide by ten thousand for the rate, by ten thousand again for the security factor, and by 365 for the annualisation; round the whole exact expression half-up once to obtain `rated_premium_cents`.
    Design: Difficulty/resource_temporal_overlap/jobsite_floater_closed_interval_adjacency_collides
    """
    ctx = site_holding_one_autumn_floater(api)

    accepted = validate_success(api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Tower B fit-out",
            installed_value_limit_cents=15000000,
            coverage_start_date="2026-12-02", coverage_end_date="2027-03-02"),
        UNDERWRITER), 201)

    assert accepted["status"] == "PENDING"
    assert accepted["term_days"] == 91
    assert accepted["rated_premium_cents"] == 52356
    assert accepted["termination_trigger"] is None
    _, meta = floaters_on_the_site(api, ctx)
    assert meta["total_count"] == 2


def owned_truck_with_one_planned_run(api, arrival_at, declared_value_cents):
    """An approved owned truck of 5,000,000 capacity carrying one planned run."""
    ctx = fixtures.build_in_force_transit_file(
        api, part_kwargs=dict(transit_owned_limit_cents=10000000,
                              transit_hired_limit_cents=0,
                              catastrophe_limit_cents=5000000))
    vehicle = fixtures.create_vehicle(api, unit_label="OWNED-11",
                                      per_conveyance_limit_cents=5000000,
                                      approval_expires_on="2026-12-31")
    vehicle = fixtures.approve_vehicle(api, vehicle["id"])
    fixtures.set_clock(api, "2026-08-04T00:00:00Z")
    first = fixtures.plan_shipment(
        api, ctx.part_id, vehicle["id"],
        origin_territory_code="T2_URBAN", destination_territory_code="T3_INLAND",
        departure_at="2026-08-05T08:00:00Z", arrival_at=arrival_at,
        declared_value_cents=declared_value_cents)
    ctx["vehicle_id"] = vehicle["id"]
    ctx["first"] = first
    return ctx


def runs_on_the_truck(api, ctx):
    """Every shipment booked on the conveyance, with its pagination envelope."""
    return validate_paginated(api.list_transit_shipments(
        UNDERWRITER, limit=50, offset=0, vehicle_id=ctx.vehicle_id))


def test_a_departure_inside_the_four_hour_turnaround_conflicts(api):
    """The truck is not free until four hours after it arrives, to the minute.

    PRD: The occupation window of a shipment is half-open in the instant domain: it begins at `departure_at` inclusive and ends at `arrival_at` exclusive, and the conveyance is not free again until a turnaround buffer of four hours has elapsed after `arrival_at`.
    PRD: The new shipment is tested against every shipment on the same vehicle whose status is `PLANNED` or `IN_TRANSIT`, and a conflict is refused with `ERR_VEHICLE_WINDOW_CONFLICT`.
    Design: Difficulty/resource_temporal_overlap/vehicle_transit_half_open_window_with_turnaround_buffer
    """
    ctx = owned_truck_with_one_planned_run(api, "2026-08-05T18:00:00Z", 1000000)
    assert ctx.first["catastrophe_zone"] is False
    assert ctx.first["status"] == "PLANNED"

    refused = api.create_transit_shipment(
        ctx.part_id,
        factories.transit_shipment(
            ctx.vehicle_id, origin_territory_code="T2_URBAN",
            destination_territory_code="T3_INLAND",
            departure_at="2026-08-05T21:59:00Z",
            arrival_at="2026-08-06T04:00:00Z", declared_value_cents=1000000),
        UNDERWRITER)

    validate_error(refused, "ERR_VEHICLE_WINDOW_CONFLICT", 409)
    _, meta = runs_on_the_truck(api, ctx)
    assert meta["total_count"] == 1


def test_a_departure_exactly_four_hours_after_arrival_is_accepted(api):
    """Both trailing edges are exclusive, so the buffer's own instant is free.

    PRD: Because both edges are exclusive at the trailing end, a shipment departing exactly four hours after the previous shipment's arrival is accepted, while one departing three hours and fifty-nine minutes after it is not.
    PRD: Delivered, lost and cancelled shipments release their windows.
    Design: Difficulty/resource_temporal_overlap/vehicle_transit_half_open_window_with_turnaround_buffer
    """
    ctx = owned_truck_with_one_planned_run(api, "2026-08-05T18:00:00Z", 1000000)

    accepted = validate_success(api.create_transit_shipment(
        ctx.part_id,
        factories.transit_shipment(
            ctx.vehicle_id, origin_territory_code="T2_URBAN",
            destination_territory_code="T3_INLAND",
            departure_at="2026-08-05T22:00:00Z",
            arrival_at="2026-08-06T04:00:00Z", declared_value_cents=1000000),
        UNDERWRITER), 201)

    assert accepted["status"] == "PLANNED"
    assert_instant_equals(accepted["departure_at"], "2026-08-05T22:00:00Z")
    _, meta = runs_on_the_truck(api, ctx)
    assert meta["total_count"] == 2


def test_two_runs_on_one_date_exceed_the_daily_capacity_though_no_window_overlaps(api):
    """The capacity test is a calendar bucket, and it fires where the window test does not.

    PRD: Independently of the window test, a conveyance may not be loaded beyond its stated capacity on any one day.
    PRD: Sum `declared_value_cents` over the shipments on the same vehicle whose status is `PLANNED` or `IN_TRANSIT` and whose `departure_at` falls on the same UTC calendar date as the new shipment's `departure_at`, include the new shipment's own `declared_value_cents` in that sum, and compare the total against the vehicle's `per_conveyance_limit_cents`; a total that exceeds it is refused with `ERR_VEHICLE_CAPACITY_EXCEEDED`.
    Design: Difficulty/resource_temporal_overlap/vehicle_daily_declared_value_capacity_is_calendar_bucket_not_window
    """
    ctx = owned_truck_with_one_planned_run(api, "2026-08-05T12:00:00Z", 4000000)

    refused = api.create_transit_shipment(
        ctx.part_id,
        factories.transit_shipment(
            ctx.vehicle_id, origin_territory_code="T2_URBAN",
            destination_territory_code="T3_INLAND",
            departure_at="2026-08-05T20:00:00Z",
            arrival_at="2026-08-05T23:00:00Z", declared_value_cents=1500000),
        UNDERWRITER)

    validate_error(refused, "ERR_VEHICLE_CAPACITY_EXCEEDED", 422)
    _, meta = runs_on_the_truck(api, ctx)
    assert meta["total_count"] == 1
    assert get_success_data(api.get_vehicle(
        ctx.vehicle_id, UNDERWRITER))["in_transit_value_cents"] == 0


def test_the_same_load_departing_after_midnight_falls_in_a_new_bucket(api):
    """Crossing the date boundary empties the bucket even hours later on the clock.

    PRD: This is a same-calendar-date test on the departure instant, not a rolling twenty-four-hour test, so two shipments departing twenty-three hours apart across midnight fall on different dates and do not aggregate, while two departing one minute apart within one date do.
    PRD: It is created with status `PLANNED` and null `departed_at` and `delivered_at`.
    Design: Difficulty/resource_temporal_overlap/vehicle_daily_declared_value_capacity_is_calendar_bucket_not_window
    """
    ctx = owned_truck_with_one_planned_run(api, "2026-08-05T12:00:00Z", 4000000)

    accepted = validate_success(api.create_transit_shipment(
        ctx.part_id,
        factories.transit_shipment(
            ctx.vehicle_id, origin_territory_code="T2_URBAN",
            destination_territory_code="T3_INLAND",
            departure_at="2026-08-06T02:00:00Z",
            arrival_at="2026-08-06T06:00:00Z", declared_value_cents=1500000),
        UNDERWRITER), 201)

    assert accepted["status"] == "PLANNED"
    assert accepted["departed_at"] is None
    _, meta = runs_on_the_truck(api, ctx)
    assert meta["total_count"] == 2
    assert get_success_data(api.get_vehicle(
        ctx.vehicle_id, UNDERWRITER))["in_transit_value_cents"] == 0

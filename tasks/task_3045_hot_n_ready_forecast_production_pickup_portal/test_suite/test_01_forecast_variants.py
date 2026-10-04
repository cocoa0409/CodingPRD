"""The two forecast variants on a Daypart row: provisional vs frozen-at-close final."""

from test_helpers import (
    fixtures,
    make_manager_headers,
    make_shift_lead_headers,
    validate_success,
)


def test_provisional_counts_scheduled_event_final_excludes_it(client):
    """Same rows, two variants: the provisional forecast counts the overlapping
    SCHEDULED event (10 x 2.0 = 20) while the final computed at close excludes it
    (10 x 1.0 = 10).

    "The forecast considers every non-cancelled demand event of the same store day
    whose status is `SCHEDULED` or `ACTIVE` and whose window overlaps the daypart
    window under closed-interval semantics"
    "A second, **final** variant, `forecast_units_final`, is computed once when the
    daypart closes and frozen thereafter: it counts only events in `ACTIVE` or
    `ENDED` status at close time under the same overlap predicate, so a
    still-`SCHEDULED` event is excluded and the same event set can yield a
    different number than the provisional value."

    Design: Difficulty/dual_variant_calc/forecast_provisional_counts_scheduled_event_final_excludes_it
    """
    manager = make_manager_headers()
    bundle = fixtures.planned_store_day(
        client,
        "2026-09-10",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1020,
            "rack_capacity": 30,
            "base_demand_units": 10,
        },
    )
    sd, dp = bundle.store_day, bundle.daypart
    fixtures.create_demand_event(
        client,
        sd["id"],
        name="Game Night",
        window_start_at="2026-09-10T16:30:00Z",
        window_end_at="2026-09-10T19:00:00Z",
        demand_multiplier=2.0,
    )
    fixtures.get_success_data(client.open_store_day(sd["id"], manager))
    fixtures.set_clock(client, "2026-09-10T16:05:00Z")

    closed = validate_success(client.close_daypart(dp["id"], make_shift_lead_headers()), 200)

    assert closed["status"] == "CLOSED"
    assert closed["forecast_units_provisional"] == 20, (
        "provisional must count the overlapping SCHEDULED event: 10 x 2.0"
    )
    assert closed["forecast_units_final"] == 10, (
        "final must exclude the still-SCHEDULED event: 10 x 1.0"
    )
    assert closed["forecast_units_provisional"] != closed["forecast_units_final"]

    stored = fixtures.read_daypart(client, dp["id"])
    assert stored["forecast_units_provisional"] == 20
    assert stored["forecast_units_final"] == 10


def test_provisional_forecast_is_null_free_and_final_null_until_close(client):
    """The provisional forecast is computed at creation; the final variant stays
    null until the daypart closes.

    "The forecast considers every non-cancelled demand event of the same store day
    whose status is `SCHEDULED` or `ACTIVE`"
    "Until close, `forecast_units_final` is null."

    Design: Difficulty/dual_variant_calc/forecast_provisional_counts_scheduled_event_final_excludes_it
    """
    manager = make_manager_headers()
    bundle = fixtures.planned_store_day(
        client,
        "2026-09-10",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1020,
            "rack_capacity": 30,
            "base_demand_units": 10,
        },
    )
    sd, dp = bundle.store_day, bundle.daypart
    assert dp["forecast_units_provisional"] == 10, (
        "creation snapshot is base demand only, before the event exists"
    )
    assert dp["forecast_units_final"] is None, (
        "forecast_units_final must be null until close"
    )
    fixtures.create_demand_event(
        client,
        sd["id"],
        name="Game Night",
        window_start_at="2026-09-10T16:30:00Z",
        window_end_at="2026-09-10T19:00:00Z",
        demand_multiplier=2.0,
    )
    # "Creating an event triggers the same recomputation with the new event
    # included." -- re-read the daypart after the event to see the live value.
    dp = fixtures.read_daypart(client, dp["id"])
    assert dp["forecast_units_provisional"] == 20
    assert dp["forecast_units_final"] is None, (
        "forecast_units_final must be null until close"
    )

    fixtures.get_success_data(client.open_store_day(sd["id"], manager))
    fixtures.set_clock(client, "2026-09-10T16:05:00Z")
    live = fixtures.read_daypart(client, dp["id"])
    assert live["status"] == "ACTIVE"
    assert live["forecast_units_provisional"] == 20
    assert live["forecast_units_final"] is None

    fixtures.get_success_data(client.close_daypart(dp["id"], make_shift_lead_headers()))
    closed = fixtures.read_daypart(client, dp["id"])
    assert closed["forecast_units_final"] == 10

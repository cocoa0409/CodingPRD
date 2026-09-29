"""Resources contended over time, where the verdict turns on a single instant."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_crane_costs,
    assert_total_count,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    CRANE_REQUESTED,
    CREW_ON_SHIFT,
    CURTAILMENT_ACTIVE,
    CURTAILMENT_CURTAILED,
    CURTAILMENT_FORCED_STOP,
    CURTAILMENT_PENDING,
    CURTAILMENT_RELEASED,
    CURTAILMENT_UNCONSTRAINED,
    WINDOW_CONFIRMED,
    WINDOW_FORECAST,
    WO_SCHEDULED,
    WO_SUBMITTED,
)
from test_helpers.factories import crane_payload, schedule_payload, weather_window_payload
from test_helpers.fixtures import (
    read_crane,
    read_crew,
    read_curtailment,
    read_turbine,
    read_window,
    read_work_order,
    setup_crew_tiling_day,
    setup_curtailment_stack,
    setup_touch_point_geometry,
)
from test_helpers.test_users import make_control_room_headers, make_planner_headers


def _schedule(api, order_id, site, planned_start_utc, planned_end_utc, window_id=None):
    """Offer one planned interval to the tiling crew inside the tiling window."""
    return api.schedule_work_order(
        order_id,
        schedule_payload(
            site["crew"]["id"],
            window_id or site["window"]["id"],
            planned_start_utc,
            planned_end_utc,
        ),
        make_planner_headers(),
    )


def test_a_crew_may_finish_one_order_at_the_instant_it_begins_the_next(api):
    """Adjacency is accepted on the upper edge and on the lower edge alike.

    The contract states: "Every interval in this system is **half-open**: the start
    bound is inclusive and the end bound is exclusive."  Of the crew it states:
    "**Occupancy** asks whether any such order's planned interval overlaps the
    proposed one under the half-open rule of §2.5 — that is, whether an existing
    order starts strictly before the proposed end and ends strictly after the
    proposed start."  It continues: "Adjacency is explicitly allowed here: a crew may
    finish one order at exactly the instant it begins the next."  Of the bookkeeping
    it states: "A successful schedule stores `crew_id`, `weather_window_id`,
    `planned_start_utc` and `planned_end_utc` on the order, sets the crew's `status`
    to `ON_SHIFT`, and increments the window's `active_work_order_count` by 1 while
    **leaving the window in `CONFIRMED`** — which is precisely what allows a second
    crew to be scheduled into the same window."

    Design: Difficulty/resource_temporal_overlap/crew_occupancy_is_half_open_so_exact_adjacency_schedules_but_a_one_minute_overlap_is_refused
    """
    site = setup_crew_tiling_day(api)

    first = validate_success(
        _schedule(api, site["wo_a"]["id"], site, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
    )
    assert first["state"] == WO_SCHEDULED
    assert first["crew_id"] == site["crew"]["id"]
    assert first["weather_window_id"] == site["window"]["id"]

    upper_edge = validate_success(
        _schedule(api, site["wo_b"]["id"], site, "2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z")
    )
    assert upper_edge["state"] == WO_SCHEDULED
    assert upper_edge["planned_start_utc"] == first["planned_end_utc"]

    lower_edge = validate_success(
        _schedule(api, site["wo_d"]["id"], site, "2026-08-10T04:00:00Z", "2026-08-10T06:00:00Z")
    )
    assert lower_edge["state"] == WO_SCHEDULED
    assert lower_edge["planned_end_utc"] == first["planned_start_utc"]

    window = read_window(api, site["window"]["id"])
    assert window["state"] == WINDOW_CONFIRMED
    assert window["active_work_order_count"] == 3
    assert read_crew(api, site["crew"]["id"])["status"] == CREW_ON_SHIFT


def test_a_one_minute_overlap_and_a_contained_interval_are_both_refused(api):
    """Two refusals leave no residue, and the same order schedules on the third try.

    The contract states: "**Occupancy** asks whether any such order's planned
    interval overlaps the proposed one under the half-open rule of §2.5 — that is,
    whether an existing order starts strictly before the proposed end and ends
    strictly after the proposed start."  It continues: "An overlap is refused with
    `ERR_CREW_WINDOW_CONFLICT`."  Of the window it states: "The proposed interval
    must be **contained** inside the window's interval, meaning `planned_start_utc`
    is at or after the window's `start_utc` and `planned_end_utc` is at or before its
    `end_utc`; anything protruding is refused with `ERR_WORK_ORDER_OUTSIDE_WINDOW`."
    It also states: "A rejected request writes nothing at all — no counter moves, no
    `version` advances, no partial cascade survives."

    Design: Difficulty/resource_temporal_overlap/crew_occupancy_is_half_open_so_exact_adjacency_schedules_but_a_one_minute_overlap_is_refused
    """
    site = setup_crew_tiling_day(api)
    validate_success(
        _schedule(api, site["wo_a"]["id"], site, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
    )
    validate_success(
        _schedule(api, site["wo_b"]["id"], site, "2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z")
    )

    one_minute = _schedule(
        api, site["wo_c"]["id"], site, "2026-08-10T13:59:00Z", "2026-08-10T16:00:00Z"
    )
    validate_error(one_minute, "ERR_CREW_WINDOW_CONFLICT", 409)

    contained = _schedule(
        api, site["wo_c"]["id"], site, "2026-08-10T09:00:00Z", "2026-08-10T09:30:00Z"
    )
    validate_error(contained, "ERR_CREW_WINDOW_CONFLICT", 409)

    held = read_work_order(api, site["wo_c"]["id"])
    assert held["state"] == WO_SUBMITTED
    assert held["crew_id"] is None
    assert held["weather_window_id"] is None
    assert held["planned_start_utc"] is None
    assert held["planned_end_utc"] is None
    assert_version_unchanged(site["wo_c"], held)

    outside = _schedule(
        api, site["wo_c"]["id"], site, "2026-08-11T00:00:00Z", "2026-08-11T02:00:00Z"
    )
    validate_error(outside, "ERR_WORK_ORDER_OUTSIDE_WINDOW", 422)
    assert read_work_order(api, site["wo_c"]["id"])["state"] == WO_SUBMITTED

    retried = validate_success(
        _schedule(api, site["wo_c"]["id"], site, "2026-08-10T14:00:00Z", "2026-08-10T16:00:00Z")
    )
    assert retried["state"] == WO_SCHEDULED

    window = read_window(api, site["window"]["id"])
    assert window["state"] == WINDOW_CONFIRMED
    assert window["active_work_order_count"] == 3


def test_the_crane_pad_closes_at_the_touch_point_on_both_of_its_edges(api):
    """A padded slot overlapping another by one second is refused; touching exactly clears it.

    The anchor runs 2026-09-10 to 2026-09-12, so its padded slot is
    [2026-09-08, 2026-09-14).  Overlap is the half-open test of PRD 2.5 applied to the
    padded intervals, so a request whose own pad merely touches [2026-09-08, 2026-09-14)
    at one instant does not overlap it, while a request reaching one second inside does.
    Because the pad is 48 hours on each side, that is what makes raw adjacency conflict:
    a mobilization beginning at the anchor's 2026-09-12 end sits 96 hours inside the
    combined pad.

    The contract states: "Every mobilization reserves the slot for its own interval
    **plus two full days, 48 hours, on each side**, for haul-road access and
    assembly."  It continues: "A new mobilization is refused with
    `ERR_CRANE_BUFFER_CONFLICT` when its padded interval overlaps the equally padded
    interval of any mobilization on the same farm still in `REQUESTED` or
    `MOBILIZED`; mobilizations in `DEMOBILIZED` or `CANCELLED` have released the slot
    and are ignored."  And: "Unlike crew occupancy, exact adjacency **does** conflict
    here — a mobilization beginning the instant another ends sits 96 hours inside the
    combined pad."  Of a new request it states: "A mobilization begins in `state`
    `REQUESTED` with `reserved_replacement_count` at 0 and every cost figure —
    `lift_days`, `standby_days`, `billable_days`, `subtotal_cents`,
    `volume_credit_cents` and `total_crane_cost_cents` — at 0."

    Design: Difficulty/resource_temporal_overlap/crane_buffer_closes_at_the_touch_point_while_weather_window_adjacency_stays_open
    """
    site = setup_touch_point_geometry(api)

    # The PRD's own worked example: a mobilization beginning the instant the anchor
    # ends is 96 hours inside the combined pad, so raw adjacency does conflict.
    raw_adjacent = api.create_crane_mobilization(
        crane_payload(
            site["farm"]["id"],
            crane_class="TOWER_ASSIST",
            mobilization_start_utc="2026-09-12T00:00:00Z",
            demobilization_end_utc="2026-09-13T00:00:00Z",
            day_rate_cents=1200000,
            mobilization_fee_cents=4000000,
            max_lift_wind_speed_ms=11.0,
        ),
        make_planner_headers(),
    )
    validate_error(raw_adjacent, "ERR_CRANE_BUFFER_CONFLICT", 409)

    # One second inside the anchor's padded upper edge of 2026-09-14T00:00:00Z.
    upper_overlap = api.create_crane_mobilization(
        crane_payload(
            site["farm"]["id"],
            crane_class="TOWER_ASSIST",
            mobilization_start_utc="2026-09-15T23:59:59Z",
            demobilization_end_utc="2026-09-17T00:00:00Z",
            day_rate_cents=1200000,
            mobilization_fee_cents=4000000,
            max_lift_wind_speed_ms=11.0,
        ),
        make_planner_headers(),
    )
    validate_error(upper_overlap, "ERR_CRANE_BUFFER_CONFLICT", 409)

    # Its own pad now starts exactly at 2026-09-14T00:00:00Z, so the two padded
    # intervals merely touch and, under the half-open rule, do not overlap.
    upper_clear = validate_success(
        api.create_crane_mobilization(
            crane_payload(
                site["farm"]["id"],
                crane_class="TOWER_ASSIST",
                mobilization_start_utc="2026-09-16T00:00:00Z",
                demobilization_end_utc="2026-09-17T00:00:00Z",
                day_rate_cents=1200000,
                mobilization_fee_cents=4000000,
                max_lift_wind_speed_ms=11.0,
            ),
            make_planner_headers(),
        ),
        201,
    )
    assert upper_clear["state"] == CRANE_REQUESTED

    # One second inside the anchor's padded lower edge of 2026-09-08T00:00:00Z.
    lower_overlap = api.create_crane_mobilization(
        crane_payload(
            site["farm"]["id"],
            crane_class="SELF_ERECTING",
            mobilization_start_utc="2026-09-04T00:00:00Z",
            demobilization_end_utc="2026-09-06T00:00:01Z",
            day_rate_cents=700000,
            mobilization_fee_cents=1500000,
            max_lift_wind_speed_ms=12.0,
        ),
        make_planner_headers(),
    )
    validate_error(lower_overlap, "ERR_CRANE_BUFFER_CONFLICT", 409)

    # Its own pad now ends exactly at 2026-09-08T00:00:00Z, the touch point again.
    lower_clear = validate_success(
        api.create_crane_mobilization(
            crane_payload(
                site["farm"]["id"],
                crane_class="SELF_ERECTING",
                mobilization_start_utc="2026-09-04T00:00:00Z",
                demobilization_end_utc="2026-09-06T00:00:00Z",
                day_rate_cents=700000,
                mobilization_fee_cents=1500000,
                max_lift_wind_speed_ms=12.0,
            ),
            make_planner_headers(),
        ),
        201,
    )
    assert lower_clear["state"] == CRANE_REQUESTED

    anchor = read_crane(api, site["crane_anchor"]["id"])
    assert anchor["state"] == CRANE_REQUESTED
    assert anchor["reserved_replacement_count"] == 0
    assert_crane_costs(anchor, lift_days=0, standby_days=0, billable_days=0)
    assert_cents(anchor["total_crane_cost_cents"], 0, "anchor.total_crane_cost_cents")

    assert_total_count(
        api.list_crane_mobilizations(
            make_planner_headers(), wind_farm_id=site["farm"]["id"], state=CRANE_REQUESTED
        ),
        3,
    )


def test_a_weather_window_may_start_where_another_ends_on_the_very_same_farm(api):
    """The opposite verdict to the crane pad, on the same farm in the same request run.

    The contract states: "Its half-open interval must not overlap any window on the
    same farm still in `FORECAST` or `CONFIRMED`; an overlap is refused with
    `ERR_WEATHER_WINDOW_OVERLAP`, while exact adjacency — a new window starting at
    the instant an existing one ends — is permitted."  It also states: "A new window
    is created in `state` `FORECAST` with `active_work_order_count` at 0."  And:
    "Every interval in this system is **half-open**: the start bound is inclusive and
    the end bound is exclusive."

    Design: Difficulty/resource_temporal_overlap/crane_buffer_closes_at_the_touch_point_while_weather_window_adjacency_stays_open
    """
    site = setup_touch_point_geometry(api)

    adjacent = validate_success(
        api.create_weather_window(
            weather_window_payload(
                site["farm"]["id"],
                start_utc="2026-09-10T12:00:00Z",
                end_utc="2026-09-11T00:00:00Z",
                forecast_wind_speed_ms=7.5,
                forecast_gust_ms=10.5,
                icing_risk=False,
            ),
            make_planner_headers(),
        ),
        201,
    )
    assert adjacent["state"] == WINDOW_FORECAST
    assert adjacent["active_work_order_count"] == 0
    assert adjacent["start_utc"] == site["ww_anchor"]["end_utc"]

    one_minute = api.create_weather_window(
        weather_window_payload(
            site["farm"]["id"],
            start_utc="2026-09-10T11:59:00Z",
            end_utc="2026-09-10T13:00:00Z",
            forecast_wind_speed_ms=7.5,
            forecast_gust_ms=10.5,
            icing_risk=False,
        ),
        make_planner_headers(),
    )
    validate_error(one_minute, "ERR_WEATHER_WINDOW_OVERLAP", 409)

    confirmed = validate_success(
        api.confirm_weather_window(site["ww_anchor"]["id"], make_planner_headers())
    )
    assert confirmed["state"] == WINDOW_CONFIRMED

    inside_confirmed = api.create_weather_window(
        weather_window_payload(
            site["farm"]["id"],
            start_utc="2026-09-10T06:00:00Z",
            end_utc="2026-09-10T07:00:00Z",
            forecast_wind_speed_ms=7.5,
            forecast_gust_ms=10.5,
            icing_risk=False,
        ),
        make_planner_headers(),
    )
    validate_error(inside_confirmed, "ERR_WEATHER_WINDOW_OVERLAP", 409)

    rows = assert_total_count(
        api.list_weather_windows(make_planner_headers(), wind_farm_id=site["farm"]["id"]), 2
    )
    assert sorted(row["state"] for row in rows) == [WINDOW_CONFIRMED, WINDOW_FORECAST]


def test_the_stack_limit_counts_live_orders_and_not_the_order_presented(api):
    """Two perfectly legal orders are refused because two others got there first.

    The contract states: "Bringing an order into force drives it `PENDING → ACTIVE`
    and writes only the curtailment dimension."  It continues: "The turbine must not
    be `DECOMMISSIONED`, and it must currently hold fewer than **two** active orders;
    a third concurrent order is refused with `ERR_CURTAILMENT_STACK_LIMIT`."  And:
    "Activation increments the turbine's `active_curtailment_count` by 1 and sets its
    `effective_power_limit_kw` to the smallest `power_limit_kw` across all of that
    turbine's active orders — the most restrictive instruction wins."  It also states:
    "A rejected request writes nothing at all — no counter moves, no `version`
    advances, no partial cascade survives."

    Design: Difficulty/resource_temporal_overlap/curtailment_stack_limit_is_an_aggregate_gate_that_reopens_only_as_orders_release
    """
    site = setup_curtailment_stack(api)
    turbine_id = site["t1"]["id"]

    grid = validate_success(
        api.activate_curtailment_order(site["co_grid"]["id"], make_control_room_headers())
    )
    assert grid["state"] == CURTAILMENT_ACTIVE
    after_grid = read_turbine(api, turbine_id)
    assert after_grid["active_curtailment_count"] == 1
    assert after_grid["effective_power_limit_kw"] == 1500
    assert after_grid["curtailment_state"] == CURTAILMENT_CURTAILED

    validate_success(
        api.activate_curtailment_order(site["co_noise"]["id"], make_control_room_headers())
    )
    after_noise = read_turbine(api, turbine_id)
    assert after_noise["active_curtailment_count"] == 2
    assert after_noise["effective_power_limit_kw"] == 800
    assert after_noise["curtailment_state"] == CURTAILMENT_CURTAILED

    third = api.activate_curtailment_order(
        site["co_wildlife"]["id"], make_control_room_headers()
    )
    validate_error(third, "ERR_CURTAILMENT_STACK_LIMIT", 409)

    fourth = api.activate_curtailment_order(site["co_icing"]["id"], make_control_room_headers())
    validate_error(fourth, "ERR_CURTAILMENT_STACK_LIMIT", 409)

    assert read_curtailment(api, site["co_wildlife"]["id"])["state"] == CURTAILMENT_PENDING
    assert read_curtailment(api, site["co_icing"]["id"])["state"] == CURTAILMENT_PENDING
    assert_version_unchanged(
        site["co_icing"], read_curtailment(api, site["co_icing"]["id"])
    )
    still_two = read_turbine(api, turbine_id)
    assert still_two["active_curtailment_count"] == 2
    assert still_two["effective_power_limit_kw"] == 800


def test_each_release_frees_one_slot_and_accrues_only_up_to_its_released_at(api):
    """A slot freed is a slot taken, and the minimum is recomputed at every step.

    The contract states: "This is the one place where accrual is measured from what
    actually happened rather than from what was planned: `curtailed_hours` is the
    elapsed time from `start_utc` to `released_at` expressed in hours, **not** from
    `start_utc` to the order's `end_utc`, so an early release accrues strictly less
    than the order asked for."  It continues: "`lost_energy_kwh` is `curtailed_hours`
    multiplied by `deemed_kwh_per_hour`, rounded half up to two decimal places."  And:
    "The turbine's `active_curtailment_count` is decremented by 1, and
    `effective_power_limit_kw` is recomputed as the smallest `power_limit_kw` across
    the orders that remain active, or as the model's `rated_power_kw` — the
    uncurtailed nameplate ceiling — when none remain."  Of the accrual side it states:
    "When `compensable` is false, the released `curtailed_hours` is added to the
    turbine's `counted_downtime_hours_period`, and nothing is added when it is true."
    And of the flag: "The `compensable` flag is derived, never supplied: it is true
    exactly when `reason` is `GRID`, and false for `NOISE`, `ICING` and `WILDLIFE`."

    Design: Difficulty/resource_temporal_overlap/curtailment_stack_limit_is_an_aggregate_gate_that_reopens_only_as_orders_release
    """
    site = setup_curtailment_stack(api)
    turbine_id = site["t1"]["id"]
    validate_success(
        api.activate_curtailment_order(site["co_grid"]["id"], make_control_room_headers())
    )
    validate_success(
        api.activate_curtailment_order(site["co_noise"]["id"], make_control_room_headers())
    )

    released_grid = validate_success(
        api.release_curtailment_order(
            site["co_grid"]["id"], "2026-08-01T04:00:00Z", make_control_room_headers()
        )
    )
    assert released_grid["state"] == CURTAILMENT_RELEASED
    assert released_grid["compensable"] is True
    assert_two_dp(released_grid["curtailed_hours"], 4.0, "grid.curtailed_hours")
    assert_two_dp(released_grid["lost_energy_kwh"], 2000.00, "grid.lost_energy_kwh")
    after_grid = read_turbine(api, turbine_id)
    assert after_grid["counted_downtime_hours_period"] == 0
    assert after_grid["active_curtailment_count"] == 1
    assert after_grid["effective_power_limit_kw"] == 800
    assert after_grid["curtailment_state"] == CURTAILMENT_CURTAILED

    wildlife = validate_success(
        api.activate_curtailment_order(site["co_wildlife"]["id"], make_control_room_headers())
    )
    assert wildlife["state"] == CURTAILMENT_ACTIVE
    stacked = read_turbine(api, turbine_id)
    assert stacked["active_curtailment_count"] == 2
    assert stacked["effective_power_limit_kw"] == 0
    assert stacked["curtailment_state"] == CURTAILMENT_FORCED_STOP

    refused_again = api.activate_curtailment_order(
        site["co_icing"]["id"], make_control_room_headers()
    )
    validate_error(refused_again, "ERR_CURTAILMENT_STACK_LIMIT", 409)

    released_noise = validate_success(
        api.release_curtailment_order(
            site["co_noise"]["id"], "2026-08-01T05:00:00Z", make_control_room_headers()
        )
    )
    assert released_noise["compensable"] is False
    assert_two_dp(released_noise["curtailed_hours"], 3.0, "noise.curtailed_hours")
    assert_two_dp(released_noise["lost_energy_kwh"], 1200.00, "noise.lost_energy_kwh")
    after_noise = read_turbine(api, turbine_id)
    assert_two_dp(
        after_noise["counted_downtime_hours_period"], 3.0, "t1.counted_downtime_hours_period"
    )
    assert after_noise["active_curtailment_count"] == 1
    assert after_noise["effective_power_limit_kw"] == 0
    assert after_noise["curtailment_state"] == CURTAILMENT_FORCED_STOP

    released_wildlife = validate_success(
        api.release_curtailment_order(
            site["co_wildlife"]["id"], "2026-08-01T03:30:00Z", make_control_room_headers()
        )
    )
    assert_two_dp(released_wildlife["curtailed_hours"], 0.5, "wildlife.curtailed_hours")
    assert_two_dp(released_wildlife["lost_energy_kwh"], 0.00, "wildlife.lost_energy_kwh")
    emptied = read_turbine(api, turbine_id)
    assert_two_dp(
        emptied["counted_downtime_hours_period"], 3.5, "t1.counted_downtime_hours_period"
    )
    assert emptied["active_curtailment_count"] == 0
    assert emptied["curtailment_state"] == CURTAILMENT_UNCONSTRAINED
    assert emptied["effective_power_limit_kw"] == 4200

    finally_active = validate_success(
        api.activate_curtailment_order(site["co_icing"]["id"], make_control_room_headers())
    )
    assert finally_active["state"] == CURTAILMENT_ACTIVE
    reopened = read_turbine(api, turbine_id)
    assert reopened["active_curtailment_count"] == 1
    assert reopened["effective_power_limit_kw"] == 1200
    assert reopened["curtailment_state"] == CURTAILMENT_CURTAILED

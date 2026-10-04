"""Demand curves and staged fleet deployment.

A wave leaves a staged reserve behind, and the reserve is rounded up once per
wave before the subtraction is applied.  Activation is where all three safety
gates converge, and dispatching is a best-effort allocation rather than an
all-or-nothing one.
"""

from test_helpers import constants as c
from test_helpers.api_errors import (
    ERR_TERRITORY_NOT_ACTIVE,
    ERR_WEATHER_SUSPENDED,
    ERR_ZONE_BLOCKED_WAVE,
)
from test_helpers.assertions import get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    active_territory_with_depot,
    activate_zones,
    bind_demand_signal,
    create_wave,
    read_territory,
    read_vehicle,
    set_clock,
    staged_available_vehicles,
)
from test_helpers.test_users import PLANNER, SAFETY


def get_wave(api, wave_id):
    """Read a wave by its own identifier."""
    return get_success_data(api.get_wave(wave_id, headers=PLANNER))


def _staged_territory(api, count, **depot_overrides):
    """An ACTIVE territory with ``count`` staged, service-ready vehicles."""
    stack = active_territory_with_depot(api, depot_overrides=depot_overrides or None)
    territory, depot = stack["territory"], stack["depot"]
    vehicles = staged_available_vehicles(api, depot["id"], territory["id"], count)
    stack["vehicles"] = vehicles
    return stack


class TestWaveReserveFloor:
    """The reserve is rounded up once per wave, before any subtraction."""

    def test_wave_of_four_keeps_a_reserve_floor_of_two(self, api):
        """Budget 4 over 3 available staged cars deploys exactly one.

        PRD 3.3: "The reserve floor is 6 divided by the wave's
        `planned_vehicle_count`, rounded up to a whole number; this rounding is
        performed once per wave, before any subtraction, and it rounds up rather
        than down."
        PRD 3.3: "A wave planning 4 vehicles therefore keeps a reserve floor of
        2, not 1, and consequently deploys one fewer vehicle than a floor-based
        reading would allow."

        Design: Difficulty/combinatorial_formula/if_match_wave_reserve_floor_nested_rounding
        """
        set_clock(api)
        stack = _staged_territory(api, 3)
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"], projected_rides=50, manual_only_rides=10)
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=4)
        validate_success(api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER))

        dispatched = validate_success(
            api.dispatch_wave(territory["id"], wave["id"], headers=PLANNER)
        )
        assert dispatched["status"] == c.WAVE_COMPLETED
        assert dispatched["deployed_vehicle_count"] == 1, (
            "ceil(6/4) == 2 keeps two staged, so 3 available - 2 == 1 deploys"
        )

    def test_the_deployed_car_is_the_highest_charged_candidate(self, api):
        """Ranking is battery descending, with creation order breaking ties.

        PRD 3.3: "Candidates are then ranked by `battery_pct` descending and,
        where batteries tie, by `created_at` ascending; ties are never broken by
        `id`. The top candidates up to the cap are taken."

        Design: Difficulty/combinatorial_formula/if_match_wave_reserve_floor_nested_rounding
        """
        set_clock(api)
        stack = _staged_territory(api, 3)
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"])
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=4)
        validate_success(api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER))
        validate_success(api.dispatch_wave(territory["id"], wave["id"], headers=PLANNER))

        deployed = [
            vehicle for vehicle in stack["vehicles"]
            if read_vehicle(api, vehicle["id"])["status"] == c.VEHICLE_IN_SERVICE
        ]
        assert len(deployed) == 1
        highest = max(stack["vehicles"], key=lambda row: row["battery_pct"])
        assert deployed[0]["id"] == highest["id"]

    def test_the_undeproyed_reserve_stays_staged_and_available(self, api):
        """The vehicles left behind are still AT_DEPOT and still AVAILABLE.

        PRD 3.3: "The candidate pool is every vehicle in the wave's territory
        whose `status` is `AT_DEPOT`, whose `is_roadside_blocked` is false, and
        whose `service_status` is `AVAILABLE`."
        PRD 2.5: "otherwise a vehicle whose `status` is `AT_DEPOT` is `AVAILABLE`
        when it is service ready and `UNAVAILABLE` when it is not"

        Design: Difficulty/combinatorial_formula/if_match_wave_reserve_floor_nested_rounding
        """
        set_clock(api)
        stack = _staged_territory(api, 3)
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"])
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=4)
        validate_success(api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER))
        validate_success(api.dispatch_wave(territory["id"], wave["id"], headers=PLANNER))

        lowest = min(stack["vehicles"], key=lambda row: row["battery_pct"])
        after = read_vehicle(api, lowest["id"])
        assert after["status"] == c.VEHICLE_AT_DEPOT
        assert after["service_status"] == c.SERVICE_AVAILABLE


class TestWavePartialSelection:
    """Dispatch is best-effort rather than all-or-nothing."""

    def test_short_pool_still_completes_the_wave(self, api):
        """Fewer candidates than the budget completes with a reduced count.

        PRD 3.3: "The number of candidates is counted, and the actual allocation
        cap is the smaller of the wave's budget and the candidate count minus the
        reserve floor — floored at zero, so a territory with fewer available
        vehicles than its reserve floor deploys nothing at all rather than
        deploying a negative number."
        PRD 3.3: "the wave's `deployed_vehicle_count` is set to the number
        actually moved. The wave itself moves from `ACTIVE` to `COMPLETED`."

        Design: Corner/endpoints/if_match_wave_dispatch_partial_selection_semantics
        """
        set_clock(api)
        stack = _staged_territory(api, 2)
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"])
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=6)
        validate_success(api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER))

        dispatched = validate_success(
            api.dispatch_wave(territory["id"], wave["id"], headers=PLANNER)
        )
        assert dispatched["status"] == c.WAVE_COMPLETED
        assert dispatched["deployed_vehicle_count"] == 1, (
            "ceil(6/6) == 1 keeps one staged, so 2 available - 1 == 1 deploys"
        )

    def test_a_budget_below_the_pool_still_caps_at_the_budget(self, api):
        """With plenty of candidates the wave budget is the binding constraint.

        PRD 3.3: "The actual allocation cap is the smaller of the wave's budget
        and the candidate count minus the reserve floor."

        Design: Corner/endpoints/if_match_wave_dispatch_partial_selection_semantics
        """
        set_clock(api)
        stack = _staged_territory(
            api, 6,
            charge_positions=8, cleaning_positions=8, calib_positions=8, software_positions=8,
        )
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"])
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=2)
        validate_success(api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER))

        dispatched = validate_success(
            api.dispatch_wave(territory["id"], wave["id"], headers=PLANNER)
        )
        assert dispatched["deployed_vehicle_count"] == 2, (
            "min(2, 6 - ceil(6/2)=3) == 2"
        )


class TestWaveActivationGates:
    """Activation is where the posture, zone and weather gates converge."""

    def test_three_active_zones_refuse_the_activation(self, api):
        """A RESTRICTED territory refuses an otherwise valid wave.

        PRD 3.3: "A wave may be activated only when the territory's `posture` is
        `ACTIVE` — anything else, including `RESTRICTED` or `SUSPENDED`, is
        refused with `ERR_TERRITORY_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/if_match_wave_activation_requires_territory_active
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=1)
        activate_zones(api, territory["id"], 3, route_class=c.ROUTE_FREEWAY)

        read = read_territory(api, territory["id"])
        assert read["posture"] == c.POSTURE_RESTRICTED
        assert read["active_zone_count"] == 3

        resp = api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)
        validate_error(resp, ERR_TERRITORY_NOT_ACTIVE, 409)

    def test_the_refused_wave_stays_planned(self, api):
        """The rejected activation leaves the wave untouched.

        PRD 3.3: "A wave may be activated only when the territory's `posture` is
        `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/if_match_wave_activation_requires_territory_active
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=1)
        activate_zones(api, territory["id"], 3, route_class=c.ROUTE_FREEWAY)
        api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)

        after = get_wave(api, wave["id"])
        assert after["status"] == c.WAVE_PLANNED
        assert after["deployed_vehicle_count"] == 0

    def test_a_single_active_zone_blocks_the_wave(self, api):
        """One active zone is enough to refuse activation, even at ACTIVE posture.

        PRD 3.3: "only when the territory has no active exclusion zones at all —
        a single `ACTIVE` zone is enough to refuse the activation with
        `ERR_ZONE_BLOCKED_WAVE` (HTTP 409), even though three zones would be
        needed to push the posture out of `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/if_match_wave_activation_requires_territory_active
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=1)
        activate_zones(api, territory["id"], 1, route_class=c.ROUTE_FREEWAY)
        assert read_territory(api, territory["id"])["posture"] == c.POSTURE_ACTIVE

        resp = api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)
        validate_error(resp, ERR_ZONE_BLOCKED_WAVE, 409)

    def test_severe_weather_refuses_a_peak_window_wave(self, api):
        """A MORNING_PEAK wave is refused when the forecast tier reaches 3.

        PRD 2.8: "when the forecast `tier` for a `MORNING_PEAK` or
        `EVENING_PEAK` window is 3 or higher, wave activation for that window is
        rejected with `ERR_WEATHER_SUSPENDED` (HTTP 422). The `MIDDAY` and
        `OVERNIGHT` windows are not subject to this gate."

        Design: Corner/validations/if_match_weather_suspension_on_peak_wave
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        get_success_data(
            api.weather_tier_tick(
                territory["id"], {"window_code": c.WINDOW_MORNING_PEAK, "tier": 4},
                headers=SAFETY,
            )
        )
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MORNING_PEAK,
                           planned_vehicle_count=1)
        resp = api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)
        validate_error(resp, ERR_WEATHER_SUSPENDED, 422)

    def test_the_same_conditions_let_a_midday_wave_activate(self, api):
        """The weather gate is conditional on the window code.

        PRD 2.8: "The `MIDDAY` and `OVERNIGHT` windows are not subject to this
        gate."

        Design: Corner/validations/if_match_weather_suspension_on_peak_wave
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        get_success_data(
            api.weather_tier_tick(
                territory["id"], {"window_code": c.WINDOW_MORNING_PEAK, "tier": 4},
                headers=SAFETY,
            )
        )
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=1)
        activated = validate_success(
            api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)
        )
        assert activated["status"] == c.WAVE_ACTIVE

    def test_tier_two_does_not_suspend_a_peak_window(self, api):
        """Below tier 3 the peak window activates normally.

        PRD 2.8: "The tiers that matter here are the peak windows: when the
        forecast `tier` for a `MORNING_PEAK` or `EVENING_PEAK` window is 3 or
        higher, wave activation for that window is rejected with
        `ERR_WEATHER_SUSPENDED` (HTTP 422)."

        Design: Corner/validations/if_match_weather_suspension_on_peak_wave
        """
        set_clock(api)
        stack = _staged_territory(api, 1)
        territory = stack["territory"]
        get_success_data(
            api.weather_tier_tick(
                territory["id"], {"window_code": c.WINDOW_EVENING_PEAK, "tier": 2},
                headers=SAFETY,
            )
        )
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_EVENING_PEAK,
                           planned_vehicle_count=1)
        activated = validate_success(
            api.activate_wave(territory["id"], wave["id"], {}, headers=PLANNER)
        )
        assert activated["status"] == c.WAVE_ACTIVE

    def test_abort_moves_a_planned_wave_to_aborted(self, api):
        """A wave that should not run may be aborted from PLANNED or ACTIVE.

        PRD 3.3: "A wave that should not run may be aborted from either `PLANNED`
        or `ACTIVE`, landing in `ABORTED`. No vehicles move as a result of an
        abort."

        Design: Corner/endpoints/if_match_wave_dispatch_partial_selection_semantics
        """
        set_clock(api)
        stack = _staged_territory(api, 2)
        territory = stack["territory"]
        wave = create_wave(api, territory["id"], window_code=c.WINDOW_MIDDAY,
                           planned_vehicle_count=2)
        aborted = get_success_data(api.abort_wave(territory["id"], wave["id"], headers=PLANNER))
        assert aborted["status"] == c.WAVE_ABORTED
        assert aborted["deployed_vehicle_count"] == 0
        assert read_vehicle(api, stack["vehicles"][0]["id"])["status"] == c.VEHICLE_AT_DEPOT


class TestDemandSignalUpsert:
    """Publishing for an existing window replaces the row, it does not append."""

    def test_repeated_publish_replaces_rather_than_duplicates(self, api):
        """A second publish for the same window leaves one signal row.

        PRD 3.3: "Publishing for a window code that already has a signal replaces
        it rather than creating a second row for the same window."

        Design: Corner/endpoints/if_match_wave_dispatch_partial_selection_semantics
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        territory = stack["territory"]
        bind_demand_signal(api, territory["id"], projected_rides=50, manual_only_rides=10)
        updated = bind_demand_signal(api, territory["id"], projected_rides=70,
                                     manual_only_rides=10)

        rows = get_success_data(api.list_territory_demand_signals(territory["id"], headers=PLANNER))
        assert len(rows) == 1
        assert updated["effective_demand"] == 60
        assert rows[0]["effective_demand"] == 60
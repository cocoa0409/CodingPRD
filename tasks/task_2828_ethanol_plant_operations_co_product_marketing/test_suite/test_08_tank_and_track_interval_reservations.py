"""
Two deliberately opposite interval conventions over the same clock.

Track windows are half-open and judged in the aggregate, so adjacency is free
while an overlapping extra railcar overflows; tank occupancy is a closed
interval pushed out by a settling buffer, so touching endpoints conflict.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_instant_equals, assert_null, ids_of
from test_helpers.test_users import LOGISTICS_COORDINATOR, PROCESS_OPERATOR


def _track_with_two_adjacent_full_trains(api):
    """TRK-A carrying two 110-car trains in adjacent, non-overlapping windows."""
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=900000.00, settling_buffer_minutes=120,
    )
    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    first = fx.schedule_shipment(
        api, track["id"], tank["id"], track["version"],
        shipment_code="UT-A", destination_terminal="Chicago Rail Terminal",
        railcar_count=110, gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    after_first = get_success_data(api.get_track(track["id"], LOGISTICS_COORDINATOR))
    second = fx.schedule_shipment(
        api, track["id"], tank["id"], after_first["version"],
        shipment_code="UT-B", destination_terminal="Kansas City Terminal",
        railcar_count=110, gallons_per_railcar=2659.00,
        window_start="2026-09-05T12:00:00Z", window_end="2026-09-05T18:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"tank": tank, "track": track, "first": first, "second": second}


def _tank_reserved_until_two_in_the_afternoon(api):
    """BL-1 reserves T-301 from 08:00 through 14:00 once the 120-minute buffer is added."""
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    neat = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=500000.00)
    denaturant = fx.commission_tank(api, "T-201", "DENATURANT", 600000.00, opening_gallons=500000.00)
    e100 = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=0.00, settling_buffer_minutes=120,
    )
    blend = fx.schedule_blend(
        api, neat["id"], denaturant["id"], e100["id"], e100["version"],
        blend_code="BL-1", neat_gallons=2565.00, denaturant_gallons=60.00,
        window_start="2026-09-04T08:00:00Z", window_end="2026-09-04T12:00:00Z",
    )
    after = get_success_data(api.get_tank(e100["id"], PROCESS_OPERATOR))
    return {
        "neat": neat,
        "denaturant": denaturant,
        "e100": e100,
        "blend": blend,
        "tank_version": after["version"],
    }


def _blend_body(scenario, blend_code, window_start, window_end):
    return {
        "blend_code": blend_code,
        "neat_source_tank_id": scenario["neat"]["id"],
        "denaturant_source_tank_id": scenario["denaturant"]["id"],
        "destination_tank_id": scenario["e100"]["id"],
        "expected_destination_tank_version": scenario["tank_version"],
        "neat_gallons": 2565.00,
        "denaturant_gallons": 60.00,
        "window_start": window_start,
        "window_end": window_end,
    }


class TestTrackHalfOpenWindows:
    """Adjacency is free on a shared track; overlap is not."""

    def test_a_train_beginning_exactly_when_another_ends_overlaps_nothing(self, api):
        """Two full 110-car trains stand back to back for a committed total of 220.

        PRD 3.6: "Two windows overlap when the first starts strictly before the
        second ends **and** the second starts strictly before the first ends,
        which means adjacency does **not** overlap — a window beginning exactly
        when another ends is a separate spot."

        Design: Difficulty/resource_temporal_overlap/track_half_open_windows_adjacent_ok_but_aggregate_capacity_overflow_rejected
        """
        scenario = _track_with_two_adjacent_full_trains(api)

        assert scenario["second"]["loading_status"] == "SCHEDULED", scenario["second"]["loading_status"]
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 220, track["committed_railcars"]

    def test_one_railcar_inside_the_first_window_overflows_the_shared_capacity(self, api):
        """The overlap sum is 111 against 110 spots, and the refusal changes nothing.

        PRD 3.6: "Capacity is then judged in the aggregate rather than
        exclusively: sum the `railcar_count` of every shipment on the same track
        whose `loading_status` is `SCHEDULED`, `BLOCKED` or `LOADED` and whose
        window overlaps the candidate's, add the candidate's own `railcar_count`,
        and accept the schedule when that total is **at most** the track's
        `spot_capacity` — the bound is inclusive, so landing exactly on capacity
        is accepted."

        Design: Difficulty/resource_temporal_overlap/track_half_open_windows_adjacent_ok_but_aggregate_capacity_overflow_rejected
        """
        scenario = _track_with_two_adjacent_full_trains(api)
        before = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))

        validate_error(
            api.create_shipment(
                {
                    "shipment_code": "UT-C",
                    "track_id": scenario["track"]["id"],
                    "expected_track_version": before["version"],
                    "source_tank_id": scenario["tank"]["id"],
                    "destination_terminal": "Omaha Terminal",
                    "railcar_count": 1,
                    "gallons_per_railcar": 2659.00,
                    "window_start": "2026-09-05T11:00:00Z",
                    "window_end": "2026-09-05T12:00:00Z",
                    "price_cents_per_gallon": 181.50,
                },
                LOGISTICS_COORDINATOR,
            ),
            ApiErrorId.TRACK_CAPACITY_EXCEEDED,
            422,
        )

        after = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert after["committed_railcars"] == 220, after["committed_railcars"]
        assert after["version"] == before["version"], (
            "a refused schedule must not increment the track version"
        )

        rows, _meta = validate_paginated(
            api.list_shipments(LOGISTICS_COORDINATOR, {"track_id": scenario["track"]["id"]})
        )
        assert ids_of(rows) == [scenario["first"]["id"], scenario["second"]["id"]], ids_of(rows)


class TestTankClosedOccupancyInterval:
    """The settling buffer extends the reservation, and touching it is a conflict."""

    def test_a_blend_starting_on_the_occupancy_end_is_refused(self, api):
        """14:00 is the occupancy end itself, and the closed interval includes it.

        PRD 3.5: "Two intervals conflict when the candidate's start is at or
        before an existing blend's occupancy end **and** that existing blend's
        start is at or before the candidate's occupancy end — which means
        **touching endpoints do conflict**."

        Design: Difficulty/resource_temporal_overlap/tank_closed_interval_with_settling_buffer_rejects_touching_reservation
        """
        scenario = _tank_reserved_until_two_in_the_afternoon(api)
        assert_instant_equals(
            scenario["blend"]["occupancy_end"], "2026-09-04T14:00:00Z", "occupancy_end"
        )

        validate_error(
            api.create_blend(
                _blend_body(scenario, "BL-2", "2026-09-04T14:00:00Z", "2026-09-04T16:00:00Z"),
                PROCESS_OPERATOR,
            ),
            ApiErrorId.TANK_OCCUPANCY_CONFLICT,
            422,
        )

        rows, _meta = validate_paginated(
            api.list_tank_blends(scenario["e100"]["id"], PROCESS_OPERATOR, {"status": "SCHEDULED"})
        )
        assert ids_of(rows) == [scenario["blend"]["id"]], ids_of(rows)

        tank = get_success_data(api.get_tank(scenario["e100"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 0.00, "current_gallons")

    def test_a_blend_starting_one_minute_later_clears_the_buffer(self, api):
        """14:01 is outside the closed interval, so the reservation is granted.

        PRD 3.5: "Concretely, on a tank with a 120-minute settling buffer, a
        blend whose window ends at noon occupies the tank through 14:00, so a
        second blend starting at exactly 14:00 conflicts while one starting at
        14:01 does not."

        Design: Difficulty/resource_temporal_overlap/tank_closed_interval_with_settling_buffer_rejects_touching_reservation
        """
        scenario = _tank_reserved_until_two_in_the_afternoon(api)

        granted = validate_success(
            api.create_blend(
                _blend_body(scenario, "BL-3", "2026-09-04T14:01:00Z", "2026-09-04T16:00:00Z"),
                PROCESS_OPERATOR,
            ),
            201,
        )
        assert granted["status"] == "SCHEDULED", granted["status"]
        assert_instant_equals(granted["occupancy_end"], "2026-09-04T18:00:00Z", "occupancy_end")

        first = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert first["status"] == "SCHEDULED", first["status"]
        assert_null(first["executed_at"], "executed_at")

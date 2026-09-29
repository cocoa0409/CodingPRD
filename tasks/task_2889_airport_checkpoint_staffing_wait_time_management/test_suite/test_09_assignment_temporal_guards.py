"""Assignment guards: half-open officer overlap, closed lane occupancy, priority.

Covers PRD section 3.3 - the officer overlap rule is half-open while the per-lane
occupancy rule is closed, the rest buffer is conditional on a run passing the
hour, and the certification guard outranks both temporal checks.
"""

from test_helpers import (
    PLANNER_HEADERS,
    ApiErrorId,
    assert_officer_ledger,
    assert_plan_cost,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1030,
    BAND_1100,
    BAND_1130,
    Scenario,
)


def _assign(scenario: Scenario, lane_id: str, officer_id: str, band_id: str):
    return scenario.api.create_lane_assignment(
        f.lane_assignment_payload(scenario.plan_id, lane_id, officer_id, band_id),
        PLANNER_HEADERS,
    )


def _rows(scenario: Scenario, **params) -> list:
    rows, _meta = validate_paginated(
        scenario.api.list_lane_assignments(PLANNER_HEADERS, params)
    )
    return rows


def _two_lane_band_grid(base: Scenario) -> Scenario:
    """Two unequipped lanes, officer Ada, four consecutive bands, one DRAFT plan."""
    base.lane = base.create_lane(position_index=1)
    base.extras["second_lane"] = base.create_lane(position_index=2)
    base.build_officer()
    base.extras["grid_bands"] = [
        base.create_band(start) for start in (BAND_1000, BAND_1030, BAND_1100, BAND_1130)
    ]
    base.band = base.extras["grid_bands"][0]
    base.plan = base.create_plan()
    base.extras["first_row"] = base.create_assignment(band_id=base.band["id"])
    return base


class TestOfficerOverlapIsHalfOpen:
    """PRD 3.3 - adjacent bands touch without overlapping on the officer axis."""

    def test_adjacent_bands_are_accepted_while_a_repeat_band_is_double_booked(
        self, base: Scenario
    ):
        """A band ending at 10:30 and one starting at 10:30 are not an overlap.

        Design: Difficulty/resource_temporal_overlap/officer_band_overlap_half_open_with_conditional_rest_buffer
        """
        scenario = _two_lane_band_grid(base)
        bands = scenario.extras["grid_bands"]
        second_lane = scenario.extras["second_lane"]

        adjacent = validate_success(
            _assign(scenario, scenario.lane_id, scenario.officer_id, bands[1]["id"]), 201
        )
        assert adjacent["assignment_state"] == "SCHEDULED"

        validate_error(
            _assign(scenario, second_lane["id"], scenario.officer_id, bands[0]["id"]),
            ApiErrorId.OFFICER_DOUBLE_BOOKED,
            409,
        )

    def test_the_rest_buffer_only_fires_once_the_run_passes_the_hour(self, base: Scenario):
        """A third adjacent band needs a fifteen-minute gap; a 30-minute gap clears it.

        Design: Difficulty/resource_temporal_overlap/officer_band_overlap_half_open_with_conditional_rest_buffer
        """
        scenario = _two_lane_band_grid(base)
        bands = scenario.extras["grid_bands"]
        second_lane = scenario.extras["second_lane"]
        validate_success(
            _assign(scenario, scenario.lane_id, scenario.officer_id, bands[1]["id"]), 201
        )

        # The 10:00-10:30 and 10:30-11:00 run is exactly one hour, so extending it
        # with the 11:00 band would pass the hour without any separation at all.
        validate_error(
            _assign(scenario, second_lane["id"], scenario.officer_id, bands[2]["id"]),
            ApiErrorId.OFFICER_REST_BUFFER_REQUIRED,
            409,
        )

        cleared = validate_success(
            _assign(scenario, second_lane["id"], scenario.officer_id, bands[3]["id"]), 201
        )
        assert cleared["assignment_state"] == "SCHEDULED"

        officer = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert_officer_ledger(officer, committed_duty_minutes=90)
        assert len(_rows(scenario, officer_id=scenario.officer_id)) == 3
        assert len(_rows(scenario, lane_id=second_lane["id"])) == 1


def _single_position_lane(base: Scenario) -> Scenario:
    """One lane admitting a single concurrent officer, two officers, three bands."""
    base.lane = base.create_lane(position_index=3, max_concurrent_officers=1)
    base.build_officer()
    base.extras["second_officer"] = base.create_officer(
        badge_number="B-1005",
        full_name="Bea Ridge",
        certifications=["STANDARD_LANE"],
        base_rate_cents_per_minute=100,
        weekly_regular_minutes_cap=45,
        weekly_overtime_minutes_cap=600,
    )
    base.extras["grid_bands"] = [
        base.create_band(start) for start in (BAND_1000, BAND_1030, BAND_1100)
    ]
    base.band = base.extras["grid_bands"][0]
    base.plan = base.create_plan()
    base.create_assignment(band_id=base.band["id"])
    return base


class TestLaneOccupancyIsClosed:
    """PRD 3.3 - the lane side takes band intervals as closed, endpoints included."""

    def test_two_bands_sharing_an_endpoint_contend_for_the_same_lane_minute(
        self, base: Scenario
    ):
        """A second officer at 10:30 breaches a lane admitting one concurrent officer.

        Design: Difficulty/resource_temporal_overlap/lane_position_capacity_closed_interval_rejects_shared_endpoint
        """
        scenario = _single_position_lane(base)
        bands = scenario.extras["grid_bands"]

        validate_error(
            _assign(
                scenario,
                scenario.lane_id,
                scenario.extras["second_officer"]["id"],
                bands[1]["id"],
            ),
            ApiErrorId.LANE_POSITION_CAPACITY_EXCEEDED,
            409,
        )

    def test_a_clear_gap_at_the_lane_admits_the_second_officer(self, base: Scenario):
        """The 11:00 band shares no endpoint with the 10:00 band and is accepted.

        Design: Difficulty/resource_temporal_overlap/lane_position_capacity_closed_interval_rejects_shared_endpoint
        """
        scenario = _single_position_lane(base)
        bands = scenario.extras["grid_bands"]
        second_officer = scenario.extras["second_officer"]

        accepted = validate_success(
            _assign(scenario, scenario.lane_id, second_officer["id"], bands[2]["id"]), 201
        )
        assert accepted["assignment_state"] == "SCHEDULED"

        for officer_id in (scenario.officer_id, second_officer["id"]):
            officer = validate_success(
                scenario.api.get_officer(officer_id, PLANNER_HEADERS)
            )
            assert_officer_ledger(officer, committed_duty_minutes=30)
        assert len(_rows(scenario, lane_id=scenario.lane_id)) == 2

        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert_plan_cost(
            priced,
            subtotal_cents=6000,
            admin_fee_rate="0.045",
            admin_fee_cents=270,
            total_cost_cents=6270,
            planned_regular_minutes=60,
        )


def _mixed_modality_floor(base: Scenario) -> Scenario:
    """A standard and an expedited lane, two officers, both already on the standard lane."""
    base.lane = base.create_lane(position_index=1, lane_type="STANDARD")
    base.extras["expedited_lane"] = base.create_lane(
        position_index=2, lane_type="EXPEDITED", max_concurrent_officers=2
    )
    base.build_officer()
    base.extras["expedited_officer"] = base.create_officer(
        badge_number="B-1003",
        full_name="Bea Ridge",
        certifications=["STANDARD_LANE", "EXPEDITED_LANE"],
        base_rate_cents_per_minute=100,
        weekly_regular_minutes_cap=45,
        weekly_overtime_minutes_cap=600,
    )
    base.band = base.create_band(BAND_1000)
    base.plan = base.create_plan()
    base.create_assignment(officer_id=base.officer_id)
    base.create_assignment(officer_id=base.extras["expedited_officer"]["id"])
    return base


class TestCertificationOutranksTemporalGuards:
    """PRD 2.8 and 3.3 - certification is priority 15 and the overlap check is 22."""

    def test_an_uncertified_officer_is_refused_before_the_double_booking_check(
        self, base: Scenario
    ):
        """Ada is both uncertified for the lane and already booked on that band.

        Design: Difficulty/priority_pair_validation_conflict/assignment_certification_outranks_officer_double_booked
        """
        scenario = _mixed_modality_floor(base)

        validate_error(
            _assign(
                scenario,
                scenario.extras["expedited_lane"]["id"],
                scenario.officer_id,
                scenario.band["id"],
            ),
            ApiErrorId.OFFICER_NOT_CERTIFIED,
            422,
        )

    def test_a_certified_officer_reaches_the_double_booking_check(self, base: Scenario):
        """Bea holds EXPEDITED_LANE, so the lower-priority temporal guard is what fires.

        Design: Difficulty/priority_pair_validation_conflict/assignment_certification_outranks_officer_double_booked
        """
        scenario = _mixed_modality_floor(base)
        expedited_lane = scenario.extras["expedited_lane"]
        expedited_officer = scenario.extras["expedited_officer"]

        validate_error(
            _assign(
                scenario, expedited_lane["id"], expedited_officer["id"], scenario.band["id"]
            ),
            ApiErrorId.OFFICER_DOUBLE_BOOKED,
            409,
        )

        # Neither rejection wrote anything: both original rows and both ledgers hold.
        for officer_id in (scenario.officer_id, expedited_officer["id"]):
            officer = validate_success(
                scenario.api.get_officer(officer_id, PLANNER_HEADERS)
            )
            assert_officer_ledger(officer, committed_duty_minutes=30)
        for row in _rows(scenario, lane_id=scenario.lane_id):
            assert row["assignment_state"] == "SCHEDULED"
        assert _rows(scenario, lane_id=expedited_lane["id"]) == []

        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert_plan_cost(
            priced,
            subtotal_cents=6000,
            admin_fee_rate="0.045",
            admin_fee_cents=270,
            total_cost_cents=6270,
        )

"""Attraction coverage, lifeguard rotation discipline, and shift precondition gates."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_rotating_a_staffer_leaves_the_attraction_short_of_its_floor(api, platform_ops_headers,
                                                                    aquatics_manager_headers):
    """PRD §3.6: "The shift moves to `ROTATED`, and crucially the linked
    attraction's status is left unchanged, because a rotated staffer still counts
    as covering the attraction for the purposes of the coverage calculation."
    PRD §3.6: "An attraction whose `min_occupancy_units` exceeds 1 can never leave
    `LIMITED` while staffed, because a single attraction posts at most one staffer
    at a time, so its count can never reach a floor above 1."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort, attraction, shift = fx.setup_attraction_with_staffer(
        min_occupancy_units=2, required_certification="NONE",
        start_minute=540, end_minute=660, rotation_minutes=60,
    )
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    rotated = validate_success(
        api.rotate_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers)
    )
    assert rotated["shift_status"] == "ROTATED"
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "LIMITED"


def test_completing_a_shift_moves_the_attraction_down_to_limited(api, platform_ops_headers,
                                                                aquatics_manager_headers):
    """PRD §3.6: "And the operation that completes a shift recomputes the
    attraction downward as well as upward: an attraction becomes `LIMITED` while a
    rostered staffer remains under the daily cap, and `CLOSED` once every rostered
    staffer has reached it."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort, attraction, shift = fx.setup_attraction_with_staffer(
        min_occupancy_units=1, required_certification="NONE"
    )
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    completed = validate_success(
        api.complete_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers)
    )
    assert completed["shift_status"] == "COMPLETED"
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "LIMITED"


def test_an_unrostered_staffer_opens_nothing(api, platform_ops_headers, aquatics_manager_headers):
    """PRD §3.6: "A staffer counts toward an attraction's coverage only when the
    roster carries an entry equal to that staffer's role-prefixed name for the
    shift in question. Staffers who are scheduled but not rostered do not open
    anything."
    PRD §3.6: "A count of 0 makes it `LIMITED` when at least one rostered staffer
    for that date has not yet exhausted their daily cap, and `CLOSED` when every
    rostered staffer has."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=10)
    fx.add_manager(resort["id"], "Dana")
    attraction = fx.create_attraction(
        resort["id"], min_occupancy_units=1, required_certification="NONE"
    )
    shift = fx.create_shift(resort["id"], attraction["id"], "Unlisted")
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "LIMITED"


def test_a_shift_abutting_a_completed_one_breaches_the_rotation_buffer(
    api, aquatics_manager_headers
):
    """PRD §3.6: "Third, every already-`COMPLETED` shift for the same staffer on
    the same date must be separated from this shift's window by at least the
    rotation buffer constant of 30 minutes; in other words, a staffer coming off a
    completed shift needs a full half-hour of rest before the next posting begins."

    Design: Difficulty/resource_temporal_overlap/lifeguard_rotation_buffer_breach_rejected
    """
    resort, attraction, _completed = fx.setup_attraction_with_completed_shift(
        staffer_name="Iris", start_minute=540, end_minute=660, rotation_minutes=120
    )
    fresh = validate_success(
        api.create_lifeguard_shift(
            resort["id"],
            {
                "attraction_id": attraction["id"],
                "staffer_name": "Iris",
                "certification_code": "LIFEGUARD",
                "shift_date": "2026-09-03",
                "start_minute": 600,
                "end_minute": 720,
                "rotation_minutes": 120,
            },
            aquatics_manager_headers,
        ),
        201,
    )
    response = api.start_lifeguard_shift(resort["id"], fresh["id"], aquatics_manager_headers)
    assert response.status_code >= 400
    validate_error(response, ApiErrorId.ERR_SHIFT_ROTATION_VIOLATION.value)


def test_a_shift_wider_than_its_rotation_allowance_plus_two_hours_is_refused(
    api, aquatics_manager_headers
):
    """PRD §3.6: "Second, the shift's own duration — `end_minute` minus
    `start_minute` — may not exceed `rotation_minutes` plus the maximum consecutive
    minutes constant of 120; expressed in hours, a shift may not be posted for
    longer than its rotation allowance plus two hours, so a shift with a 60-minute
    rotation allowance may run at most three hours."

    Design: Difficulty/resource_temporal_overlap/lifeguard_rotation_buffer_breach_rejected
    """
    resort, attraction, _shift = fx.setup_attraction_with_staffer(
        min_occupancy_units=1, required_certification="NONE",
        start_minute=540, end_minute=660, rotation_minutes=60,
    )
    over_long = validate_success(
        api.create_lifeguard_shift(
            resort["id"],
            {
                "attraction_id": attraction["id"],
                "staffer_name": "Kai",
                "certification_code": "LIFEGUARD",
                "shift_date": "2026-09-03",
                "start_minute": 540,
                "end_minute": 780,
                "rotation_minutes": 60,
            },
            aquatics_manager_headers,
        ),
        201,
    )
    response = api.start_lifeguard_shift(resort["id"], over_long["id"], aquatics_manager_headers)
    validate_error(response, ApiErrorId.ERR_SHIFT_ROTATION_VIOLATION.value)


def test_an_uncertified_staffer_cannot_start_a_lifeguard_attraction(
    api, aquatics_manager_headers
):
    """PRD §3.6: "The shift must be `SCHEDULED`, and the staffer's
    `certification_code` must equal the target attraction's `required_certification`
    — an uncertified staffer cannot be posted to an attraction that requires a
    lifeguard, and an attempt is refused with `ERR_SHIFT_ROTATION_VIOLATION` (HTTP
    409)."

    Design: Corner/errors/shifted_start_missing_certification_rejected
    """
    resort = fx.create_resort(park_capacity_occupancy_units=20, day_pass_cap_units=10)
    fx.add_manager(resort["id"], "Ada")
    attraction = fx.create_attraction(
        resort["id"], required_certification="LIFEGUARD", min_occupancy_units=1
    )
    shift = validate_success(
        api.create_lifeguard_shift(
            resort["id"],
            {
                "attraction_id": attraction["id"],
                "staffer_name": "Ada",
                "certification_code": "NONE",
                "shift_date": "2026-09-03",
                "start_minute": 540,
                "end_minute": 660,
                "rotation_minutes": 60,
            },
            aquatics_manager_headers,
        ),
        201,
    )
    response = api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers)
    validate_error(response, ApiErrorId.ERR_SHIFT_ROTATION_VIOLATION.value)
    assert validate_success(
        api.get_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers)
    )["shift_status"] == "SCHEDULED"


def test_admission_is_refused_to_an_unstaffed_attraction(api, gate_attendant_headers):
    """PRD §2.4: "attraction readiness (`ERR_ATTRACTION_NOT_OPEN`, guarding gate admission posting and activity-session creation); physical plausibility of a submitted water reading (`ERR_WATER_QUALITY_OUT_OF_RANGE`); cabana overlap and capacity (`ERR_CABANA_DOUBLE_BOOKED` and `ERR_CABANA_UNITS_UNAVAILABLE`); the day-pass ceiling (`ERR_DAY_PASS_CAP_EXCEEDED`); the park capacity ceiling (`ERR_PARK_CAPACITY_EXCEEDED`); the arcade ceiling (`ERR_ARCADE_LIMIT_EXCEEDED`); the birthday-party minimum (`ERR_GROUP_MINIMUM_NOT_MET`); and finally the deposit requirement together with gateway acceptance (`ERR_PAYMENT_DECLINED`)."

    Design: Corner/validations/admission_refused_to_unstaffed_attraction
    """
    resort, _attraction, _reservation, band = fx.setup_active_guest_band(
        guest_count=2, clock_iso="2026-09-03T09:00:00Z"
    )
    fx.add_manager(resort["id"], "Tamarin Keeper")
    unstaffed = fx.create_attraction(
        resort["id"], name="Tamarin Trail", required_certification="LIFEGUARD"
    )
    assert unstaffed["attraction_status"] == "CLOSED"
    response = api.post_admission(
        resort["id"],
        {"wristband_id": band["id"], "service_date": "2026-09-03", "direction": "IN"},
        gate_attendant_headers,
    )
    validate_error(response, ApiErrorId.ERR_ATTRACTION_NOT_OPEN.value)


@pytest.mark.parametrize("bad_window", [{"start_minute": 1440, "end_minute": 1440},
                                        {"start_minute": 600, "end_minute": 600}])
def test_an_inverted_or_out_of_range_shift_window_is_refused(api, aquatics_manager_headers,
                                                             bad_window):
    """PRD §3.6: "a `start_minute` in minutes after midnight that must be at least 0
    and at most 1439, an `end_minute` that must be greater than `start_minute` and
    at most 1440, and a `rotation_minutes` maximum of at least 1."

    Design: Corner/errors/shifted_start_missing_certification_rejected
    """
    resort, attraction, _shift = fx.setup_attraction_with_staffer(min_occupancy_units=1)
    response = api.create_lifeguard_shift(
        resort["id"],
        {
            "attraction_id": attraction["id"],
            "staffer_name": "Moe",
            "certification_code": "LIFEGUARD",
            "shift_date": "2026-09-03",
            "rotation_minutes": 60,
            **bad_window,
        },
        aquatics_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_reading_a_shift_window_contains_blocks_resumption(api, aquatics_manager_headers):
    """PRD §3.6: "Resuming from a rotation requires `ROTATED` status, requires that
    no other shift for the same staffer and date be `ON_DUTY` with an overlapping
    window, and adds a safety condition belonging to the water itself: every water
    reading already recorded for the linked attraction within the shift's
    `[start_minute, end_minute)` window on its `shift_date` must carry a
    `log_status` of `PASS`. A staffer may not resume posting to water that has
    failed a reading."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort, attraction, shift = fx.setup_attraction_with_staffer(
        min_occupancy_units=1, required_certification="NONE"
    )
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    validate_success(api.rotate_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T10:00:00Z", ph_reading=6.0
    )
    response = api.resume_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers)
    assert response.status_code >= 400, "a staffer may not resume posting to water that has failed a reading"
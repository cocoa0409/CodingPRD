"""Absence grading: the wait-time boundary and the program weighting."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    read_trip,
    set_clock,
    setup_absence_scenario,
    validate_error,
    validate_success,
)


def test_absence_report_at_exactly_twelve_minutes_is_refused():
    """PRD §3.8: "Wait time is measured in twelve-minute blocks: the elapsed
    whole minutes between the logical clock instant and the trip's arrival are
    divided into blocks, where an elapsed time of twelve minutes or less is
    still the first block, each further full twelve-minute span adds one block".
    PRD §3.8: "the trip's accrued wait-time block count must have reached the
    two-block minimum, and an early report is refused with
    `ERR_WAIT_TIME_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/absence_wait_boundary_at_exactly_two_blocks
    """
    scenario = setup_absence_scenario()
    headers = scenario["driver_headers"]

    set_clock("2026-09-10T07:42:00Z")
    resp = api_client.report_exception(
        scenario["trip"]["id"],
        {"issue": "RIDER_NOT_PRESENT", "note": "exactly twelve minutes"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_WAIT_TIME_NOT_MET)

    trip = read_trip(scenario["trip"]["id"])
    assert trip["trip_state"] == "AWAITING_STUDENT", (
        "a refused report must not cancel the trip"
    )
    assert trip["exception_code"] is None


def test_absence_report_at_exactly_twenty_four_minutes_is_accepted():
    """PRD §3.8: "an elapsed time of twelve minutes or less is still the first
    block, each further full twelve-minute span adds one block, elapsed time
    before arrival counts as no block at all, and the count is capped at five
    blocks."
    PRD §3.8: "Reporting is also gated on wait time: the trip's accrued wait-time
    block count must have reached the two-block minimum".

    Design: Difficulty/boundary_precision_check/absence_wait_boundary_at_exactly_two_blocks
    """
    scenario = setup_absence_scenario()
    headers = scenario["driver_headers"]

    set_clock("2026-09-10T07:54:00Z")
    validate_success(
        api_client.report_exception(
            scenario["trip"]["id"],
            {"issue": "RIDER_NOT_PRESENT", "note": "exactly twenty-four minutes"},
            headers,
        ),
        201,
    )

    trip = read_trip(scenario["trip"]["id"])
    assert trip["trip_state"] == "CANCELLED"
    assert trip["exception_code"] == "RIDER_NOT_PRESENT"
    assert trip["exception_recorded_at"] is not None
    assert trip["safety_state"] == "LOCKED", (
        "the accepted report grades HIGH and locks the safety posture"
    )


def test_wait_boundary_report_opens_the_student_absent_alert_and_strikes():
    """PRD §3.8: "A `HIGH` grade additionally costs the driver a strike on the
    spot; if that strike pushes the driver's strike count to the three-strike
    suspension threshold, the driver's automatic suspension cascade runs and
    cancels every other `SCHEDULED` trip for that driver."

    Design: Difficulty/boundary_precision_check/absence_wait_boundary_at_exactly_two_blocks
    """
    scenario = setup_absence_scenario()
    headers = scenario["driver_headers"]

    set_clock("2026-09-10T07:54:00Z")
    validate_success(
        api_client.report_exception(
            scenario["trip"]["id"],
            {"issue": "RIDER_NOT_PRESENT", "note": "exactly twenty-four minutes"},
            headers,
        ),
        201,
    )

    driver = read_driver(scenario["driver"]["id"])
    assert driver["incident_strike_count"] == 1, (
        "a HIGH grade consumes one strike while the incident itself is unresolved"
    )

    incidents = get_success_data(
        api_client.list_trip_safety_incidents(
            scenario["trip"]["id"], TEST_USERS["support_center_headers"]
        )
    )
    assert len(incidents) == 1
    assert incidents[0]["category"] == "NO_SHOW_UNVERIFIED"
    assert incidents[0]["severity"] == "HIGH"
    assert incidents[0]["status"] == "REPORTED"
    assert incidents[0]["adjudication"] is None

    alerts = get_success_data(
        api_client.list_trip_alerts(
            scenario["trip"]["id"], TEST_USERS["support_center_headers"]
        )
    )
    assert [alert["alert_type"] for alert in alerts] == ["STUDENT_ABSENT"]


def test_two_block_wait_consumes_exactly_one_strike():
    """PRD §3.9: "That second term is why a `HIGH` absence costs an on-the-spot
    strike: the absence incident opened by the exception report carries no
    adjudication until a support agent resolves it, and the trip itself — locked
    by the `HIGH` grade — is what contributes the strike immediately."
    PRD §3.8: "A `HIGH` grade additionally costs the driver a strike on the
    spot".

    Design: Difficulty/dual_variant_calc/absence_grade_under_program_weights_and_flat_program_variants
    """
    scenario = setup_absence_scenario()
    headers = scenario["driver_headers"]
    assert read_driver(scenario["driver"]["id"])["incident_strike_count"] == 0

    set_clock("2026-09-10T07:54:00Z")
    validate_success(
        api_client.report_exception(
            scenario["trip"]["id"],
            {"issue": "RIDER_REFUSED_BOARDING", "note": "two blocks of wait"},
            headers,
        ),
        201,
    )

    driver = read_driver(scenario["driver"]["id"])
    assert driver["incident_strike_count"] == 1, (
        "one HIGH absence consumes one strike, never two"
    )
    assert driver["status"] == "ACTIVE", (
        "one strike is below the three-strike suspension threshold"
    )
    assert read_trip(scenario["trip"]["id"])["exception_code"] == "RIDER_REFUSED_BOARDING"


def test_weighted_absence_grade_locks_the_trip_while_a_flat_weight_would_not():
    """PRD §3.8: "The grade is driven by the student's program type, the accrued
    wait blocks and the student's priority level, weighted by whether the
    dispatch was late."
    PRD §3.8: "Students in `FOSTER_CARE` and `HOMELESS_MCKINNEY_VENTO`
    placements weigh most heavily, students in `SPECIAL_EDUCATION` weigh more
    than general-education students".
    PRD §3.8: "at least eight points grade `HIGH`, at least four but fewer than
    eight grade `MEDIUM`, and fewer than four grade `LOW`."

    Design: Difficulty/dual_variant_calc/absence_grade_under_program_weights_and_flat_program_variants
    """
    scenario = setup_absence_scenario(program_type="FOSTER_CARE", spi_level=1)
    headers = scenario["driver_headers"]

    set_clock("2026-09-10T07:54:00Z")
    validate_success(
        api_client.report_exception(
            scenario["trip"]["id"],
            {"issue": "RIDER_NOT_PRESENT", "note": "weighted grade"},
            headers,
        ),
        201,
    )

    trip = read_trip(scenario["trip"]["id"])
    assert trip["safety_state"] == "LOCKED", (
        "the weighted grade clears the eight-point HIGH threshold"
    )
    assert trip["trip_state"] == "CANCELLED"

    # A general-education student on the identical two-block wait, with an
    # on-time dispatch (the window closes after the reporting instant), grades
    # below the medium threshold, so the same report leaves the posture NORMAL.
    flat = setup_absence_scenario(
        program_type="GENERAL", spi_level=1,
        window_end_at="2026-09-10T08:00:00Z",
    )
    set_clock("2026-09-10T07:54:00Z")
    validate_success(
        api_client.report_exception(
            flat["trip"]["id"],
            {"issue": "RIDER_NOT_PRESENT", "note": "flat grade"},
            flat["driver_headers"],
        ),
        201,
    )
    flat_trip = read_trip(flat["trip"]["id"])
    assert flat_trip["trip_state"] == "CANCELLED"
    assert flat_trip["safety_state"] == "NORMAL", (
        "a low grade leaves the safety posture NORMAL"
    )
    assert read_driver(flat["driver"]["id"])["incident_strike_count"] == 0, (
        "only a HIGH grade consumes a strike"
    )
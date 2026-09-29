"""Flight-log compliance summaries and the enforcement risk score.

Covers the half-open reporting window of the pilot flight summary — which flights
enter the source set and which field the window keys on — and the weighted risk
score that suspends a pilot the moment it reaches the enforcement threshold.
"""

from test_helpers import (
    DEFAULT_LIMIT,
    FlightStatus,
    InjuryLevel,
    OperationCategory,
    OperatorCategory,
    PilotStatus,
    PreflightResult,
    RegistrationStatus,
    SystemGroundingReason,
    ZoneClassCode,
    assert_flight,
    assert_flight_summary,
    assert_instant_equals,
    assert_pagination_meta,
    factories,
    fixtures,
    make_pilot_headers,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# The reporting window: inclusive lower bound, exclusive upper bound
# ---------------------------------------------------------------------------

WINDOW_SETUP_CLOCK = "2026-08-05T00:00:00Z"
WINDOW_PLANNED_START = "2026-08-10T09:00:00Z"
WINDOW_PLANNED_END = "2026-08-10T10:00:00Z"
WINDOW_ACTUAL_END = "2026-08-10T10:00:00Z"
WINDOW_ONE_SECOND_LATER = "2026-08-10T10:00:01Z"
WINDOW_UPPER = "2026-08-11T00:00:00Z"
WINDOW_LOWER = "2026-08-09T00:00:00Z"
WINDOW_REPORTING_CLOCK = "2026-08-12T00:00:00Z"


def _single_completed_flight(api):
    """One certified pilot with exactly one flight flown 09:00 to 10:00 at 385 ft."""
    fixtures.set_clock(api, WINDOW_SETUP_CLOCK)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=WINDOW_SETUP_CLOCK
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=600
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=2,
    )
    fixtures.set_clock(api, WINDOW_PLANNED_START)
    flight = fixtures.create_completed_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        WINDOW_PLANNED_START,
        WINDOW_PLANNED_END,
        max_altitude_reached_ft=385,
        actual_end=WINDOW_ACTUAL_END,
        planned_max_altitude_ft=390,
    )
    fixtures.set_clock(api, WINDOW_REPORTING_CLOCK)
    return pilot, flight


def test_the_summary_counts_a_flight_ending_exactly_at_the_window_start(
    api, compliance_officer
):
    """PRD §3.7: "The source set is that pilot's flights whose `status` is `COMPLETED` and whose `actual_end` falls in the half-open window — at or after `window_start` and strictly before `window_end`."
    PRD §3.7: "From that set the response reports `completed_flight_count` (the number of flights), `total_logged_minutes` (the sum of their `logged_minutes`), `max_altitude_reached_ft` (the greatest `max_altitude_reached_ft` among them), `incident_flight_count` (how many have `incident_occurred` true), `exceedance_flight_count` (how many have `altitude_exceedance` true), `average_duration_minutes` (the `total_logged_minutes` divided by the `completed_flight_count`, rounded half-up to one decimal place), and the `window_start` and `window_end` actually applied."

    Design: Difficulty/boundary_precision_check/flight_summary_window_bounds_inclusive_start_exclusive_end_and_empty_set_zeros
    """
    pilot, flight = _single_completed_flight(api)

    summary = validate_success(
        api.get_flight_summary(
            pilot["id"],
            params={"window_start": WINDOW_ACTUAL_END, "window_end": WINDOW_UPPER},
            headers=compliance_officer,
        )
    )

    assert_flight_summary(
        summary,
        completed_flight_count=1,
        total_logged_minutes=60,
        max_altitude_reached_ft=385,
        incident_flight_count=0,
        exceedance_flight_count=0,
        average_duration_minutes=60.0,
        window_start=WINDOW_ACTUAL_END,
        window_end=WINDOW_UPPER,
    )
    assert_instant_equals(
        flight["actual_end"], WINDOW_ACTUAL_END, "the flight ends on the window's lower bound"
    )


def test_the_summary_drops_a_flight_ending_exactly_at_the_window_end(api, compliance_officer):
    """PRD §3.7: "The source set is that pilot's flights whose `status` is `COMPLETED` and whose `actual_end` falls in the half-open window — at or after `window_start` and strictly before `window_end`."
    PRD §3.7: "The empty-set behaviour is fixed and must not be improvised: when no flight qualifies, every count and total is 0, `max_altitude_reached_ft` is 0, and `average_duration_minutes` is 0.0 — never null, and never a division by zero."

    Design: Difficulty/boundary_precision_check/flight_summary_window_bounds_inclusive_start_exclusive_end_and_empty_set_zeros
    """
    pilot, _flight = _single_completed_flight(api)

    summary = validate_success(
        api.get_flight_summary(
            pilot["id"],
            params={"window_start": WINDOW_LOWER, "window_end": WINDOW_ACTUAL_END},
            headers=compliance_officer,
        )
    )

    assert_flight_summary(
        summary,
        completed_flight_count=0,
        total_logged_minutes=0,
        max_altitude_reached_ft=0,
        incident_flight_count=0,
        exceedance_flight_count=0,
        average_duration_minutes=0.0,
        window_start=WINDOW_LOWER,
        window_end=WINDOW_ACTUAL_END,
    )
    assert summary["average_duration_minutes"] == 0.0, (
        f"an empty source set reports 0.0, got {summary['average_duration_minutes']!r}"
    )


def test_one_second_of_window_movement_pulls_the_flight_in_and_out(api, compliance_officer):
    """PRD §3.7: "The source set is that pilot's flights whose `status` is `COMPLETED` and whose `actual_end` falls in the half-open window — at or after `window_start` and strictly before `window_end`."
    PRD §3.7: "The service writes all four fields, then computes `logged_minutes` as the whole minutes between `actual_start` and `actual_end`, discarding any part-minute remainder, and computes `altitude_exceedance` as true exactly when `max_altitude_reached_ft` is strictly greater than the flight's effective ceiling — the cited authorization's `granted_ceiling_ft` when the flight names one, and 400 feet otherwise."

    Design: Difficulty/boundary_precision_check/flight_summary_window_bounds_inclusive_start_exclusive_end_and_empty_set_zeros
    """
    pilot, flight = _single_completed_flight(api)

    assert_flight(
        flight,
        status=FlightStatus.COMPLETED.value,
        logged_minutes=60,
        altitude_exceedance=False,
        max_altitude_reached_ft=385,
    )

    one_second_past_the_start = validate_success(
        api.get_flight_summary(
            pilot["id"],
            params={"window_start": WINDOW_ONE_SECOND_LATER, "window_end": WINDOW_UPPER},
            headers=compliance_officer,
        )
    )
    assert_flight_summary(
        one_second_past_the_start,
        completed_flight_count=0,
        total_logged_minutes=0,
        max_altitude_reached_ft=0,
        average_duration_minutes=0.0,
    )

    one_second_past_the_end = validate_success(
        api.get_flight_summary(
            pilot["id"],
            params={"window_start": WINDOW_LOWER, "window_end": WINDOW_ONE_SECOND_LATER},
            headers=compliance_officer,
        )
    )
    assert_flight_summary(
        one_second_past_the_end,
        completed_flight_count=1,
        total_logged_minutes=60,
        max_altitude_reached_ft=385,
        average_duration_minutes=60.0,
        window_start=WINDOW_LOWER,
        window_end=WINDOW_ONE_SECOND_LATER,
    )


# ---------------------------------------------------------------------------
# The enforcement threshold: exactly 70 suspends
# ---------------------------------------------------------------------------

RISK_SETUP_CLOCK = "2026-08-05T00:00:00Z"
RISK_INCIDENT_START = "2026-08-10T09:00:00Z"
RISK_INCIDENT_END = "2026-08-10T10:00:00Z"
RISK_EXCEEDANCE_START = "2026-08-11T09:00:00Z"
RISK_EXCEEDANCE_END = "2026-08-11T10:00:00Z"
RISK_FILING_CLOCK = "2026-08-11T12:00:00Z"
RISK_OCCURRED_AT = "2026-08-10T09:50:00Z"
RISK_DAMAGE_CENTS = 120000
RISK_THRESHOLD_REASON = "RISK_THRESHOLD_REACHED"


def _risk_operation(api):
    """A commercial operator with one registered airframe over uncontrolled airspace."""
    fixtures.set_clock(api, RISK_SETUP_CLOCK)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=RISK_SETUP_CLOCK
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=2,
    )
    return pilot, aircraft, zone


def _fly_an_incident_flight(api, pilot, aircraft, zone):
    """A recreational sortie logged with an incident and well under the ceiling."""
    fixtures.set_clock(api, RISK_INCIDENT_START)
    return fixtures.create_completed_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        RISK_INCIDENT_START,
        RISK_INCIDENT_END,
        max_altitude_reached_ft=380,
        incident_occurred=True,
        actual_end=RISK_INCIDENT_END,
        operation_category=OperationCategory.RECREATIONAL.value,
        planned_max_altitude_ft=390,
    )


def _fly_an_exceedance_flight(api, pilot, aircraft, zone, incident_occurred=False):
    """A recreational sortie flown to 450 ft, above the 400 ft effective ceiling."""
    fixtures.set_clock(api, RISK_EXCEEDANCE_START)
    return fixtures.create_completed_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        RISK_EXCEEDANCE_START,
        RISK_EXCEEDANCE_END,
        max_altitude_reached_ft=450,
        incident_occurred=incident_occurred,
        actual_end=RISK_EXCEEDANCE_END,
        operation_category=OperationCategory.RECREATIONAL.value,
        planned_max_altitude_ft=400,
    )


def test_a_risk_score_of_exactly_seventy_suspends_the_pilot_on_filing(api):
    """PRD §3.9: "Then take the raw score as 25 times the incident count, plus 15 times the exceedance count, plus 30 times the open-accident count, plus a lapsed-currency term of 10 when the pilot's `status` is `LAPSED` and 0 otherwise, minus 5 times the clean-flight count."
    PRD §3.9: "Suspension fires when the recomputed `risk_score` reaches 70."
    PRD §3.9: "The comparison is inclusive: exactly 70 suspends."
    PRD §3.9: "The automatic path applies only to a pilot whose `status` is `CERTIFIED` or `LAPSED`, and it records `suspension_reason` as `RISK_THRESHOLD_REACHED`."
    PRD §3.8: "Filing also recomputes the pilot's `risk_score` and increments the pilot's `version`, and a recomputed score that reaches 70 suspends the pilot on the spot with the depth-four cascade."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_seventy_suspends_pilot_at_the_inclusive_threshold
    """
    pilot, aircraft, zone = _risk_operation(api)
    incident_flight = _fly_an_incident_flight(api, pilot, aircraft, zone)
    exceedance_flight = _fly_an_exceedance_flight(api, pilot, aircraft, zone)

    assert incident_flight["altitude_exceedance"] is False, (
        "380 ft is under the 400 ft effective ceiling, so the incident flight has no exceedance"
    )
    assert exceedance_flight["altitude_exceedance"] is True, (
        "450 ft is above the 400 ft effective ceiling, so the second flight is an exceedance"
    )

    before = fixtures.read_pilot(api, pilot["id"])
    assert before["risk_score"] == 40, (
        f"one incident flight (25) plus one exceedance flight (15) scores 40, got "
        f"{before['risk_score']}"
    )
    assert before["status"] == PilotStatus.CERTIFIED.value, (
        f"40 is below the threshold, so the pilot stays CERTIFIED, got {before['status']}"
    )

    fixtures.set_clock(api, RISK_FILING_CLOCK)
    report = fixtures.create_filed_report(
        api,
        incident_flight,
        RISK_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=RISK_DAMAGE_CENTS,
    )

    after = fixtures.read_pilot(api, pilot["id"])
    assert after["risk_score"] == 70, (
        f"25 + 15 + 30 for the open accident is exactly 70, got {after['risk_score']}"
    )
    assert after["status"] == PilotStatus.SUSPENDED.value, (
        f"exactly 70 suspends, got {after['status']} at risk_score {after['risk_score']}"
    )
    assert after["suspension_reason"] == RISK_THRESHOLD_REASON, (
        f"expected {RISK_THRESHOLD_REASON}, got {after['suspension_reason']!r}"
    )
    assert report["reserved_cents"] == 0, (
        f"a recreational flight carries no cover, so nothing is held, got "
        f"{report['reserved_cents']}"
    )
    assert report["policy_id"] is None, (
        f"the copied policy_id is null on a recreational flight, got {report['policy_id']!r}"
    )


def test_the_threshold_suspension_grounds_the_airframe_and_spares_flown_missions(
    api, compliance_officer
):
    """PRD §2.8: "The pilot moves to `SUSPENDED` and `suspension_reason` is recorded; because the pilot is suspended, every airframe they own whose `registration_status` is `REGISTERED` moves to `GROUNDED` with `grounding_reason` set to `OWNER_SUSPENDED`; because each of those airframes is now grounded, every airspace authorization bound to one of them whose `status` is `APPROVED` or `ACTIVE` moves to `REVOKED`, and each such revocation decrements that zone's `reserved_slot_count` by 1 and increments the zone's `version` by 1; and because those authorizations are revoked, every flight citing one of them whose `status` is `PLANNED` or `PREFLIGHT_CLEARED` moves to `CANCELLED` with `cancellation_reason` set to `AUTHORIZATION_REVOKED`."
    PRD §2.8: "What the cascade deliberately leaves alone matters as much as what it touches: flights already `COMPLETED` or `IN_PROGRESS` are untouched, authorizations already `DENIED`, `CONSUMED`, `REVOKED` or `EXPIRED` are untouched, and airframes still in `PENDING_REGISTRATION` are untouched."
    PRD §3.9: "The comparison is inclusive: exactly 70 suspends."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_seventy_suspends_pilot_at_the_inclusive_threshold
    """
    pilot, aircraft, zone = _risk_operation(api)
    incident_flight = _fly_an_incident_flight(api, pilot, aircraft, zone)
    exceedance_flight = _fly_an_exceedance_flight(api, pilot, aircraft, zone)

    fixtures.set_clock(api, RISK_FILING_CLOCK)
    fixtures.create_filed_report(
        api,
        incident_flight,
        RISK_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=RISK_DAMAGE_CENTS,
    )

    suspended = fixtures.read_pilot(api, pilot["id"])
    assert suspended["risk_score"] == 70, (
        f"the filing takes the score to exactly 70, got {suspended['risk_score']}"
    )

    grounded = validate_success(api.get_aircraft(aircraft["id"], headers=compliance_officer))
    assert grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        f"the owner's suspension grounds the airframe, got {grounded['registration_status']}"
    )
    assert grounded["grounding_reason"] == SystemGroundingReason.OWNER_SUSPENDED.value, (
        f"expected OWNER_SUSPENDED, got {grounded['grounding_reason']!r}"
    )

    for flown in (incident_flight, exceedance_flight):
        reread = validate_success(api.get_flight(flown["id"], headers=compliance_officer))
        assert reread["status"] == FlightStatus.COMPLETED.value, (
            f"a flown mission is untouched by the cascade, got {reread['status']}"
        )
        assert reread["cancellation_reason"] is None, (
            f"nothing cancels a COMPLETED flight, got {reread['cancellation_reason']!r}"
        )


def test_a_score_below_the_threshold_leaves_the_pilot_certified_and_flying(
    api, compliance_officer
):
    """PRD §3.9: "The open-accident count is the number of accident reports against that pilot's flights whose `status` is `FILED`, `INVESTIGATING` or `REMEDIATION_REQUIRED`; reports in `CLOSED` or `WITHDRAWN` are excluded."
    PRD §3.9: "Suspension fires when the recomputed `risk_score` reaches 70."
    PRD §3.9: "The comparison is inclusive: exactly 70 suspends."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_seventy_suspends_pilot_at_the_inclusive_threshold
    """
    pilot, aircraft, zone = _risk_operation(api)
    incident_flight = _fly_an_incident_flight(api, pilot, aircraft, zone)

    fixtures.set_clock(api, RISK_FILING_CLOCK)
    fixtures.create_filed_report(
        api,
        incident_flight,
        RISK_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=RISK_DAMAGE_CENTS,
    )

    after = fixtures.read_pilot(api, pilot["id"])
    assert after["risk_score"] == 55, (
        f"25 for the incident flight plus 30 for the open accident is 55, got "
        f"{after['risk_score']}"
    )
    assert after["status"] == PilotStatus.CERTIFIED.value, (
        f"55 does not reach 70, so no suspension fires, got {after['status']}"
    )
    assert after["suspension_reason"] is None, (
        f"an unsuspended pilot carries no reason, got {after['suspension_reason']!r}"
    )

    still_flying = validate_success(api.get_aircraft(aircraft["id"], headers=compliance_officer))
    assert still_flying["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"no suspension means no grounding, got {still_flying['registration_status']}"
    )
    assert still_flying["grounding_reason"] is None, (
        f"expected a null grounding_reason, got {still_flying['grounding_reason']!r}"
    )


def test_a_score_past_the_threshold_suspends_the_pilot_just_the_same(api):
    """PRD §3.9: "The clean-flight count is the number of that pilot's flights whose `status` is `COMPLETED` and whose `incident_occurred` and `altitude_exceedance` are **both** false."
    PRD §3.9: "Then take the raw score as 25 times the incident count, plus 15 times the exceedance count, plus 30 times the open-accident count, plus a lapsed-currency term of 10 when the pilot's `status` is `LAPSED` and 0 otherwise, minus 5 times the clean-flight count."
    PRD §3.9: "Suspension fires when the recomputed `risk_score` reaches 70."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_seventy_suspends_pilot_at_the_inclusive_threshold
    """
    pilot, aircraft, zone = _risk_operation(api)
    incident_flight = _fly_an_incident_flight(api, pilot, aircraft, zone)
    both_flight = _fly_an_exceedance_flight(api, pilot, aircraft, zone, incident_occurred=True)

    assert both_flight["incident_occurred"] is True, (
        "the second sortie is logged with an incident as well as an exceedance"
    )
    assert both_flight["altitude_exceedance"] is True, (
        f"450 ft breaches the 400 ft effective ceiling, got "
        f"{both_flight['altitude_exceedance']!r}"
    )

    before = fixtures.read_pilot(api, pilot["id"])
    assert before["risk_score"] == 65, (
        f"two incident flights (50) plus one exceedance (15) scores 65 with no clean flight to "
        f"decay it, got {before['risk_score']}"
    )
    assert before["status"] == PilotStatus.CERTIFIED.value, (
        f"65 is short of the threshold, got {before['status']}"
    )

    fixtures.set_clock(api, RISK_FILING_CLOCK)
    fixtures.create_filed_report(
        api,
        incident_flight,
        RISK_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=RISK_DAMAGE_CENTS,
    )

    after = fixtures.read_pilot(api, pilot["id"])
    assert after["risk_score"] == 95, (
        f"65 plus 30 for the open accident is 95, got {after['risk_score']}"
    )
    assert after["status"] == PilotStatus.SUSPENDED.value, (
        f"a score past 70 suspends as surely as one at 70, got {after['status']}"
    )
    assert after["suspension_reason"] == RISK_THRESHOLD_REASON, (
        f"expected {RISK_THRESHOLD_REASON}, got {after['suspension_reason']!r}"
    )


# ---------------------------------------------------------------------------
# The source set: completed missions only
# ---------------------------------------------------------------------------

MIXED_SETUP_CLOCK = "2026-10-01T00:00:00Z"
MIXED_FLOWN_START = "2026-10-02T09:00:00Z"
MIXED_FLOWN_PLANNED_END = "2026-10-02T10:00:00Z"
MIXED_FLOWN_ACTUAL_END = "2026-10-02T10:05:00Z"
MIXED_STOOD_DOWN_START = "2026-10-03T09:00:00Z"
MIXED_STOOD_DOWN_END = "2026-10-03T10:00:00Z"
MIXED_AIRBORNE_START = "2026-10-04T09:00:00Z"
MIXED_AIRBORNE_END = "2026-10-04T10:00:00Z"
MIXED_REPORTING_CLOCK = "2026-10-04T09:30:00Z"


def _one_flown_one_cancelled_one_airborne(api):
    """Three plans filed up front, then flown, stood down and launched in turn."""
    fixtures.set_clock(api, MIXED_SETUP_CLOCK)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=MIXED_SETUP_CLOCK
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    headers = make_pilot_headers(pilot["id"])
    plans = [
        fixtures.create_planned_flight(
            api,
            pilot["id"],
            aircraft["id"],
            zone["id"],
            start,
            end,
            planned_max_altitude_ft=380,
        )
        for start, end in (
            (MIXED_FLOWN_START, MIXED_FLOWN_PLANNED_END),
            (MIXED_STOOD_DOWN_START, MIXED_STOOD_DOWN_END),
            (MIXED_AIRBORNE_START, MIXED_AIRBORNE_END),
        )
    ]

    fixtures.set_clock(api, MIXED_FLOWN_START)
    first_check = fixtures.clear_flight_for_launch(api, plans[0])
    assert first_check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a clear sweep, got findings {first_check['blocking_findings']}"
    )
    validate_success(api.launch_flight(plans[0]["id"], headers=headers))
    fixtures.set_clock(api, MIXED_FLOWN_ACTUAL_END)
    flown = validate_success(
        api.complete_flight(
            plans[0]["id"],
            factories.completion_payload(
                MIXED_FLOWN_ACTUAL_END, max_altitude_reached_ft=300, incident_occurred=False
            ),
            headers=headers,
        )
    )

    stood_down = validate_success(
        api.cancel_flight(
            plans[1]["id"],
            factories.cancellation_payload("Crosswind above the airframe limit."),
            headers=headers,
        )
    )

    fixtures.set_clock(api, MIXED_AIRBORNE_START)
    third_check = fixtures.clear_flight_for_launch(api, plans[2])
    assert third_check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a clear sweep, got findings {third_check['blocking_findings']}"
    )
    airborne = validate_success(api.launch_flight(plans[2]["id"], headers=headers))

    fixtures.set_clock(api, MIXED_REPORTING_CLOCK)
    return pilot, flown, stood_down, airborne


def test_the_summary_aggregates_the_flown_mission_alone(api, compliance_officer):
    """PRD §3.7: "Flights in `PLANNED`, `PREFLIGHT_CLEARED`, `IN_PROGRESS` or `CANCELLED` are excluded entirely, and the keying is on `actual_end`, not on `planned_end` and not on `created_at`."
    PRD §3.7: "It accepts an optional `window_start` and `window_end`; `window_start` defaults to the pilot's `created_at` and `window_end` to the current instant."
    PRD §3.7: "The service writes all four fields, then computes `logged_minutes` as the whole minutes between `actual_start` and `actual_end`, discarding any part-minute remainder, and computes `altitude_exceedance` as true exactly when `max_altitude_reached_ft` is strictly greater than the flight's effective ceiling — the cited authorization's `granted_ceiling_ft` when the flight names one, and 400 feet otherwise."

    Design: Corner/calculations/flight_summary_counts_only_completed_flights
    """
    pilot, flown, stood_down, airborne = _one_flown_one_cancelled_one_airborne(api)

    assert flown["logged_minutes"] == 65, (
        f"09:00 to 10:05 is 65 whole minutes, got {flown['logged_minutes']}"
    )
    assert stood_down["status"] == FlightStatus.CANCELLED.value, (
        f"the second plan was stood down, got {stood_down['status']}"
    )
    assert airborne["status"] == FlightStatus.IN_PROGRESS.value, (
        f"the third plan is still airborne, got {airborne['status']}"
    )

    summary = validate_success(
        api.get_flight_summary(pilot["id"], headers=compliance_officer)
    )

    assert_flight_summary(
        summary,
        completed_flight_count=1,
        total_logged_minutes=65,
        average_duration_minutes=65.0,
        max_altitude_reached_ft=300,
        incident_flight_count=0,
        exceedance_flight_count=0,
        window_start=pilot["created_at"],
        window_end=MIXED_REPORTING_CLOCK,
    )


def test_the_completed_filter_and_the_summary_agree_on_the_source_set(api, compliance_officer):
    """PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."
    PRD §3.7: "Flights in `PLANNED`, `PREFLIGHT_CLEARED`, `IN_PROGRESS` or `CANCELLED` are excluded entirely, and the keying is on `actual_end`, not on `planned_end` and not on `created_at`."

    Design: Corner/calculations/flight_summary_counts_only_completed_flights
    """
    pilot, flown, _stood_down, _airborne = _one_flown_one_cancelled_one_airborne(api)

    rows, meta = validate_paginated(
        api.list_flights(
            params={"pilot_id": pilot["id"], "status": FlightStatus.COMPLETED.value},
            headers=compliance_officer,
        )
    )

    assert_pagination_meta(meta, DEFAULT_LIMIT, 0, 1)
    assert len(rows) == 1, f"only the flown mission is COMPLETED, got {len(rows)} rows"
    assert rows[0]["id"] == flown["id"], (
        f"expected the flown mission {flown['id']}, got {rows[0]['id']}"
    )

    unfiltered, unfiltered_meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert unfiltered_meta["total_count"] == 3, (
        f"the pilot holds three flights in all, got {unfiltered_meta['total_count']}"
    )
    assert len(unfiltered) == 3, f"expected three rows on the unfiltered page, got {len(unfiltered)}"


# ---------------------------------------------------------------------------
# The window keys on actual_end, not on created_at and not on planned_start
# ---------------------------------------------------------------------------

KEYED_SETUP_CLOCK = "2026-10-01T00:00:00Z"
KEYED_LATER_START = "2026-10-04T23:00:00Z"
KEYED_LATER_PLANNED_END = "2026-10-04T23:50:00Z"
KEYED_LATER_ACTUAL_END = "2026-10-05T00:10:00Z"
KEYED_EARLIER_START = "2026-10-02T23:30:00Z"
KEYED_EARLIER_PLANNED_END = "2026-10-03T00:20:00Z"
KEYED_EARLIER_ACTUAL_END = "2026-10-03T00:25:00Z"
KEYED_WINDOW_START = "2026-10-03T00:00:00Z"
KEYED_WINDOW_END = "2026-10-05T00:00:00Z"


def _two_flights_straddling_midnight(api):
    """The later window is filed first; each mission overruns its planned end."""
    fixtures.set_clock(api, KEYED_SETUP_CLOCK)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=KEYED_SETUP_CLOCK
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=2,
    )
    headers = make_pilot_headers(pilot["id"])
    later_plan = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        KEYED_LATER_START,
        KEYED_LATER_PLANNED_END,
        planned_max_altitude_ft=380,
    )
    earlier_plan = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        KEYED_EARLIER_START,
        KEYED_EARLIER_PLANNED_END,
        planned_max_altitude_ft=380,
    )

    fixtures.set_clock(api, KEYED_EARLIER_START)
    fixtures.clear_flight_for_launch(api, earlier_plan)
    validate_success(api.launch_flight(earlier_plan["id"], headers=headers))
    fixtures.set_clock(api, KEYED_EARLIER_ACTUAL_END)
    earlier = validate_success(
        api.complete_flight(
            earlier_plan["id"],
            factories.completion_payload(
                KEYED_EARLIER_ACTUAL_END, max_altitude_reached_ft=300, incident_occurred=False
            ),
            headers=headers,
        )
    )

    fixtures.set_clock(api, KEYED_LATER_START)
    fixtures.clear_flight_for_launch(api, later_plan)
    validate_success(api.launch_flight(later_plan["id"], headers=headers))
    fixtures.set_clock(api, KEYED_LATER_ACTUAL_END)
    later = validate_success(
        api.complete_flight(
            later_plan["id"],
            factories.completion_payload(
                KEYED_LATER_ACTUAL_END,
                max_altitude_reached_ft=300,
                incident_occurred=True,
                incident_summary="Bird strike on descent; airframe recovered.",
            ),
            headers=headers,
        )
    )
    return pilot, earlier, later


def test_the_window_selects_on_actual_end_rather_than_on_the_planned_window(
    api, compliance_officer
):
    """PRD §3.7: "Flights in `PLANNED`, `PREFLIGHT_CLEARED`, `IN_PROGRESS` or `CANCELLED` are excluded entirely, and the keying is on `actual_end`, not on `planned_end` and not on `created_at`."
    PRD §3.7: "The source set is that pilot's flights whose `status` is `COMPLETED` and whose `actual_end` falls in the half-open window — at or after `window_start` and strictly before `window_end`."
    PRD §3.7: "From that set the response reports `completed_flight_count` (the number of flights), `total_logged_minutes` (the sum of their `logged_minutes`), `max_altitude_reached_ft` (the greatest `max_altitude_reached_ft` among them), `incident_flight_count` (how many have `incident_occurred` true), `exceedance_flight_count` (how many have `altitude_exceedance` true), `average_duration_minutes` (the `total_logged_minutes` divided by the `completed_flight_count`, rounded half-up to one decimal place), and the `window_start` and `window_end` actually applied."

    Design: Corner/calculations/summary_window_keys_on_actual_end_not_on_created_at_or_planned_start
    """
    pilot, earlier, later = _two_flights_straddling_midnight(api)

    assert_flight(
        earlier,
        status=FlightStatus.COMPLETED.value,
        logged_minutes=55,
        actual_end=KEYED_EARLIER_ACTUAL_END,
        incident_occurred=False,
    )
    assert_flight(
        later,
        status=FlightStatus.COMPLETED.value,
        logged_minutes=70,
        actual_end=KEYED_LATER_ACTUAL_END,
        incident_occurred=True,
    )
    assert_instant_equals(
        pilot["created_at"], KEYED_SETUP_CLOCK, "the pilot was enrolled before the window opens"
    )

    summary = validate_success(
        api.get_flight_summary(
            pilot["id"],
            params={"window_start": KEYED_WINDOW_START, "window_end": KEYED_WINDOW_END},
            headers=compliance_officer,
        )
    )

    assert_flight_summary(
        summary,
        completed_flight_count=1,
        total_logged_minutes=55,
        average_duration_minutes=55.0,
        max_altitude_reached_ft=300,
        incident_flight_count=0,
        exceedance_flight_count=0,
        window_start=KEYED_WINDOW_START,
        window_end=KEYED_WINDOW_END,
    )

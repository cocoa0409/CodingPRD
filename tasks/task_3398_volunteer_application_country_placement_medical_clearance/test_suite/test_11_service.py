"""Swearing-in cascade and the in-country service: event-driven suspension,
the ACTIVE-status gates, and early termination from SUSPENDED."""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    ET_0MO_END_CLOCK,
    EXPECTED_COMPLETION_DATE,
    SERVICE_START_CLOCK,
    TEST_USERS,
    api_client,
    assert_completion_record_invariants,
    assert_service_event,
    create_site_placement_payload,
    create_sworn_in_scenario,
    early_terminate_service_at,
    get_application,
    get_service,
    get_service_for_application,
    log_service_event,
    set_clock,
    suspend_service_with_security_alert,
    validate_error,
    validate_success,
)

TRAINER = TEST_USERS["training_director_headers"]
DIRECTOR = TEST_USERS["country_director_headers"]
MEDIC = TEST_USERS["medical_officer_headers"]


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestSwearInCascade:
    def test_swear_in_creates_service_and_closes_application(self):
        """PRD §3.7: "A `TrainingDirector` swears in a `PASSED` enrollment —
        any other state fails with `ERR_ENROLLMENT_NOT_ASSESSABLE` — which
        creates the volunteer's service record: `service_start_date` read
        from the logical clock, `expected_completion_date` exactly 810 days
        later, status `ACTIVE`, and `application_id`,
        `assignment_opening_id`, and `country_program_id` copied from the
        accepted invitation and its pinned program. The same act advances the
        application from `IN_TRAINING` to `SWORN_IN`, its terminal state."

        Design: Difficulty/transitive_cascade/swear_in_creates_service_and_closes_application
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]
        enrollment = scenario["enrollment"]
        app_id = scenario["application"]["id"]

        assert enrollment["status"] == "SWORN_IN", "enrollment reaches its terminal state"
        # Link 1: exactly one service, created ACTIVE with clock-stamped dates.
        assert service["status"] == "ACTIVE"
        assert _ts(service["service_start_date"]) == _ts(SERVICE_START_CLOCK)
        assert _ts(service["expected_completion_date"]) == _ts(EXPECTED_COMPLETION_DATE), \
            "expected completion is exactly 810 days after service start"
        assert service["assignment_opening_id"] == scenario["opening"]["id"]
        assert service["country_program_id"] == scenario["program"]["id"]
        assert service["application_id"] == app_id
        # Link 2: the application closes.
        assert get_application(app_id)["status"] == "SWORN_IN"

    def test_swear_in_terminal_rejects_replay(self):
        """PRD §3.7: "A `TrainingDirector` swears in a `PASSED` enrollment —
        any other state fails with `ERR_ENROLLMENT_NOT_ASSESSABLE` — which
        creates the volunteer's service record: `service_start_date` read
        from the logical clock, `expected_completion_date` exactly 810 days
        later, status `ACTIVE`, and `application_id`,
        `assignment_opening_id`, and `country_program_id` copied from the
        accepted invitation and its pinned program."
        PRD §3.7: "Assessment belongs to the `TrainingDirector` and to a live
        classroom: it requires the cohort `IN_SESSION` (`ERR_INVALID_STATE`
        otherwise) and the enrollment `ENROLLED` or `REMEDIATION`
        (`ERR_ENROLLMENT_NOT_ASSESSABLE` otherwise)."

        Design: Difficulty/transitive_cascade/swear_in_creates_service_and_closes_application
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        enrollment_id = scenario["enrollment"]["id"]
        app_id = scenario["application"]["id"]

        # SWORN_IN is terminal for the enrollment: no action is replayable.
        validate_error(
            api_client.swear_in_training_enrollment(enrollment_id, TRAINER),
            ApiErrorId.ERR_ENROLLMENT_NOT_ASSESSABLE, 409)
        validate_error(
            api_client.assess_training_enrollment(
                enrollment_id,
                {"language_score": 3.0, "technical_score": 3.0,
                 "cultural_score": 3.0},
                TRAINER),
            ApiErrorId.ERR_ENROLLMENT_NOT_ASSESSABLE, 409)
        validate_error(
            api_client.remediate_training_enrollment(enrollment_id, TRAINER),
            ApiErrorId.ERR_ENROLLMENT_NOT_ASSESSABLE, 409)
        assert get_application(app_id)["status"] == "SWORN_IN"
        # Still exactly one service for the application (no duplicate created).
        get_service_for_application(app_id)


class TestServiceEventsAndSuspension:
    def test_service_events_suspend_and_resume(self):
        """PRD §3.8: "Two event types move the service itself: a
        `SECURITY_ALERT` at `CRITICAL` severity suspends an `ACTIVE` service
        into `SUSPENDED` under the evacuation protocol, and an `ALL_CLEAR`
        returns a `SUSPENDED` service to `ACTIVE`."
        PRD §3.8: "Entries are immutable once written (§2.5), and the log
        lists chronologically by `occurred_at` with `created_at` ascending as
        the tie-break."
        PRD §2.5: "The exception is the ServiceEvent. Service events form an
        append-only log: each entry receives an `id` and a `created_at`, and
        neither `updated_at` nor `version` exists on the resource."

        Design: Corner/state_machines/service_events_suspend_and_resume
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]

        alert = log_service_event(
            service["id"],
            event_type="SECURITY_ALERT", severity="CRITICAL",
            description="Civil unrest near site; evacuate to safe haven",
            occurred_at="2027-01-03T08:00:00Z")
        assert get_service(service["id"])["status"] == "SUSPENDED"

        # A ROUTINE medical event (loggable by a MedicalOfficer) changes
        # nothing while the service is suspended.
        care = log_service_event(
            service["id"], headers=MEDIC,
            event_type="MEDICAL_CARE", severity="ROUTINE",
            description="Routine checkup at regional office",
            occurred_at="2027-01-04T08:00:00Z")
        assert get_service(service["id"])["status"] == "SUSPENDED"

        all_clear = log_service_event(
            service["id"],
            event_type="ALL_CLEAR", severity="ROUTINE",
            description="Situation stabilized; return to site authorized",
            occurred_at="2027-01-05T08:00:00Z")
        assert get_service(service["id"])["status"] == "ACTIVE"

        events = validate_success(
            api_client.list_service_events(service["id"], DIRECTOR), 200)
        assert len(events) == 3
        assert [e["event_type"] for e in events] == [
            "SECURITY_ALERT", "MEDICAL_CARE", "ALL_CLEAR"], \
            "the log lists chronologically by occurred_at"
        for event in events:
            assert_service_event(event)
        assert {e["id"] for e in events} == {alert["id"], care["id"], all_clear["id"]}

    def test_service_actions_require_active_status(self):
        """PRD §3.8: "Completion is available only while the service is
        `ACTIVE` (`ERR_SERVICE_NOT_ACTIVE`) and only once the logical clock
        has reached the `expected_completion_date` — earlier attempts fail
        with `ERR_SERVICE_TERM_NOT_REACHED` (HTTP 422). Early termination is
        available from `ACTIVE` or `SUSPENDED` — from any other state,
        `ERR_SERVICE_NOT_ACTIVE` — and names a `reason` of `MEDICAL`,
        `FAMILY`, `SECURITY`, or `ADMINISTRATIVE`."
        PRD §3.8: "With the volunteer sworn in, a `CountryDirector` proposes
        a site placement for the `ACTIVE` service — a service in any other
        state rejects the proposal with `ERR_SERVICE_NOT_ACTIVE` — naming the
        `host_community_name` and the `counterpart_org_name`."

        Design: Corner/state_machines/service_actions_require_active_status
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_sworn_in_scenario()
        service = scenario["service"]
        suspend_service_with_security_alert(service["id"])

        # While SUSPENDED, completion and placement proposals are rejected.
        validate_error(
            api_client.complete_service(service["id"], DIRECTOR),
            ApiErrorId.ERR_SERVICE_NOT_ACTIVE, 409)
        validate_error(
            api_client.create_site_placement(
                service["id"], create_site_placement_payload(), DIRECTOR),
            ApiErrorId.ERR_SERVICE_NOT_ACTIVE, 409)
        assert get_service(service["id"])["status"] == "SUSPENDED"

        # Early termination from SUSPENDED is allowed; day 14 rounds to
        # zero months under the half-month round-up.
        closed, record = early_terminate_service_at(
            service["id"], "SECURITY", ET_0MO_END_CLOCK)
        assert closed["status"] == "EARLY_TERMINATED"
        assert _ts(closed["actual_end_date"]) == _ts(ET_0MO_END_CLOCK)
        assert record["completion_type"] == "EARLY"
        assert record["et_reason"] == "SECURITY"
        assert record["months_served"] == 0
        assert record["gross_accrued_cents"] == 0
        assert record["allowance_paid_cents"] == 0
        assert record["allowance_forfeited_cents"] == 0
        assert record["nce_eligible"] is False
        assert record["nce_duration_months"] == 0
        assert_completion_record_invariants(record)

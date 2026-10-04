"""Crash detection, wellness checks, emergency dispatch, and cascades."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    false_alarm_payload,
    get_circle_state,
    get_member_state,
    get_success_data,
    invite_and_grant_member,
    invite_and_grant_minor,
    make_member_headers,
    post_fix,
    report_crash_for_member,
    report_crash_payload,
    reset_clock,
    run_sweeps,
    set_clock,
    start_trip,
    validate_error,
    validate_paginated,
    validate_success,
    verify_dispatch_payload,
)
from test_helpers.api_client import api_client


class TestCrashCreation:
    def test_crash_event_initial_state_is_wellness_pending(self, api, system_headers):
        """PRD §3.7: "A successfully reported crash event enters `DETECTED` and
        immediately transitions to `WELLNESS_PENDING`. The transition creates a
        wellness check in `SENT` with a `deadline_at` derived from the
        severity: `detected_at` plus 300 seconds for `SEVERE`, plus 600 seconds
        otherwise."
        PRD §3.7: "at least 8.0 but less than 16.0 maps to `MINOR`"

        Design: Corner/state_machines/crash_event_initial_state_is_wellness_pending
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="InitCrashFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=12.0)
        assert crash["crash_status"] == "WELLNESS_PENDING"
        assert crash["severity"] == "MINOR"
        assert crash["wellness_check_id"]
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "SENT"
        assert check["deadline_at"] == "2026-09-01T00:10:00.000Z" or check["deadline_at"].startswith("2026-09-01T00:10:00")

    def test_crash_event_severe_severity_uses_300s_deadline(self, api, system_headers):
        """PRD §3.7: "The transition creates a wellness check in `SENT` with a
        `deadline_at` derived from the severity: `detected_at` plus 300 seconds
        for `SEVERE`, plus 600 seconds otherwise."
        PRD §3.7: "24.0 or more maps to `SEVERE`."

        Design: Corner/state_machines/crash_event_initial_state_is_wellness_pending
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="SevFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=25.0)
        assert crash["severity"] == "SEVERE"
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "SENT"
        assert check["deadline_at"].startswith("2026-09-01T00:05:00")


class TestCrashSeverityBoundary:
    def test_crash_severity_lower_boundary_inclusive(self, api, system_headers):
        """PRD §3.7: "a `delta_v` strictly less than 8.0 is rejected with
        `ERR_CRASH_BELOW_THRESHOLD` (HTTP 422) and no crash event is created.
        The severity ladder itself is a strict-threshold mapping compared at
        two decimal places: at least 8.0 but less than 16.0 maps to `MINOR`;
        at least 16.0 but less than 24.0 maps to `MAJOR`; 24.0 or more maps to
        `SEVERE`. The boundary is inclusive on the lower edge — a `delta_v` of
        exactly 16.0 is `MAJOR`, not `MINOR` — and a `delta_v` of exactly 7.99
        is rejected."

        Design: Difficulty/boundary_precision_check/crash_severity_lower_boundary_inclusive
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="BoundFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        resp = api.report_crash(
            circle["id"], owner_id,
            report_crash_payload(trip_id, delta_v=7.99, note="below"),
            owner_headers,
        )
        validate_error(resp, "ERR_CRASH_BELOW_THRESHOLD")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=8.0)
        assert crash["severity"] == "MINOR"

    def test_crash_severity_upper_boundary_major_at_sixteen(self, api, system_headers):
        """PRD §3.7: "The boundary is inclusive on the lower edge — a `delta_v`
        of exactly 16.0 is `MAJOR`, not `MINOR` — and a `delta_v` of exactly
        7.99 is rejected."

        Design: Difficulty/boundary_precision_check/crash_severity_lower_boundary_inclusive
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="BoundFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=16.0)
        assert crash["severity"] == "MAJOR"

    def test_crash_below_threshold_rejected(self, api, system_headers):
        """PRD §3.7: "a `delta_v` strictly less than 8.0 is rejected with
        `ERR_CRASH_BELOW_THRESHOLD` (HTTP 422) and no crash event is created."

        Design: Corner/validations/crash_below_threshold_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="BelowFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        resp = api.report_crash(
            circle["id"], owner_id,
            report_crash_payload(trip_id, delta_v=7.99, note="tap"),
            owner_headers,
        )
        validate_error(resp, "ERR_CRASH_BELOW_THRESHOLD")
        data, meta = validate_paginated(api.list_crashes(circle["id"], owner_id, owner_headers))
        assert meta["total_count"] == 0

    def test_crash_below_threshold_free_tier_rejected(self, api, system_headers):
        """PRD §3.7: "a `delta_v` strictly less than 8.0 is rejected with
        `ERR_CRASH_BELOW_THRESHOLD` (HTTP 422) and no crash event is created."

        Design: Corner/validations/crash_below_threshold_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="BelowFreeFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        resp = api.report_crash(
            circle["id"], owner_id,
            report_crash_payload(trip_id, delta_v=4.0, note="nudge"),
            owner_headers,
        )
        validate_error(resp, "ERR_CRASH_BELOW_THRESHOLD")


class TestCrashRequiresOpenTrip:
    def test_crash_event_requires_trip_open(self, api, system_headers):
        """PRD §3.7: "First, the named trip must currently be `OPEN` and must
        belong to the same member the crash is reported against; otherwise the
        report is rejected with `ERR_TRIP_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/crash_event_requires_trip_open
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="TripDepFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:05:00Z",
                 speed_mps=0.0, motion_context="STILL")
        resp = api.report_crash(
            circle["id"], owner_id,
            report_crash_payload(trip_id, delta_v=20.0, note="after close"),
            owner_headers,
        )
        validate_error(resp, "ERR_TRIP_NOT_OPEN")
        trip = get_success_data(api.get_trip(circle["id"], owner_id, trip_id, owner_headers))
        assert trip["trip_status"] == "CLOSED"
        data, meta = validate_paginated(api.list_crashes(circle["id"], owner_id, owner_headers))
        assert meta["total_count"] == 0

    def test_crash_event_against_other_members_open_trip_rejected(self, api, system_headers):
        """PRD §3.7: "First, the named trip must currently be `OPEN` and must
        belong to the same member the crash is reported against; otherwise the
        report is rejected with `ERR_TRIP_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/crash_event_requires_trip_open
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="TripDepFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        other = invite_and_grant_member(circle, owner_headers, display_name="Oth", email="oth@example.com")
        other_headers = make_member_headers(other["id"])
        _fix, owner_trip_id = start_trip(circle, owner, owner_headers,
                                         recorded_at="2026-09-01T00:00:00Z")
        resp = api.report_crash(
            circle["id"], other["id"],
            report_crash_payload(owner_trip_id, delta_v=20.0, note="not my trip"),
            other_headers,
        )
        validate_error(resp, "ERR_TRIP_NOT_OPEN")


class TestWellnessDeadline:
    def test_wellness_acknowledge_after_deadline_rejected(self, api, system_headers):
        """PRD §3.7: "An acknowledgement attempted at or after the deadline is
        rejected with `ERR_WELLNESS_EXPIRED` (HTTP 409); by then the system has
        already escalated."

        Design: Corner/state_machines/wellness_acknowledge_after_deadline_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="LateFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=18.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        resp = api.acknowledge_wellness(crash["id"], crash["wellness_check_id"], owner_headers)
        validate_error(resp, "ERR_WELLNESS_EXPIRED")
        after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert after["crash_status"] == "ESCALATED"

    def test_wellness_acknowledge_before_deadline_confirms_ok(self, api, system_headers):
        """PRD §3.7: "A successful acknowledgement moves the wellness check to
        `ACKNOWLEDGED`, records the `acknowledged_by_member_id`, transitions
        the crash event to `CONFIRMED_OK`, and — as a compensation — cancels
        any emergency dispatch that already exists in `PENDING_VERIFICATION`."

        Design: Corner/state_machines/wellness_acknowledge_after_deadline_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="AckFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=18.0)
        check = validate_success(api.acknowledge_wellness(
            crash["id"], crash["wellness_check_id"], owner_headers,
        ))
        assert check["check_status"] == "ACKNOWLEDGED"
        assert check["acknowledged_by_member_id"] == owner_id
        after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert after["crash_status"] == "CONFIRMED_OK"


class TestDispatchLifecycle:
    def test_dispatch_cannot_be_cancelled_once_staged(self, api, system_headers):
        """PRD §3.7: "The owner may also cancel a dispatch directly while it is
        in `PENDING_VERIFICATION` — moving it to `CANCELLED` — but cancellation
        from `STAGED` or `COMPLETED` is rejected with
        `ERR_DISPATCH_ALREADY_STAGED` (HTTP 409)."

        Design: Corner/state_machines/dispatch_cannot_be_cancelled_once_staged
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="StagedFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        dispatch_id = escalated["dispatch_id"]
        validate_success(api.verify_dispatch(dispatch_id, verify_dispatch_payload(), owner_headers))
        resp = api.cancel_dispatch(dispatch_id, owner_headers)
        validate_error(resp, "ERR_DISPATCH_ALREADY_STAGED")
        dispatch = get_success_data(api.get_dispatch(dispatch_id, owner_headers))
        assert dispatch["dispatch_status"] == "STAGED"

    def test_dispatch_cancel_while_pending_verification_succeeds(self, api, system_headers):
        """PRD §3.7: "The owner may also cancel a dispatch directly while it is
        in `PENDING_VERIFICATION` — moving it to `CANCELLED` — but cancellation
        from `STAGED` or `COMPLETED` is rejected with
        `ERR_DISPATCH_ALREADY_STAGED` (HTTP 409)."

        Design: Corner/state_machines/dispatch_cannot_be_cancelled_once_staged
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="CancelFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        dispatch_id = escalated["dispatch_id"]
        cancelled = validate_success(api.cancel_dispatch(dispatch_id, owner_headers))
        assert cancelled["dispatch_status"] == "CANCELLED"


class TestFalseAlarm:
    def test_mark_false_alarm_from_dispatched_rejected(self, api, system_headers):
        """PRD §3.7: "A crash can be retracted as a false alarm by the owner, by
        an admin, or by the crash-subject member, from any of `DETECTED`,
        `WELLNESS_PENDING`, or `ESCALATED` — but never from `DISPATCHED`,
        because by then the assistance unit has been burned with the
        responder."
        PRD §3.7: "A retraction from `DISPATCHED` or beyond does not refund."

        Design: Corner/state_machines/mark_false_alarm_from_dispatched_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="DispatchedFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        dispatch_id = escalated["dispatch_id"]
        validate_success(api.verify_dispatch(dispatch_id, verify_dispatch_payload(), owner_headers))
        balance_before = get_circle_state(circle["id"], owner_headers)["assistance_units_balance"]
        assert balance_before == 3
        resp = api.mark_false_alarm(crash["id"], false_alarm_payload(), owner_headers)
        validate_error(resp, "ERR_INVALID_STATE")
        after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert after["crash_status"] == "DISPATCHED"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 3

    def test_mark_false_alarm_from_wellness_pending_cancels_check(self, api, system_headers):
        """PRD §3.7: "On a successful retraction the crash event moves to
        `FALSE_ALARM`, the wellness check is `CANCELLED` if still `SENT`, the
        emergency dispatch is `CANCELLED` if it is `PENDING_VERIFICATION` or
        `VERIFIED`, and — critically — if the crash had previously consumed an
        assistance unit (that is, it was retracted from `ESCALATED`), one unit
        is returned to the circle's `assistance_units_balance`."

        Design: Corner/state_machines/mark_false_alarm_from_dispatched_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="FalseAlarmFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        retracted = validate_success(api.mark_false_alarm(
            crash["id"], false_alarm_payload(false_alarm_reason="dropped phone, not a crash"),
            owner_headers,
        ))
        assert retracted["crash_status"] == "FALSE_ALARM"
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "CANCELLED"
        # No escalation occurred, so no unit was consumed and none is refunded.
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4

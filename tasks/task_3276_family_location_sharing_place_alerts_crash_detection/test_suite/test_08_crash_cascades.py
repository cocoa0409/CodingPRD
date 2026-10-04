"""Depth cascades: crash-detection chain, consent-revoke chain, cyclic crashes."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    false_alarm_payload,
    get_circle_state,
    get_success_data,
    invite_and_grant_member,
    make_member_headers,
    post_fix,
    report_crash_for_member,
    reset_clock,
    run_sweeps,
    set_clock,
    start_trip,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestCrashDetectionDepth3Cascade:
    def test_crash_detection_depth3_cascade(self, api, system_headers):
        """PRD §3.7: "When the wellness deadline passes with the check still
        `SENT`, the system escalates: the wellness check transitions to
        `UNANSWERED`, an emergency dispatch is created in
        `PENDING_VERIFICATION`, the circle's `assistance_units_balance` is
        decremented by 1, and the crash event moves to `ESCALATED`."

        Design: Difficulty/transitive_cascade/crash_detection_depth3_cascade
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="CascadeFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        created_version = crash["version"]
        set_clock("2026-09-01T00:10:01Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert escalated["crash_status"] == "ESCALATED"
        # PRD §3.7: "Escalation increments both the crash event's `version` and
        # the circle's `version`" — at least one increment over the version
        # observed at creation.
        assert escalated["version"] >= created_version + 1
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "UNANSWERED"
        dispatch_id = escalated["dispatch_id"]
        assert dispatch_id
        dispatch = get_success_data(api.get_dispatch(dispatch_id, owner_headers))
        assert dispatch["crash_event_id"] == crash["id"]
        assert dispatch["dispatch_status"] == "PENDING_VERIFICATION"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 3

    def test_crash_detection_cascade_severe_escalates_after_300s(self, api, system_headers):
        """PRD §3.7: "The transition creates a wellness check in `SENT` with a
        `deadline_at` derived from the severity: `detected_at` plus 300 seconds
        for `SEVERE`, plus 600 seconds otherwise."
        PRD §3.7: "When the wellness deadline passes with the check still
        `SENT`, the system escalates: the wellness check transitions to
        `UNANSWERED`, an emergency dispatch is created in
        `PENDING_VERIFICATION`, the circle's `assistance_units_balance` is
        decremented by 1, and the crash event moves to `ESCALATED`."

        Design: Difficulty/transitive_cascade/crash_detection_depth3_cascade
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="CascadeSevFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=30.0)
        assert crash["severity"] == "SEVERE"
        # 301 seconds later: past the SEVERE deadline but before a 600 s one.
        set_clock("2026-09-01T00:05:01Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert escalated["crash_status"] == "ESCALATED"
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "UNANSWERED"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 3


class TestConsentRevokeDepth2Cascade:
    def test_consent_revoke_depth2_cascade(self, api, system_headers):
        """PRD §3.2: "A successful revocation appends a `ConsentRecord` with
        `consent_action` `REVOKE`, flips the member's `consent_state` to
        `REVOKED`, increments the member's `version`, and triggers three
        compensations across the rest of the system: every location fix the
        member's device subsequently submits is recorded as `REJECTED_CONSENT`
        rather than accepted; every `OPEN` crash event on that member
        transitions to `FALSE_ALARM`; and every wellness check still `SENT` for
        that member is `CANCELLED`. The same revocation abandons any open trip
        the member had been driving."

        Design: Difficulty/transitive_cascade/consent_revoke_depth2_cascade
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="RevokeFam")
        rex = invite_and_grant_member(circle, owner_headers, display_name="Rex", email="rex@example.com")
        rex_headers = make_member_headers(rex["id"])
        _fix, trip_id = start_trip(circle, rex, rex_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, rex, rex_headers, trip_id, delta_v=18.0)
        validate_success(api.revoke_consent(circle["id"], rex["id"], owner_headers))
        from test_helpers import get_member_state
        member = get_member_state(circle["id"], rex["id"], owner_headers)
        assert member["consent_state"] == "REVOKED"
        crash_after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert crash_after["crash_status"] == "FALSE_ALARM"
        check = get_success_data(api.get_wellness_check(crash["wellness_check_id"], owner_headers))
        assert check["check_status"] == "CANCELLED"
        trip = get_success_data(api.get_trip(circle["id"], rex["id"], trip_id, rex_headers))
        assert trip["trip_status"] == "ABANDONED"
        dispatches, meta = validate_paginated(
            api.list_dispatches_toplevel(system_headers, params={"crash_event_id": crash["id"]})
        )
        assert meta["total_count"] == 0

    def test_consent_revoke_without_open_crash_leaves_no_false_alarm(self, api, system_headers):
        """PRD §3.2: "A successful revocation appends a `ConsentRecord` with
        `consent_action` `REVOKE`, flips the member's `consent_state` to
        `REVOKED`, increments the member's `version`, and triggers three
        compensations across the rest of the system: every location fix the
        member's device subsequently submits is recorded as `REJECTED_CONSENT`
        rather than accepted; every `OPEN` crash event on that member
        transitions to `FALSE_ALARM`; and every wellness check still `SENT` for
        that member is `CANCELLED`. The same revocation abandons any open trip
        the member had been driving."

        Design: Difficulty/transitive_cascade/consent_revoke_depth2_cascade
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="RevokeCalmFam")
        rex = invite_and_grant_member(circle, owner_headers, display_name="RexC", email="rexc@example.com")
        rex_headers = make_member_headers(rex["id"])
        _fix, trip_id = start_trip(circle, rex, rex_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        validate_success(api.revoke_consent(circle["id"], rex["id"], rex_headers))
        from test_helpers import get_member_state
        member = get_member_state(circle["id"], rex["id"], owner_headers)
        assert member["consent_state"] == "REVOKED"
        trip = get_success_data(api.get_trip(circle["id"], rex["id"], trip_id, rex_headers))
        assert trip["trip_status"] == "ABANDONED"
        crashes, meta = validate_paginated(api.list_crashes(circle["id"], rex["id"], rex_headers))
        assert meta["total_count"] == 0


class TestCrashCyclicFalseAlarmLoop:
    def test_crash_event_cyclic_false_alarm_loop(self, api, system_headers):
        """PRD §3.7: "On a successful retraction the crash event moves to
        `FALSE_ALARM`, the wellness check is `CANCELLED` if still `SENT`, the
        emergency dispatch is `CANCELLED` if it is `PENDING_VERIFICATION` or
        `VERIFIED`, and — critically — if the crash had previously consumed an
        assistance unit (that is, it was retracted from `ESCALATED`), one unit
        is returned to the circle's `assistance_units_balance`."
        PRD §3.7: "A successful acknowledgement moves the wellness check to
        `ACKNOWLEDGED`, records the `acknowledged_by_member_id`, transitions
        the crash event to `CONFIRMED_OK`, and — as a compensation — cancels
        any emergency dispatch that already exists in `PENDING_VERIFICATION`."

        Design: Difficulty/non_linear_state_machine/crash_event_cyclic_false_alarm_loop
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="CrashFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        # First crash: escalate past deadline, then retract from ESCALATED.
        _f1, trip1 = start_trip(circle, owner, owner_headers,
                                recorded_at="2026-09-01T00:00:00Z")
        crash1 = report_crash_for_member(circle, owner, owner_headers, trip1, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated1 = get_success_data(api.get_crash(crash1["id"], owner_headers))
        assert escalated1["crash_status"] == "ESCALATED"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 3
        validate_success(api.mark_false_alarm(
            crash1["id"], false_alarm_payload(false_alarm_reason="dropped phone, not a crash"),
            owner_headers,
        ))
        crash1_after = get_success_data(api.get_crash(crash1["id"], owner_headers))
        assert crash1_after["crash_status"] == "FALSE_ALARM"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4
        # Second crash on a new trip; acknowledged in time -> CONFIRMED_OK.
        _f2, trip2 = start_trip(circle, owner, owner_headers,
                                recorded_at="2026-09-01T00:12:00Z")
        crash2 = report_crash_for_member(circle, owner, owner_headers, trip2, delta_v=25.0)
        check2 = validate_success(api.acknowledge_wellness(
            crash2["id"], crash2["wellness_check_id"], owner_headers,
        ))
        assert check2["check_status"] == "ACKNOWLEDGED"
        crash2_after = get_success_data(api.get_crash(crash2["id"], owner_headers))
        assert crash2_after["crash_status"] == "CONFIRMED_OK"

    def test_resolved_crash_cannot_reenter_escalated(self, api, system_headers):
        """PRD §3.7: "Once a crash is `RESOLVED`, it cannot re-enter
        `ESCALATED` — that path is forbidden."
        PRD §3.7: "From `DISPATCHED`, the owner completes the dispatch: the
        dispatch moves from `STAGED` to `COMPLETED`, the crash event moves to
        `RESOLVED`, and the crash event's `version` increments."

        Design: Difficulty/non_linear_state_machine/crash_event_cyclic_false_alarm_loop
        """
        from test_helpers import verify_dispatch_payload, validate_error
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="ResolveFam")
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
        validate_success(api.complete_dispatch(dispatch_id, owner_headers))
        resolved = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert resolved["crash_status"] == "RESOLVED"
        # A further sweep must not move a RESOLVED crash back to ESCALATED.
        set_clock("2026-09-01T02:00:00Z")
        run_sweeps()
        after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert after["crash_status"] == "RESOLVED"
        # Marking false alarm from RESOLVED is also rejected.
        resp = api.mark_false_alarm(crash["id"], false_alarm_payload(), owner_headers)
        validate_error(resp, "ERR_INVALID_STATE")

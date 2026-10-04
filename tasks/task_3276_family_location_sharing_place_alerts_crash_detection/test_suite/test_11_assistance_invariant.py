"""Assistance-unit compensating invariant: escalation consume/refund cycle."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    false_alarm_payload,
    get_circle_state,
    get_success_data,
    post_fix,
    report_crash_for_member,
    reset_clock,
    run_sweeps,
    set_clock,
    start_trip,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestAssistanceUnitInvariant:
    def test_assistance_units_escalate_then_false_alarm(self, api, system_headers):
        """PRD §2.8: "A companion compensating invariant governs crash
        escalations that are later retracted: an escalation that is followed by
        a false-alarm retraction restores exactly one unit to the circle,
        leaving the balance identical to what it was before the escalation —
        but only if the retraction happens before the dispatch reaches
        `DISPATCHED`; once a dispatch has been staged, the unit is burned with
        the responder and is not returned."
        PRD §3.7: "When the wellness deadline passes with the check still
        `SENT`, the system escalates: the wellness check transitions to
        `UNANSWERED`, an emergency dispatch is created in
        `PENDING_VERIFICATION`, the circle's `assistance_units_balance` is
        decremented by 1, and the crash event moves to `ESCALATED`."

        Design: Difficulty/compensating_invariant/assistance_units_escalate_then_false_alarm
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="InvFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert escalated["crash_status"] == "ESCALATED"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 3
        validate_success(api.mark_false_alarm(
            crash["id"],
            false_alarm_payload(false_alarm_reason="bump in parking lot"),
            owner_headers,
        ))
        after = get_success_data(api.get_crash(crash["id"], owner_headers))
        assert after["crash_status"] == "FALSE_ALARM"
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4
        events, _meta = validate_paginated(api.list_subscription_events(circle["id"], owner_headers))
        kinds = [(e["event_kind"], e["units_delta"]) for e in events]
        assert ("ASSISTANCE_CONSUME", -1) in kinds
        assert ("ASSISTANCE_GRANT", 1) in kinds

    def test_assistance_units_escalate_then_false_alarm_refund_exactly_once(self, api, system_headers):
        """PRD §2.8: "A companion compensating invariant governs crash
        escalations that are later retracted: an escalation that is followed by
        a false-alarm retraction restores exactly one unit to the circle,
        leaving the balance identical to what it was before the escalation —
        but only if the retraction happens before the dispatch reaches
        `DISPATCHED`; once a dispatch has been staged, the unit is burned with
        the responder and is not returned."

        Design: Difficulty/compensating_invariant/assistance_units_escalate_then_false_alarm
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="InvFam2")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        validate_success(api.mark_false_alarm(
            crash["id"],
            false_alarm_payload(false_alarm_reason="sensor glitch confirmed"),
            owner_headers,
        ))
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4
        # A second false-alarm attempt on the terminal crash is rejected and
        # must not refund a second time.
        resp = api.mark_false_alarm(
            crash["id"],
            false_alarm_payload(false_alarm_reason="second attempt"),
            owner_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE")
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 4

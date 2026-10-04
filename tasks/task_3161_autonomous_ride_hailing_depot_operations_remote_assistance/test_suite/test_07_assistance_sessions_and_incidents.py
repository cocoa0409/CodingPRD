"""Remote assistance, cyclic tier escalation, incidents and retention.

An assistance session is worked by a remote operator, but a session nobody
actions is swept back to ESCALATED by the depot operations checkpoint with
its tier raised.  Incidents hang off the session rather than the ride, and
their retention is computed in exact seconds from the report's own severity.
"""

from test_helpers import constants as c
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_MAX_ATTEMPTS_NOT_REACHED,
    ERR_SESSION_TERMINAL,
)
from test_helpers import factories as f
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    read_ride,
    read_territory,
    read_vehicle,
    run_depot_ops,
    set_clock,
    stack_with_acknowledged_session,
    stack_with_reviewable_incident,
    stack_with_unresolved_ride,
)
from test_helpers.test_users import ASSIST, ASSIST_2, SAFETY


class TestSessionCyclicEscalation:
    """An acknowledged session times out back into the escalated tier."""

    def test_three_ops_runs_return_the_session_to_escalated(self, api):
        """The checkpoint sweep re-escalates the tier and raises the counter.

        PRD 3.5: "Acknowledged sessions that nobody actioned do not sit
        indefinitely: the depot operations checkpoint, described in section 3.7,
        returns any session that has been `ACKNOWLEDGED` across three depot
        operations runs back to `ESCALATED`, raising its `escalation_tier` by one,
        incrementing its `attempt_count` by one, and refreshing its
        `last_ops_run_index` to the depot's current epoch."
        PRD 3.7: "any session that has been `ACKNOWLEDGED` across three depot
        operations runs is returned to `ESCALATED` with its `escalation_tier`
        raised by one and its `attempt_count` raised by one"

        Design: Difficulty/non_linear_state_machine/if_match_session_tier_escalation_cycle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, reason="SENSOR_FAULT")
        session = stack["session"]
        assert session["status"] == c.SESSION_ACKNOWLEDGED
        assert session["escalation_tier"] == 1

        depot_id = stack["depot"]["id"]
        run_depot_ops(api, depot_id)
        run_depot_ops(api, depot_id)
        run_depot_ops(api, depot_id)

        after = get_success_data(api.get_assistance_session(session["id"], headers=ASSIST))
        assert after["status"] == c.SESSION_ESCALATED, (
            "the session re-enters the state it already occupied"
        )
        assert after["escalation_tier"] == 2
        assert after["attempt_count"] == 1

    def test_two_ops_runs_leave_the_session_acknowledged(self, api):
        """Below the three-run allowance the session stays where it is.

        PRD 3.7: "any session that has been `ACKNOWLEDGED` across three depot
        operations runs is returned to `ESCALATED` with its `escalation_tier`
        raised by one and its `attempt_count` raised by one"

        Design: Difficulty/non_linear_state_machine/if_match_session_tier_escalation_cycle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, reason="STUCK")
        session = stack["session"]
        depot_id = stack["depot"]["id"]
        run_depot_ops(api, depot_id)
        run_depot_ops(api, depot_id)

        after = get_success_data(api.get_assistance_session(session["id"], headers=ASSIST))
        assert after["status"] == c.SESSION_ACKNOWLEDGED
        assert after["escalation_tier"] == 1
        assert after["attempt_count"] == 0

    def test_the_swept_session_can_be_acknowledged_again(self, api):
        """Re-escalation is not terminal: the session can be worked again.

        PRD 3.5: "An escalated session is worked by a `RemoteAssistanceOperator`.
        Acknowledging a session moves it from `ESCALATED` to `ACKNOWLEDGED` and
        records the acknowledging operator's `X-User-ID` on the session as
        `op_user_id`."

        Design: Difficulty/non_linear_state_machine/if_match_session_tier_escalation_cycle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, reason="STUCK")
        session = stack["session"]
        depot_id = stack["depot"]["id"]
        for _ in range(3):
            run_depot_ops(api, depot_id)

        re_acked = get_success_data(
            api.acknowledge_session(session["id"], headers=ASSIST_2)
        )
        assert re_acked["status"] == c.SESSION_ACKNOWLEDGED
        assert re_acked["op_user_id"] == ASSIST_2["X-User-ID"], (
            "the acknowledging operator's X-User-ID is recorded on the session"
        )


class TestSessionOutOfSequenceActions:
    """Session actions are only legal from the status that permits them."""

    def test_acknowledging_an_escalated_session_succeeds(self, api):
        """ESCALATED to ACKNOWLEDGED is the expected first action.

        PRD 3.5: "Acknowledging a session moves it from `ESCALATED` to
        `ACKNOWLEDGED` and records the acknowledging operator's `X-User-ID` on
        the session as `op_user_id`."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, acknowledge=False)
        session = stack["session"]
        assert session["status"] == c.SESSION_ESCALATED

        acknowledged = validate_success(
            api.acknowledge_session(session["id"], headers=ASSIST)
        )
        assert acknowledged["status"] == c.SESSION_ACKNOWLEDGED
        assert acknowledged["op_user_id"] == ASSIST["X-User-ID"]

    def test_resolving_a_session_before_acknowledging_is_refused(self, api):
        """Resolve is reachable only from ACKNOWLEDGED.

        PRD 3.5: "Acknowledging a session that is not `ESCALATED` is refused with
        `ERR_INVALID_STATE` (HTTP 409), as are the other out-of-sequence actions
        below."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, acknowledge=False)
        resp = api.resolve_session(stack["session"]["id"], headers=ASSIST)
        validate_error(resp, ERR_INVALID_STATE, 409)

    def test_resolving_an_acknowledged_session_succeeds(self, api):
        """ACKNOWLEDGED to RESOLVED carries no further cascade.

        PRD 3.5: "The operator may resolve it, moving it to `RESOLVED`, which is
        one of the two terminal statuses and carries no further cascade."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api)
        resolved = get_success_data(api.resolve_session(stack["session"]["id"], headers=ASSIST))
        assert resolved["status"] == c.SESSION_RESOLVED
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_MATCHED

    def test_unresolved_below_three_attempts_is_refused(self, api):
        """The unresolvable declaration needs at least three attempts recorded.

        PRD 3.5: "Or the operator may declare it unresolvable, which requires
        that the session's `attempt_count` is at least 3; an attempt below that
        threshold is refused with `ERR_MAX_ATTEMPTS_NOT_REACHED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/if_match_unresolved_session_cascade_to_vehicle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api)
        session = stack["session"]
        assert session["attempt_count"] == 0

        resp = api.escalate_session_unresolved(session["id"], headers=ASSIST)
        validate_error(resp, ERR_MAX_ATTEMPTS_NOT_REACHED, 409)
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_MATCHED


class TestUnresolvedCascade:
    """UNRESOLVED fails the ride, which recomputes the vehicle, which caps filing."""

    def test_unresolved_session_fails_the_ride_and_blocked_vehicle_stays_dispatched(self, api):
        """The three-hop chain ends with the ride FAILED and a capped count.

        PRD 3.5: "A successful declaration moves the session to `UNRESOLVED` —
        the other terminal status — and cascades outward: the ride referencing
        the session moves to `FAILED`, which in turn recomputes the matched
        vehicle's readiness verdict and advances the vehicle's `version`."
        PRD 3.5: "The filing is accepted only while an assistance session for that
        ride is still in `ESCALATED` or `ACKNOWLEDGED`; once the session has been
        driven to `UNRESOLVED`, the ride is `FAILED` and no further session — and
        therefore no further report — can be created against it. A filing
        attempted in that condition is rejected with `ERR_SESSION_TERMINAL`
        (HTTP 409)."
        PRD 3.5: "This is a structural cap on the severe-incident count rather
        than an incidental rule: a territory's severe-incident total cannot grow
        through a ride that has already been closed out as unresolvable."

        Design: Difficulty/transitive_cascade/if_match_unresolved_session_cascade_to_vehicle
        """
        set_clock(api)
        stack = stack_with_unresolved_ride(api)
        territory, ride, vehicle = stack["territory"], stack["ride"], stack["vehicle"]

        session = get_success_data(api.get_assistance_session(stack["session"]["id"], headers=ASSIST))
        assert session["status"] == c.SESSION_UNRESOLVED
        assert read_ride(api, territory["id"], ride["id"])["status"] == c.RIDE_FAILED

        vehicle_after = read_vehicle(api, vehicle["id"])
        assert vehicle_after["service_status"] == c.SERVICE_DISPATCHED, (
            "the vehicle is still IN_SERVICE, so the recomputed verdict is DISPATCHED"
        )

        resp = api.film_incident(
            ride["id"], f.create_incident_payload(severity="SEVERE"), headers=SAFETY
        )
        validate_error(resp, ERR_SESSION_TERMINAL, 409)
        assert read_territory(api, territory["id"])["total_severe_incidents"] == 0

    def test_the_unresolved_cascade_caps_the_severe_incident_count(self, api):
        """No report is created, so the territory count cannot grow.

        PRD 3.5: "A filing attempted in that condition is rejected with
        `ERR_SESSION_TERMINAL` (HTTP 409)."
        PRD 3.5: "Whenever it is recomputed — on filing and on voiding — it is
        set to the number of `IncidentReport` rows whose `vehicle_id` equals the
        ride's matched vehicle and whose `severity` is `SEVERE` and whose
        `status` is anything other than `VOIDED`."

        Design: Difficulty/transitive_cascade/if_match_unresolved_session_cascade_to_vehicle
        """
        set_clock(api)
        stack = stack_with_unresolved_ride(api)
        territory, ride = stack["territory"], stack["ride"]
        before = read_territory(api, territory["id"])["total_severe_incidents"]
        assert before == 0

        reports = get_success_data(
            api.list_session_incident_reports(stack["session"]["id"], headers=SAFETY)
        )
        assert reports == []

        api.film_incident(ride["id"], f.create_incident_payload(severity="SEVERE"), headers=SAFETY)
        assert read_territory(api, territory["id"])["total_severe_incidents"] == 0


class TestIncidentRetention:
    """Retention is exact seconds from the report's own severity."""

    def test_minor_report_retains_180_days(self, api):
        """A MINOR report keeps no crash evidence and expires in 180 days.

        PRD 3.5: "`crash_evidence_retained` is true exactly when the report's
        `severity` is `MODERATE` or `SEVERE`, and false for `MINOR`."
        PRD 3.5: "`retention_expires_at` is the report's `created_at` offset by a
        fixed number of exact seconds: 365 days — 31,536,000 seconds — when crash
        evidence is retained, and 180 days — 15,552,000 seconds — when it is not."

        Design: Corner/calculations/if_match_incident_retention_minor_is_180_days
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-ret-1")
        report = validate_success(
            api.film_incident(
                stack["ride"]["id"],
                {"severity": "MINOR", "description": "Curb contact, no damage"},
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert report["crash_evidence_retained"] is False
        assert report["retention_expires_at"] == "2026-11-28T00:00:00Z", (
            "180 days from 2026-06-01T00:00:00Z"
        )

    def test_moderate_report_retains_365_days(self, api):
        """A MODERATE report retains crash evidence and expires in 365 days.

        PRD 3.5: "`crash_evidence_retained` is true exactly when the report's
        `severity` is `MODERATE` or `SEVERE`, and false for `MINOR`."
        PRD 3.5: "Both fields are recomputed from the report's own severity and
        creation instant, so a `MINOR` report's expiry lands roughly half as far
        out as a `SEVERE` one filed at the same moment."

        Design: Corner/calculations/if_match_incident_retention_moderate_is_365_days
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-ret-2")
        report = validate_success(
            api.film_incident(
                stack["ride"]["id"],
                {"severity": "MODERATE", "description": "Low-speed contact with curb furniture"},
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert report["crash_evidence_retained"] is True
        assert report["retention_expires_at"] == "2027-06-01T00:00:00Z", (
            "365 days from 2026-06-01T00:00:00Z"
        )

    def test_severe_report_retains_365_days(self, api):
        """SEVERE joins MODERATE on the crash-evidence retention class.

        PRD 3.5: "`crash_evidence_retained` is true exactly when the report's
        `severity` is `MODERATE` or `SEVERE`, and false for `MINOR`."

        Design: Corner/calculations/if_match_incident_retention_moderate_is_365_days
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-ret-3")
        report = validate_success(
            api.film_incident(
                stack["ride"]["id"], f.create_incident_payload(severity="SEVERE"),
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert report["crash_evidence_retained"] is True
        assert report["retention_expires_at"] == "2027-06-01T00:00:00Z"

    def test_retention_is_offset_in_exact_seconds(self, api):
        """The offset is the declared second count, not a calendar-month step.

        PRD 3.5: "The offset is applied as exact seconds from `created_at`, not
        as a calendar-month calculation."

        Design: Corner/calculations/if_match_incident_retention_minor_is_180_days
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-ret-4")
        report = validate_success(
            api.film_incident(
                stack["ride"]["id"], f.create_incident_payload(severity="MINOR"),
                headers=SAFETY,
            ),
            expected_status=201,
        )
        created = report["created_at"]
        assert created.startswith("2026-06-01T00:00:00"), (
            f"the report is stamped with the logical clock, got {created}"
        )
        assert c.STANDARD_RETENTION_SECONDS == 15_552_000
        assert report["retention_expires_at"] == "2026-11-28T00:00:00Z"


class TestIncidentReviewTrack:
    """Incident reports are adjudicated along a fixed track with one branch."""

    def test_closed_is_terminal_for_void_and_begin_review(self, api):
        """Neither void nor begin-review is possible after closure.

        PRD 3.5: "Beginning review moves a `FILED` report to `UNDER_REVIEW`.
        Closing moves an `UNDER_REVIEW` report to `CLOSED`, one of the two
        terminal statuses."
        PRD 3.5: "Voiding is the branch: a `FILED` report may be voided directly
        to `VOIDED`, the other terminal status, without ever passing through
        review; an `UNDER_REVIEW` report cannot be voided."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_reviewable_incident(
            api, severity="MINOR", idempotency_key="idem-term-1"
        )
        report = stack["incident"]
        get_success_data(api.begin_incident_review(report["id"], headers=SAFETY))
        closed = get_success_data(api.close_incident_report(report["id"], headers=SAFETY))
        assert closed["status"] == c.INCIDENT_CLOSED

        void_resp = api.void_incident_report(report["id"], headers=SAFETY)
        validate_error(void_resp, ERR_INVALID_STATE, 409)
        review_resp = api.begin_incident_review(report["id"], headers=SAFETY)
        validate_error(review_resp, ERR_INVALID_STATE, 409)
        assert get_success_data(api.get_incident_report(report["id"], headers=SAFETY))["status"] == c.INCIDENT_CLOSED

    def test_under_review_report_cannot_be_voided(self, api):
        """The void branch is only open while the report is still FILED.

        PRD 3.5: "an `UNDER_REVIEW` report cannot be voided."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_reviewable_incident(
            api, severity="MINOR", idempotency_key="idem-term-2"
        )
        report = stack["incident"]
        get_success_data(api.begin_incident_review(report["id"], headers=SAFETY))
        void_resp = api.void_incident_report(report["id"], headers=SAFETY)
        validate_error(void_resp, ERR_INVALID_STATE, 409)

    def test_filed_report_can_be_voided_directly(self, api):
        """A FILED report is voided without ever passing through review.

        PRD 3.5: "Voiding is the branch: a `FILED` report may be voided directly
        to `VOIDED`, the other terminal status, without ever passing through
        review."

        Design: Corner/state_machines/if_match_incident_report_closed_is_terminal
        """
        set_clock(api)
        stack = stack_with_reviewable_incident(
            api, severity="MINOR", idempotency_key="idem-term-3"
        )
        voided = get_success_data(api.void_incident_report(stack["incident"]["id"], headers=SAFETY))
        assert voided["status"] == c.INCIDENT_VOIDED


class TestSevereIncidentAggregate:
    """The territory counter is an aggregate over reports, not a tally."""

    def test_filing_a_severe_report_raises_the_territory_count(self, api):
        """A SEVERE report on the ride's matched vehicle counts immediately.

        PRD 3.5: "Whenever it is recomputed — on filing and on voiding — it is
        set to the number of `IncidentReport` rows whose `vehicle_id` equals the
        ride's matched vehicle and whose `severity` is `SEVERE` and whose `status`
        is anything other than `VOIDED`."

        Design: Corner/calculations/if_match_incident_retention_moderate_is_365_days
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-sev-1")
        validate_success(
            api.film_incident(
                stack["ride"]["id"], f.create_incident_payload(severity="SEVERE"),
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert read_territory(api, stack["territory"]["id"])["total_severe_incidents"] == 1

    def test_voiding_a_severe_report_lowers_the_territory_count(self, api):
        """Voided reports are excluded entirely, so the count falls by one.

        PRD 3.5: "Reports in `FILED`, `UNDER_REVIEW` or `CLOSED` all count;
        `VOIDED` reports are excluded entirely, which means voiding a severe
        report reduces the territory's `total_severe_incidents` by one."

        Design: Difficulty/transitive_cascade/if_match_unresolved_session_cascade_to_vehicle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-sev-2")
        report = validate_success(
            api.film_incident(
                stack["ride"]["id"], f.create_incident_payload(severity="SEVERE"),
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert read_territory(api, stack["territory"]["id"])["total_severe_incidents"] == 1

        get_success_data(api.void_incident_report(report["id"], headers=SAFETY))
        assert read_territory(api, stack["territory"]["id"])["total_severe_incidents"] == 0

    def test_a_minor_report_does_not_enter_the_severe_count(self, api):
        """Only SEVERE reports feed the aggregate.

        PRD 3.5: "it is set to the number of `IncidentReport` rows whose
        `vehicle_id` equals the ride's matched vehicle and whose `severity` is
        `SEVERE` and whose `status` is anything other than `VOIDED`."

        Design: Difficulty/transitive_cascade/if_match_unresolved_session_cascade_to_vehicle
        """
        set_clock(api)
        stack = stack_with_acknowledged_session(api, idempotency_key="idem-sev-3")
        validate_success(
            api.film_incident(
                stack["ride"]["id"], f.create_incident_payload(severity="MINOR"),
                headers=SAFETY,
            ),
            expected_status=201,
        )
        assert read_territory(api, stack["territory"]["id"])["total_severe_incidents"] == 0
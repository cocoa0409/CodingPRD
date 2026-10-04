"""Strict and inclusive boundaries: the daily submission capacity is a ceiling, and
the coaching due date is inclusive on its far side.
"""
import pytest

from test_helpers import (
    api_client, utc, get_success_data, validate_error, validate_success, validate_paginated,
    set_clock, create_agency, create_carrier, create_plan,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, submit_enrollment,
    reject_enrollment, create_coaching_assignment_payload,
    create_agency_payload, create_enrollment_payload, get_success_data,
    CLOCK_BEFORE_AEP, TEST_USERS, make_licensed_agent_headers,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


class TestDailySubmissionCapacity:
    """Capacity 3: the third submission succeeds, the fourth is blocked."""

    def _capacity_scenario(self, capacity=3):
        # The effective_date 2026-11-01 must not fall inside the agency's Annual
        # Enrollment Period, or the AEP-window rule (not the capacity rule) is
        # what fires. The clock starts before the window and the window is pushed
        # clear of the effective day.
        set_clock(CLOCK_BEFORE_AEP)
        agency = get_success_data(api_client.create_agency(
            create_agency_payload(aep_daily_submission_capacity=capacity,
                                  aep_start_date="2026-11-20T00:00:00Z",
                                  aep_end_date="2026-12-07T00:00:00Z"), ADMIN))
        carrier = get_success_data(api_client.create_carrier(
            {"legal_name": "Meridian Health Plan of Texas", "naic_number": "60211",
             "contract_type": "CONTRACTED", "initial_commission_rate_pct": 0.20,
             "renewal_commission_rate_pct": 0.10, "chargeback_clawback_pct": 0.25,
             "ack_expected_within_days": 5, "effectuation_expected_within_days": 30},
            ADMIN))
        plan = create_plan(carrier["id"])
        agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
        member, version = create_member_for_agent(agency["id"], agent["id"], )
        scope = capture_scope(member["id"], agent["id"], version)
        call = open_call(agent["id"], member["id"], scope["id"])
        connect_call(agent["id"], call["id"])
        call = complete_call(agent["id"], call["id"])
        return {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent,
                "member": member, "scope": scope, "call": call}

    def test_a_rejected_enrollment_does_not_consume_capacity(self):
        """PRD §2.13: "the count of non-`REJECTED`, non-`WITHDRAWN` enrollments whose
        `effective_date` falls on the same UTC calendar day must be strictly below the
        agency's `aep_daily_submission_capacity`".
        PRD §2.13: "Rejection is recorded by the same carrier-side identity and is reachable
        from both `SUBMITTED` and `ACKNOWLEDGED`."

        Design: Difficulty/boundary_precision_check/boundary_aep_capacity_is_strictly_below
        """
        scn = self._capacity_scenario(capacity=3)
        agent_id = scn["agent"]["id"]
        first = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                  scn["plan"]["id"], scn["scope"]["id"],
                                  scn["call"]["version"])
        api_client.reject_enrollment(first["id"], {"reason": "CARRIER_DUPLICATE"},
                                     CARRIER_INT)
        scn["call"] = get_call(agent_id, scn["call"]["id"])
        second = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                   scn["plan"]["id"], scn["scope"]["id"],
                                   scn["call"]["version"])
        assert second["submission_status"] == "SUBMITTED", (
            "the REJECTED row is excluded from the committed count"
        )

    def test_at_capacity_the_next_submission_for_that_day_is_blocked(self):
        """PRD §2.13: "Then the daily capacity rule: the count of non-`REJECTED`,
        non-`WITHDRAWN` enrollments whose `effective_date` falls on the same UTC calendar
        day must be strictly below the agency's `aep_daily_submission_capacity`, and a count
        that has reached capacity produces `ERR_AEP_DAILY_SUBMISSION_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/boundary_aep_capacity_is_strictly_below
        """
        scn = self._capacity_scenario(capacity=3)
        agent_id = scn["agent"]["id"]
        first = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                  scn["plan"]["id"], scn["scope"]["id"],
                                  scn["call"]["version"])
        api_client.reject_enrollment(first["id"], {"reason": "CARRIER_DUPLICATE"},
                                     CARRIER_INT)
        scn["call"] = get_call(agent_id, scn["call"]["id"])

        # Three accepted submissions bring the committed count to the capacity.
        second = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                   scn["plan"]["id"], scn["scope"]["id"],
                                   scn["call"]["version"])
        scn["call"] = get_call(agent_id, scn["call"]["id"])
        third = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                  scn["plan"]["id"], scn["scope"]["id"],
                                  scn["call"]["version"])
        scn["call"] = get_call(agent_id, scn["call"]["id"])
        fourth = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                   scn["plan"]["id"], scn["scope"]["id"],
                                   scn["call"]["version"])
        assert second["submission_status"] == "SUBMITTED"
        assert third["submission_status"] == "SUBMITTED"
        assert fourth["submission_status"] == "SUBMITTED", (
            "the third non-rejected submission reaches the capacity and still succeeds"
        )

        scn["call"] = get_call(agent_id, scn["call"]["id"])
        headers = make_licensed_agent_headers(agent_id)
        resp = api_client.create_enrollment(create_enrollment_payload(
            scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
            scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"]), headers)
        validate_error(resp, "ERR_AEP_DAILY_SUBMISSION_CAPACITY_EXCEEDED",
                       expected_status=409)

    def test_the_blocked_request_persisted_nothing(self):
        """PRD §2.13: "a count that has reached capacity produces
        `ERR_AEP_DAILY_SUBMISSION_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/boundary_aep_capacity_is_strictly_below
        """
        scn = self._capacity_scenario(capacity=3)
        agent_id = scn["agent"]["id"]
        first = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                                  scn["plan"]["id"], scn["scope"]["id"],
                                  scn["call"]["version"])
        api_client.reject_enrollment(first["id"], {"reason": "CARRIER_DUPLICATE"},
                                     CARRIER_INT)
        # Three accepted submissions bring the committed count to the capacity.
        for _ in range(3):
            scn["call"] = get_call(agent_id, scn["call"]["id"])
            submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                              scn["plan"]["id"], scn["scope"]["id"],
                              scn["call"]["version"])
        scn["call"] = get_call(agent_id, scn["call"]["id"])
        headers = make_licensed_agent_headers(agent_id)
        api_client.create_enrollment(create_enrollment_payload(
            scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
            scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"]), headers)

        rows, _meta = validate_paginated(api_client.list_enrollments(
            DIRECTOR, params={"carrier_id": scn["carrier"]["id"]}))
        # The rejected row plus the three accepted rows, and nothing from the refusal.
        assert len(rows) == 4


class TestCoachingDueBoundary:
    """At exactly due_on the assignment is not yet overdue."""

    def _coaching_scenario(self):
        scn = {"unused": True}
        set_clock("2026-10-01T00:00:00Z")
        agency = get_success_data(api_client.create_agency(create_agency_payload(), ADMIN))
        carrier = get_success_data(api_client.create_carrier(
            {"legal_name": "Meridian Health Plan of Texas", "naic_number": "60211",
             "contract_type": "CONTRACTED", "initial_commission_rate_pct": 0.20,
             "renewal_commission_rate_pct": 0.10, "chargeback_clawback_pct": 0.25,
             "ack_expected_within_days": 5, "effectuation_expected_within_days": 30},
            ADMIN))
        plan = create_plan(carrier["id"])
        agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
        coaching = get_success_data(api_client.create_coaching_assignment(
            create_coaching_assignment_payload(agent["id"]), COACH))
        return {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent,
                "coaching": coaching}

    def test_at_exactly_due_on_the_assignment_is_not_yet_overdue(self):
        """PRD §3.9: "the `due_on` date is `assigned_on` plus 14 days, and if the logical
        clock is at or before `due_on` the figure is 0".
        PRD §3.9: "The boundary is inclusive on the `due_on` side — a clock reading exactly
        `due_on` is not yet overdue."

        Design: Difficulty/boundary_precision_check/boundary_coaching_due_on_is_not_yet_overdue
        """
        scn = self._coaching_scenario()
        set_clock("2026-10-15T00:00:00Z")
        coaching = get_success_data(api_client.get_coaching_assignment(
            scn["coaching"]["id"], COACH))
        assert coaching["due_on"] == utc("2026-10-15T00:00:00Z")
        assert coaching["status"] == "ASSIGNED"
        assert coaching["overdue_days"] == 0

    def test_one_day_later_the_assignment_reads_overdue(self):
        """PRD §3.9: "a clock strictly past `due_on` yields the whole number of days from
        `due_on` to the clock."
        PRD §3.9: "When that derived figure recomputes to 1 or more on an assignment still
        in status `ASSIGNED` or `IN_PROGRESS`, the system automatically moves it to
        `OVERDUE`".

        Design: Difficulty/boundary_precision_check/boundary_coaching_due_on_is_not_yet_overdue
        """
        scn = self._coaching_scenario()
        set_clock("2026-10-16T00:00:00Z")
        coaching = get_success_data(api_client.get_coaching_assignment(
            scn["coaching"]["id"], COACH))
        assert coaching["status"] == "OVERDUE"
        assert coaching["overdue_days"] == 1

    def test_starting_an_overdue_assignment_is_refused(self):
        """PRD §3.9: "A coach starts it, moving `ASSIGNED` to `IN_PROGRESS`; an assignment
        that is not `ASSIGNED` cannot be started, and the refusal is
        `ERR_COACHING_NOT_ASSIGNED`."

        Design: Difficulty/boundary_precision_check/boundary_coaching_due_on_is_not_yet_overdue
        """
        scn = self._coaching_scenario()
        set_clock("2026-10-16T00:00:00Z")
        resp = api_client.start_coaching(scn["coaching"]["id"], COACH)
        validate_error(resp, "ERR_COACHING_NOT_ASSIGNED", expected_status=409)

    def test_completing_from_overdue_is_allowed(self):
        """PRD §3.9: "Completion is reachable from `IN_PROGRESS` and also from `OVERDUE`,
        and any other status fails with `ERR_COACHING_NOT_IN_PROGRESS`."
        PRD §3.9: "Completion moves the assignment to `COMPLETED`, stamps `completed_on`
        from the logical clock".

        Design: Difficulty/boundary_precision_check/boundary_coaching_due_on_is_not_yet_overdue
        """
        scn = self._coaching_scenario()
        set_clock("2026-10-16T00:00:00Z")
        result = validate_success(api_client.complete_coaching(
            scn["coaching"]["id"], {"notes": "Retraining delivered"}, COACH), 200)
        assert result["status"] == "COMPLETED"
        assert result["completed_on"] == utc("2026-10-16T00:00:00Z")
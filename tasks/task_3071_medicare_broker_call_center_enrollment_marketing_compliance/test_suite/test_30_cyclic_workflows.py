"""The Complaint machine is cyclic rather than a pipeline, and the Enrollment carries
two independent state dimensions on one row.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_error, validate_success,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    setup_effectuated_enrollment, create_complaint_payload, set_clock,
    TEST_USERS, make_licensed_agent_headers,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


class TestComplaintAppealCycle:
    """A complaint can substantiate, be appealed, be remanded and substantiate again."""

    def _substantiated_once(self):
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        complaint = get_success_data(api_client.create_complaint(
            create_complaint_payload(scn["agent"]["id"],
                                     complaint_type="MISREPRESENTATION",
                                     source="BENEFICIARY", severity="HIGH",
                                     filed_on="2026-09-28T00:00:00Z"), COMPLIANCE))
        api_client.begin_review(complaint["id"], COMPLIANCE)
        first = validate_success(
            api_client.substantiate_complaint(complaint["id"], COMPLIANCE), 200)
        scn["complaint"] = first
        return scn

    def test_first_substantiation_stamps_the_finding_and_raises_the_strike_count(self):
        """PRD §3.9: "The agent's `substantiated_complaint_count` increases by one, the
        agency's `substantiated_complaint_rate` is recomputed, the agency's
        `open_complaint_count` is recomputed, and the agent's `compliance_risk_score` is
        recomputed."
        PRD §3.9: "Failing that, a complaint whose type is `UNAPPROVED_MARKETING`,
        `MISREPRESENTATION` or `PLAN_MISREPRESENTATION` yields `MARKETING_VIOLATION`."

        Design: Difficulty/non_linear_state_machine/non_linear_complaint_appeal_cycle_round_trip
        """
        scn = self._substantiated_once()
        assert scn["complaint"]["finding_code"] == "MARKETING_VIOLATION"
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["substantiated_complaint_count"] == 1

    def test_appeal_then_remand_returns_the_complaint_to_review(self):
        """PRD §3.9: "Either route moves the complaint to `APPEALED` and recomputes the
        agent's `compliance_risk_score`."
        PRD §3.9: "A compliance officer may remand it back to `UNDER_REVIEW`, which
        recomputes the agency's `open_complaint_count`".

        Design: Difficulty/non_linear_state_machine/non_linear_complaint_appeal_cycle_round_trip
        """
        scn = self._substantiated_once()
        cid = scn["complaint"]["id"]

        appealed = validate_success(
            api_client.appeal_complaint(cid, {"appeal_note": "Plan type was in scope"},
                                        CARRIER_INT), 200)
        assert appealed["status"] == "APPEALED"

        remanded = validate_success(api_client.remand_complaint(cid, COMPLIANCE), 200)
        assert remanded["status"] == "UNDER_REVIEW"

    def test_the_cycle_is_a_genuine_round_trip_and_raises_the_count_again(self):
        """PRD §3.9: "The agent's `substantiated_complaint_count` increases by one".
        PRD §3.9: "A coaching assignment is then created automatically with status
        `ASSIGNED` and `triggered_by` set to `COMPLAINT`; the agent's
        `open_coaching_count` increases by one and `coaching_flag` becomes true."

        Design: Difficulty/non_linear_state_machine/non_linear_complaint_appeal_cycle_round_trip
        """
        scn = self._substantiated_once()
        cid = scn["complaint"]["id"]
        api_client.appeal_complaint(cid, {"appeal_note": "Round trip"}, CARRIER_INT)
        api_client.remand_complaint(cid, COMPLIANCE)

        second = validate_success(
            api_client.substantiate_complaint(cid, COMPLIANCE), 200)
        assert second["status"] == "SUBSTANTIATED"

        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["substantiated_complaint_count"] == 2, (
            "the same complaint substantiated twice raises the standing strike count twice"
        )
        coaching, _meta = validate_paginated(api_client.list_agent_coaching_assignments(
            scn["agent"]["id"], DIRECTOR))
        assert len(coaching) == 2
        assert agent["open_coaching_count"] == 2

    def test_appealed_dismissal_reverses_one_standing_strike(self):
        """PRD §3.9: "On that path the complaint moves to `DISMISSED`, the agent's
        `substantiated_complaint_count` decreases by one, and the agency's
        `substantiated_complaint_rate`, the agent's `compliance_risk_score` and the
        agency's posture are all recomputed."

        Design: Difficulty/non_linear_state_machine/non_linear_complaint_appeal_cycle_round_trip
        """
        scn = self._substantiated_once()
        cid = scn["complaint"]["id"]
        api_client.appeal_complaint(cid, {"appeal_note": "Round trip"}, CARRIER_INT)
        api_client.remand_complaint(cid, COMPLIANCE)
        api_client.substantiate_complaint(cid, COMPLIANCE)

        api_client.appeal_complaint(cid, {"appeal_note": "Second appeal"}, CARRIER_INT)
        dismissed = validate_success(api_client.dismiss_complaint(cid, COMPLIANCE), 200)
        assert dismissed["status"] == "DISMISSED"

        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["substantiated_complaint_count"] == 1


class TestEnrollmentParallelDimensions:
    """submission_status and disenrollment_status evolve independently on one row."""

    def test_effectuated_and_rapid_disenrolled_coexist_on_one_row(self):
        """PRD §3.6: "The submission dimension tracks what the carrier has done with the
        paperwork, and its values are exactly `SUBMITTED`, `ACKNOWLEDGED`, `EFFECTUATED`,
        `REJECTED` and `WITHDRAWN`. The membership dimension tracks whether the beneficiary
        is actually on the plan, and its values are exactly `NOT_APPLICABLE`, `ENROLLED`,
        `RAPID_DISENROLLED` and `STANDARD_DISENROLLED`."

        Design: Difficulty/non_linear_state_machine/non_linear_enrollment_parallel_state_dimensions
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)

        set_clock("2026-11-16T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-16T00:00:00Z",
             "disenrollment_reason": "MOVED_OUT_OF_SERVICE_AREA"},
            CARRIER_INT), 200)

        assert result["submission_status"] == "EFFECTUATED"
        assert result["disenrollment_status"] == "RAPID_DISENROLLED"

    def test_disenrolled_day_number_is_measured_half_open(self):
        """PRD §3.7: "The first is `disenrolled_day_number`, the whole number of days from
        `effective_date` to `disenrollment_date`, measured half-open — a disenrollment
        recorded on the same day as the effective date has a day number of 0."

        Design: Difficulty/non_linear_state_machine/non_linear_enrollment_parallel_state_dimensions
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)

        set_clock("2026-11-16T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-16T00:00:00Z",
             "disenrollment_reason": "MOVED_OUT_OF_SERVICE_AREA"},
            CARRIER_INT), 200)

        assert result["effective_date"] == utc("2026-11-01T00:00:00Z")
        assert result["disenrolled_day_number"] == 15
        assert result["is_rapid_disenrollment"] is True

    def test_withdrawal_is_unreachable_once_the_submission_is_effectuated(self):
        """PRD §3.6: "It is reachable from `SUBMITTED`, from `ACKNOWLEDGED`, and from
        `REJECTED`; an enrollment already `EFFECTUATED` or already `WITHDRAWN` cannot be
        withdrawn, and the refusal is `ERR_ENROLLMENT_NOT_WITHDRAWABLE`."

        Design: Difficulty/non_linear_state_machine/non_linear_enrollment_parallel_state_dimensions
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)

        set_clock("2026-11-16T00:00:00Z")
        api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-16T00:00:00Z",
             "disenrollment_reason": "MOVED_OUT_OF_SERVICE_AREA"},
            CARRIER_INT)

        headers = make_licensed_agent_headers(scn["agent"]["id"])
        resp = api_client.withdraw_enrollment(
            scn["enrollment"]["id"], {"reason": "BENEFICIARY_CHANGED_MIND"}, headers)
        validate_error(resp, "ERR_ENROLLMENT_NOT_WITHDRAWABLE", expected_status=409)

    def test_disenrollment_dimension_moves_both_counts_while_submission_stays(self):
        """PRD §3.7: "It recomputes the plan's `enrolled_member_count` and the agent's
        `active_enrollment_count`, recomputes the agent's `compliance_risk_score`, and
        recomputes the agency's `commission_balance_cents`."
        PRD §3.7: "It moves every open reconciliation period of that enrollment's carrier
        to `DISPUTED`".

        Design: Difficulty/non_linear_state_machine/non_linear_enrollment_parallel_state_dimensions
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)

        set_clock("2026-11-16T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-16T00:00:00Z",
             "disenrollment_reason": "MOVED_OUT_OF_SERVICE_AREA"},
            CARRIER_INT), 200)

        plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert plan["enrolled_member_count"] == 0
        assert agent["active_enrollment_count"] == 0
        assert result["submission_status"] == "EFFECTUATED", (
            "the membership dimension moved the counts while submission_status stayed"
        )
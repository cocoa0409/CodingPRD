"""Cross-entity dependencies: a rule on one entity's state is read at request time
against another entity's row.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, create_call_session_payload,
    CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]


class TestMemberAgencyGatesCallCompletion:
    """Completion requires the member's agency to equal the agent's agency."""

    def _foreign_member_scenario(self):
        set_clock(CLOCK_START)
        agency = get_success_data(api_client.create_agency(create_agency_payload(), ADMIN))
        carrier = get_success_data(api_client.create_carrier(
            {"legal_name": "Meridian Health Plan of Texas", "naic_number": "60211",
             "contract_type": "CONTRACTED", "initial_commission_rate_pct": 0.20,
             "renewal_commission_rate_pct": 0.10, "chargeback_clawback_pct": 0.25,
             "ack_expected_within_days": 5, "effectuation_expected_within_days": 30},
            ADMIN))
        plan = create_plan(carrier["id"])
        agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])

        other_agency = get_success_data(api_client.create_agency(
            create_agency_payload(name="Cascade Health Partners",
                                  service_center_code="CAS-PDX-02",
                                  aep_daily_submission_capacity=2), ADMIN))
        foreign_member, version = create_member_for_agent(
            other_agency["id"], agent["id"], full_name="Rosa Klein",
            medicare_beneficiary_id="2FG5-UF6-NL83",
            date_of_birth="1950-07-02T00:00:00Z")
        foreign_scope = capture_scope(foreign_member["id"], agent["id"], version)
        foreign_call = open_call(agent["id"], foreign_member["id"], foreign_scope["id"],
                                 started_at="2026-10-01T12:00:00Z",
                                 scheduled_end_at="2026-10-01T12:30:00Z",
                                 recording_id="REC-1004")
        connect_call(agent["id"], foreign_call["id"], recording_id="REC-1004")
        return {"agency": agency, "other_agency": other_agency, "carrier": carrier,
                "plan": plan, "agent": agent, "member": foreign_member,
                "scope": foreign_scope, "call": foreign_call}

    def test_completion_is_refused_for_a_member_of_another_agency(self):
        """PRD §3.3: "the member must belong to the same agency as the agent, else
        `ERR_MEMBER_NOT_IN_AGENCY`".
        PRD §2.13: "Then the agency-coherence check that the plan, the member and the agent
        all belong to the same agency, else `ERR_MEMBER_NOT_IN_AGENCY`."

        Design: Difficulty/cross_entity_state_dependency/cross_dependency_member_agency_gates_call_completion
        """
        scn = self._foreign_member_scenario()
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        resp = api_client.complete_call(scn["call"]["id"],
                                        {"recording_id": "REC-1004",
                                         "disclaimer_delivered": True}, headers)
        validate_error(resp, "ERR_MEMBER_NOT_IN_AGENCY", expected_status=422)

    def test_the_call_row_is_untouched_by_the_refusal(self):
        """PRD §3.3: "On success the call becomes `COMPLETED`, `actual_end_at` takes the
        logical clock, `live_call_count` is recomputed".

        Design: Difficulty/cross_entity_state_dependency/cross_dependency_member_agency_gates_call_completion
        """
        scn = self._foreign_member_scenario()
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        api_client.complete_call(scn["call"]["id"],
                                 {"recording_id": "REC-1004",
                                  "disclaimer_delivered": True}, headers)
        after = get_call(scn["agent"]["id"], scn["call"]["id"])
        assert after["status"] == "IN_PROGRESS"
        assert after["actual_end_at"] is None

    def test_the_drop_edge_still_succeeds_on_the_same_row(self):
        """PRD §3.3: "A call in either `RINGING` or `IN_PROGRESS` may be dropped, with an
        optional `reason`, and anything else fails with `ERR_CALL_NOT_DROPPABLE`."

        Design: Difficulty/cross_entity_state_dependency/cross_dependency_member_agency_gates_call_completion
        """
        scn = self._foreign_member_scenario()
        dropped = validate_success(
            api_client.drop_call(scn["call"]["id"],
                                 {"reason": "MEMBER_ROUTING_CORRECTED"},
                                 make_licensed_agent_headers(scn["agent"]["id"])), 200)
        assert dropped["status"] == "DROPPED"

    def test_the_two_agencies_genuinely_differ(self):
        """PRD §2.1: "`LicensedAgent` is the sole role that may capture a scope of
        appointment, open a call, generate a plan comparison, or submit an enrollment."

        Design: Difficulty/cross_entity_state_dependency/cross_dependency_member_agency_gates_call_completion
        """
        scn = self._foreign_member_scenario()
        member = get_success_data(api_client.get_member(
            scn["member"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert member["agency_id"] == scn["other_agency"]["id"]
        assert agent["agency_id"] == scn["agency"]["id"]
        assert member["agency_id"] != agent["agency_id"]
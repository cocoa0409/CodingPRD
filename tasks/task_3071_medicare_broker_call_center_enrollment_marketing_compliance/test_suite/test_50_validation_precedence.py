"""Validation precedence: when several rules could reject one request, the caller is
told about the earliest failure rather than an arbitrary one.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, get_success_data, validate_error, validate_success,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    create_plan, create_carrier, create_agency,
    create_licensed_certified_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, drop_call, get_call, set_clock,
    create_and_activate_agent, create_enrollment_payload, create_call_session_payload,
    create_agency_payload, create_agent_payload, CLOCK_START, TEST_USERS,
    make_licensed_agent_headers,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _licensed_certified_not_appointed_scenario():
    """Agent holds no live carrier appointment, yet a completed call exists.

    PRD §3.3 only lets an ACTIVE agent connect a call, and PRD §3.2 only makes an
    agent ACTIVE once an APPOINTED appointment exists — so the two violations
    cannot coexist for a never-appointed agent. The anchor is therefore walked
    with the agent fully appointed, and the missing-appointment violation is then
    produced the way the PRD produces it: terminating the agent unwinds every
    APPOINTED appointment to TERMINATED (PRD §3.2, "moves every `APPOINTED`
    appointment to `TERMINATED`") while leaving the already-COMPLETED call and
    the still-CAPTURED scope untouched.
    """
    set_clock(CLOCK_START)
    agency = get_success_data(
        api_client.create_agency(create_agency_payload(), ADMIN))
    carrier = get_success_data(api_client.create_carrier(
        {"legal_name": "Meridian Health Plan of Texas", "naic_number": "60211",
         "contract_type": "CONTRACTED", "initial_commission_rate_pct": 0.20,
         "renewal_commission_rate_pct": 0.10, "chargeback_clawback_pct": 0.25,
         "ack_expected_within_days": 5, "effectuation_expected_within_days": 30},
        ADMIN))
    plan = create_plan(carrier["id"])
    agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
    member, version = create_member_for_agent(agency["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])

    api_client.terminate_agent(agent["id"], {}, DIRECTOR)
    agent = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    return {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent,
            "member": member, "scope": scope, "call": call}


class TestScopeSafetyBeatsAgentAppointmentSafety:
    """A voided scope is answered before the missing appointment is."""

    def test_voided_scope_is_reported_over_the_missing_appointment(self):
        """PRD §2.13: "Then the scope-of-appointment gate: a usable, unconsumed `CAPTURED`
        scope must exist with a non-empty authorization list, else
        `ERR_SCOPE_OF_APPOINTMENT_MISSING`."
        PRD §2.13: "Then the staffing-authority check: the agent must hold an appointment
        in status `APPOINTED`, a license whose `license_status` is `VALID`, and a
        certification in status `CERTIFIED` for the carrier, product type and state of the
        plan being submitted; otherwise `ERR_AGENT_NOT_APPOINTED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_scope_safety_beats_agent_appointment_safety
        """
        scn = _licensed_certified_not_appointed_scenario()
        api_client.void_scope(scn["scope"]["id"],
                              {"reason": "Beneficiary revoked the scope"}, COMPLIANCE)

        headers = make_licensed_agent_headers(scn["agent"]["id"])
        resp = api_client.create_enrollment(create_enrollment_payload(
            scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
            scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"]), headers)
        validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)

    def test_the_second_violation_was_really_present_and_nothing_persisted(self):
        """PRD §2.13: "Then the staffing-authority check: the agent must hold an
        appointment in status `APPOINTED` ... otherwise `ERR_AGENT_NOT_APPOINTED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_scope_safety_beats_agent_appointment_safety
        """
        scn = _licensed_certified_not_appointed_scenario()
        api_client.void_scope(scn["scope"]["id"],
                              {"reason": "Beneficiary revoked the scope"}, COMPLIANCE)

        # The un-appointed violation was genuinely present: the anchor's
        # termination unwound the appointment, so the count is zero.
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["appointed_carrier_count"] == 0
        appointments = get_success_data(
            api_client.list_appointments(scn["agent"]["id"], DIRECTOR))
        assert not [row for row in appointments if row["status"] == "APPOINTED"], (
            "the appointment violation was genuinely present"
        )

        headers = make_licensed_agent_headers(scn["agent"]["id"])
        api_client.create_enrollment(create_enrollment_payload(
            scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
            scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"]), headers)

        rows, _meta = validate_paginated(api_client.list_enrollments(
            DIRECTOR, params={"agent_id": scn["agent"]["id"],
                              "call_session_id": scn["call"]["id"]}))
        assert len(rows) == 0, "the refused submission persisted nothing"


class TestScopeSafetyBeatsCallState:
    """Connecting a dropped call whose scope was voided answers the scope error."""

    def test_voided_scope_is_reported_over_the_call_state(self):
        """PRD §2.13: "Then the scope-of-appointment gate: a usable, unconsumed `CAPTURED`
        scope must exist with a non-empty authorization list, else
        `ERR_SCOPE_OF_APPOINTMENT_MISSING`."
        PRD §2.5: "These scope rules apply to plan-comparison generation, to connecting a
        call, and to submitting an enrollment — all three."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_scope_safety_beats_call_state
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=1)
        agent_id = scn["agent"]["id"]
        call = open_call(agent_id, scn["member_two"]["id"], scn["scope_two"]["id"],
                         started_at="2026-10-01T10:00:00Z",
                         scheduled_end_at="2026-10-01T10:30:00Z",
                         recording_id="REC-1005")
        connect_call(agent_id, call["id"], recording_id="REC-1005")
        drop_call(agent_id, call["id"])
        api_client.void_scope(scn["scope_two"]["id"],
                              {"reason": "Beneficiary revoked the scope"}, COMPLIANCE)

        headers = make_licensed_agent_headers(agent_id)
        resp = api_client.connect_call(call["id"], {
            "disclaimer_delivered": True, "plan_type_discussed": "MAPD",
            "recording_id": "REC-1005", "disclaimer_script_code": "CMS-DISC-2026",
            "marketing_rule_set_version": "MKT-2026-V3",
        }, headers)
        validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)

    def test_the_call_row_is_untouched_by_the_refusal(self):
        """PRD §3.3: "A call in either `RINGING` or `IN_PROGRESS` may be dropped, with an
        optional `reason`, and anything else fails with `ERR_CALL_NOT_DROPPABLE`."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_scope_safety_beats_call_state
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=1)
        agent_id = scn["agent"]["id"]
        call = open_call(agent_id, scn["member_two"]["id"], scn["scope_two"]["id"],
                         started_at="2026-10-01T10:00:00Z",
                         scheduled_end_at="2026-10-01T10:30:00Z",
                         recording_id="REC-1005")
        connect_call(agent_id, call["id"], recording_id="REC-1005")
        dropped = drop_call(agent_id, call["id"])
        api_client.void_scope(scn["scope_two"]["id"],
                              {"reason": "Beneficiary revoked the scope"}, COMPLIANCE)

        headers = make_licensed_agent_headers(agent_id)
        api_client.connect_call(call["id"], {
            "disclaimer_delivered": True, "plan_type_discussed": "MAPD",
            "recording_id": "REC-1005", "disclaimer_script_code": "CMS-DISC-2026",
            "marketing_rule_set_version": "MKT-2026-V3",
        }, headers)

        after = get_call(agent_id, call["id"])
        assert after["status"] == "DROPPED"
        assert after["actual_end_at"] == dropped["actual_end_at"]
        assert after["version"] == dropped["version"], "no mutation occurred"
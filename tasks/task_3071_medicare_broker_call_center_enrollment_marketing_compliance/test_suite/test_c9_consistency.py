"""Immediate consistency: every side effect of a request is visible in the same
response and in every subsequent read, with no reconciliation delay.
"""
import pytest

from test_helpers import (
    validate_paginated, utc, api_client, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_complaint_payload, create_and_activate_agent, create_member_for_agent,
    capture_scope, open_call, connect_call, complete_call, get_call,
    submit_enrollment, acknowledge_enrollment, effectuate_enrollment,
    setup_master_data, create_substantiated_complaints,
    CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def test_immediate_consistency_of_enrollment_counts_and_scope_consumption():
    """PRD §3.6: "the agent's `active_enrollment_count` and the plan's
    `enrolled_member_count` are recomputed, and the open reconciliation period for that
    carrier has its `internal_total_cents` and `variance_cents` recomputed."
    PRD §2.5: "consuming a scope writes the consuming enrollment's id into
    `consumed_by_enrollment_id` and moves the scope to `CONSUMED`."

    Design: Corner/consistency_model/immediate_consistency_of_enrollment_counts_and_scope_consumption
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    enrollment = submit_enrollment(agent["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])

    result = validate_success(
        api_client.effectuate_enrollment(enrollment["id"], CARRIER_INT), 200)
    assert result["submission_status"] == "EFFECTUATED"
    assert result["disenrollment_status"] == "ENROLLED"

    plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    scope_row = get_success_data(api_client.get_scope(
        scope["id"], make_licensed_agent_headers(agent["id"])))
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))

    assert plan["enrolled_member_count"] == 1
    assert agent_row["active_enrollment_count"] == 1
    assert scope_row["status"] == "CONSUMED"
    assert scope_row["consumed_by_enrollment_id"] == enrollment["id"]
    assert agency["commission_balance_cents"] == pytest.approx(5400.00, abs=0.01)


def test_immediate_consistency_of_the_posture_and_its_cascade():
    """PRD §2.7: "The recomputation reads only the standing complaint, call, ledger and
    coaching state and never reads the stored posture, so a single recompute is permitted to
    jump an agency from `OPEN` directly to `FROZEN`".
    PRD §2.7: "If that strike count reaches 5, the posture is `FROZEN`."

    Design: Corner/consistency_model/immediate_consistency_of_the_posture_and_its_cascade
    """
    set_clock(CLOCK_START)
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    scn["agent"] = agent
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])

    create_substantiated_complaints(scn, 4, start_day=15)
    agency_before = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency_before["compliance_posture"] == "RESTRICTED"

    fifth = get_success_data(api_client.create_complaint({
        "agent_id": agent["id"], "complaint_type": "SOA_MISSING", "source": "CMS",
        "severity": "HIGH", "filed_on": "2026-09-30T00:00:00Z",
    }, COMPLIANCE))
    api_client.begin_review(fifth["id"], COMPLIANCE)
    validate_success(api_client.substantiate_complaint(fifth["id"], COMPLIANCE), 200)

    agent_after = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_after["substantiated_complaint_count"] == 5

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["compliance_posture"] == "FROZEN"
    assert agency["posture_since"] == utc(CLOCK_START)

    agent_later = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_later["status"] == "SUSPENDED"
    # The same value on a second read, with no stale window.
    assert agent_later["compliance_risk_score"] == pytest.approx(
        agent_after["compliance_risk_score"], abs=0.01)


def test_every_child_mutation_under_a_frozen_agency_is_refused():
    """PRD §2.7: "every mutating child operation on the agency is refused with
    `ERR_AGENCY_FROZEN`."

    Design: Corner/consistency_model/immediate_consistency_of_the_posture_and_its_cascade
    """
    set_clock(CLOCK_START)
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    scn["agent"] = agent
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)

    create_substantiated_complaints(scn, 5, start_day=15)
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["compliance_posture"] == "FROZEN"

    headers = make_licensed_agent_headers(agent["id"])
    validate_error(api_client.create_call_session({
        "agent_id": agent["id"], "member_id": member["id"],
        "scope_of_appointment_id": scope["id"],
        "started_at": "2026-10-01T09:00:00Z",
        "scheduled_end_at": "2026-10-01T09:30:00Z",
        "recording_id": "REC-1001", "disclaimer_script_code": "CMS-DISC-2026",
        "disclaimer_delivered": True, "marketing_rule_set_version": "MKT-2026-V3",
    }, headers), "ERR_AGENCY_FROZEN", expected_status=403)
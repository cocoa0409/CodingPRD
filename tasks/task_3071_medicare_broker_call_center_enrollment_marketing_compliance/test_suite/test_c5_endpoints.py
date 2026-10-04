"""Endpoint surface: computed reads, the clock lever and the scope void action."""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_carrier_payload, create_coaching_assignment_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, submit_enrollment,
    setup_master_data, setup_two_plan_comparison_scenario,
    setup_three_plan_comparison_scenario, create_plan_comparison_payload,
    CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LICENSING = TEST_USERS["licensing_coordinator_headers"]
COACH = TEST_USERS["coach_headers"]


def test_plan_comparison_computed_read_exposes_the_ranked_plans():
    """PRD §3.4: "The response reports the `member_id`, the `scope_of_appointment_id`, a
    `candidate_plan_count`, the recommended plan's `recommended_plan_id` and
    `recommended_plan_id_code`, its `recommended_composite_score`, and the full
    `ranked_plans` array."

    Design: Corner/endpoints/plan_comparison_computed_read_exposes_the_ranked_plans
    """
    scn = setup_two_plan_comparison_scenario()
    headers = make_licensed_agent_headers(scn["agent"]["id"])
    result = validate_success(api_client.create_plan_comparison(
        create_plan_comparison_payload(scn["member"]["id"], scn["agent"]["id"],
                                       scn["scope"]["id"]), headers), 201)

    assert result["member_id"] == scn["member"]["id"]
    assert result["scope_of_appointment_id"] == scn["scope"]["id"]
    assert result["candidate_plan_count"] == 2
    assert isinstance(result["recommended_plan_id"], str)
    assert result["recommended_plan_id"] in [scn["plan_a"]["id"], scn["plan_b"]["id"]]
    assert isinstance(result["recommended_composite_score"], (int, float))
    assert len(result["ranked_plans"]) == 2

    plans, _meta = validate_paginated(api_client.list_carrier_plans(
        scn["plan_b"]["carrier_id"], ADMIN))
    assert len(plans) == 2
    assert "composite_score" not in plans[0], (
        "the ranking is only reachable through the comparison endpoint"
    )


def test_clock_endpoint_relabels_every_derived_field_in_one_call():
    """PRD §2.6: "The `recording_status` of a call is derived fresh on every read against
    the logical clock and takes exactly one of three values."
    PRD §3.2: "That status is never stored — it is derived on every read by comparing
    `expires_on` against the logical clock".
    PRD §3.9: "the `due_on` date is `assigned_on` plus 14 days, and if the logical clock is
    at or before `due_on` the figure is 0".

    Design: Corner/endpoints/clock_endpoint_relabels_every_derived_field_in_one_call
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"],
        license_overrides={"expires_on": "2026-12-31T00:00:00Z"})
    coaching = get_success_data(api_client.create_coaching_assignment(
        create_coaching_assignment_payload(agent["id"],
                                           coaching_type="MARKETING_RULES"), COACH))
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])

    licenses, _meta = validate_paginated(api_client.list_licenses(agent["id"], LICENSING,
                                                         params={"state_code": "TX"}))
    license_id = licenses[0]["id"]

    result = validate_success(
        api_client.set_clock("2027-01-02T00:00:00Z", ADMIN), 200)
    assert result["current_utc"] == utc("2027-01-02T00:00:00Z")

    licenses, _meta = validate_paginated(api_client.list_licenses(agent["id"], LICENSING,
                                                         params={"state_code": "TX"}))
    assert licenses[0]["license_status"] == "LAPSED"

    coaching_after = get_success_data(
        api_client.get_coaching_assignment(coaching["id"], COACH))
    assert coaching_after["status"] == "OVERDUE"
    assert coaching_after["due_on"] == utc("2026-10-15T00:00:00Z")
    assert coaching_after["overdue_days"] == 79

    call_after = get_call(agent["id"], call["id"])
    # recording_retained_until is started_at plus 2555 days, so it has not passed.
    assert call_after["recording_retained_until"] > "2027-01-02T00:00:00Z"
    assert call_after["recording_status"] == "RECORDED"


def test_scope_void_moves_a_captured_scope_to_voided():
    """PRD §3.3: "A compliance officer may void a captured scope at any time, supplying a
    `reason`, which moves it to `VOIDED`."
    PRD §2.5: "`CAPTURED`, `CONSUMED` and `VOIDED` are the only three scope statuses".

    Design: Corner/endpoints/scope_void_is_the_only_non_terminal_scope_action
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])

    voided = validate_success(api_client.void_scope(
        scope["id"], {"reason": "Beneficiary revoked the scope after the call"},
        COMPLIANCE), 200)
    assert voided["status"] == "VOIDED"
    assert voided["consumed_by_enrollment_id"] is None


def test_a_voided_scope_can_never_authorize_an_enrollment():
    """PRD §2.5: "A scope that has been consumed is no longer usable".
    PRD §2.5: "a scope that is `CONSUMED` or `VOIDED` is permanently unusable."

    Design: Corner/endpoints/scope_void_is_the_only_non_terminal_scope_action
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    api_client.void_scope(scope["id"],
                          {"reason": "Beneficiary revoked the scope"}, COMPLIANCE)

    headers = make_licensed_agent_headers(agent["id"])
    resp = api_client.create_enrollment({
        "call_session_id": call["id"], "member_id": member["id"],
        "plan_id": scn["plan"]["id"], "agent_id": agent["id"],
        "scope_of_appointment_id": scope["id"],
        "effective_date": "2026-11-01T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": call["version"],
    }, headers)
    validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)

    rows, _meta = validate_paginated(api_client.list_member_scopes(member["id"], COMPLIANCE))
    assert len(rows) == 1
    assert rows[0]["status"] == "VOIDED"
    assert rows[0]["status"] != "CONSUMED"
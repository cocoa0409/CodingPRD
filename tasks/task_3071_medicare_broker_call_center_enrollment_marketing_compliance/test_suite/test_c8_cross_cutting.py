"""Cross-cutting concerns: OCC, derived-vs-stored divergence, idempotency and the
absence of any feature flag over the disclaimer obligation.
"""
import pytest

from test_helpers import (
    api_client, utc, get_success_data, validate_error, validate_success, validate_paginated,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_complaint_payload, create_and_activate_agent, create_member_for_agent,
    capture_scope, open_call, connect_call, complete_call, get_call,
    submit_enrollment, acknowledge_enrollment, effectuate_enrollment,
    setup_master_data, setup_complaint_in_review, CLOCK_START, TEST_USERS,
    make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def _completed_call_scenario():
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    scn.update({"agent": agent, "member": member, "scope": scope, "call": call})
    return scn


def test_stale_member_version_on_a_second_scope_of_appointment():
    """PRD §2.12: "The request must carry `expected_member_version`, and that value must
    equal the current `version` of the target member. A mismatch is refused with
    `ERR_STALE_VERSION` at HTTP 412."
    PRD §2.12: "a beneficiary granting a fresh scope after a prior one was voided is ordinary
    business — the second capture is not a state error".

    Design: Corner/cross_cutting/stale_member_version_on_a_second_scope_of_appointment
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    headers = make_licensed_agent_headers(agent["id"])

    # The first capture advanced the member version past the value we hold.
    resp = api_client.create_scope({
        "member_id": member["id"], "agent_id": agent["id"],
        "capture_channel": "ELECTRONIC", "plan_types_authorized": ["PDP"],
        "captured_on": CLOCK_START, "expected_member_version": version,
    }, headers)
    body = validate_error(resp, "ERR_STALE_VERSION", expected_status=412)
    assert body["error_id"] != "ERR_SCOPE_OF_APPOINTMENT_MISSING"

    rows, _meta = validate_paginated(api_client.list_member_scopes(member["id"], COMPLIANCE))
    assert len(rows) == 1

    current = get_success_data(api_client.get_member(member["id"], headers))
    assert current["version"] == version + 1

    second = validate_success(api_client.create_scope({
        "member_id": member["id"], "agent_id": agent["id"],
        "capture_channel": "ELECTRONIC", "plan_types_authorized": ["PDP"],
        "captured_on": CLOCK_START, "expected_member_version": current["version"],
    }, headers), 201)
    assert second["capture_channel"] == "ELECTRONIC"
    rows, _meta = validate_paginated(api_client.list_member_scopes(member["id"], COMPLIANCE))
    assert len(rows) == 2


def test_durable_scope_is_excluded_from_a_default_list_but_returned_on_filter():
    """PRD §2.5: "A scope is usable only while all three of the following hold
    simultaneously: it is still in status `CAPTURED`, the logical clock is at or after
    `captured_on`, and the logical clock is at or before `expires_on`."

    Design: Corner/cross_cutting/durable_scope_is_excluded_from_a_default_list_but_returned_on_filter
    """
    scn = _completed_call_scenario()
    # One day past the closed window's far end: the stored status is still
    # CAPTURED but the scope is no longer usable at the logical clock.
    set_clock("2026-11-01T00:00:00Z")

    headers = make_licensed_agent_headers(scn["agent"]["id"])
    data, _ = validate_paginated(api_client.list_scopes(
        headers, params={"member_id": scn["member"]["id"]}))
    assert len(data) == 1
    assert data[0]["status"] == "CAPTURED"
    assert data[0]["expires_on"] == utc("2026-10-31T00:00:00Z")

    filtered, _ = validate_paginated(api_client.list_scopes(
        headers, params={"member_id": scn["member"]["id"], "status": "CAPTURED"}))
    assert len(filtered) == 1, "a lapsed scope is still discoverable by its stored status"

    resp = api_client.create_enrollment({
        "call_session_id": scn["call"]["id"], "member_id": scn["member"]["id"],
        "plan_id": scn["plan"]["id"], "agent_id": scn["agent"]["id"],
        "scope_of_appointment_id": scn["scope"]["id"],
        "effective_date": "2026-11-01T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": scn["call"]["version"],
    }, headers)
    validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)


def test_compliance_posture_reflects_children_and_gates_them_in_return():
    """PRD §2.7: "the instant it was last set is recorded in `posture_since`."
    PRD §3.11: "Every agent of the agency in status `ACTIVE` is moved to `SUSPENDED`."

    Design: Corner/cross_cutting/compliance_posture_reflects_children_and_gates_them_in_return
    """
    set_clock("2026-10-01T00:00:00Z")
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])

    complaints = [
        get_success_data(api_client.create_complaint({
            "agent_id": agent["id"],
            "complaint_type": ct, "source": "CMS", "severity": "HIGH",
            "filed_on": f"2026-09-{20 + i:02d}T00:00:00Z",
        }, COMPLIANCE))
        for i, ct in enumerate(["MISREPRESENTATION", "DISCLAIMER_MISSING",
                                "RECORDING_MISSING", "UNAPPROVED_MARKETING"])
    ]

    before = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert before["open_complaint_count"] == 4

    api_client.begin_review(complaints[3]["id"], COMPLIANCE)
    validate_success(api_client.substantiate_complaint(complaints[3]["id"], COMPLIANCE), 200)

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["open_complaint_count"] == 3
    assert agency["compliance_posture"] == "RESTRICTED"

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["status"] == "SUSPENDED"
    assert agent_row["live_call_count"] == 0

    call_row = get_call(agent["id"], call["id"])
    assert call_row["status"] == "DROPPED"


def test_idempotent_acknowledgment_is_refused_rather_than_replayed():
    """PRD §3.6: "An acknowledgment requires the enrollment to be `SUBMITTED`, else
    `ERR_ENROLLMENT_NOT_SUBMITTED`".

    Design: Corner/cross_cutting/idempotent_acknowledgment_is_refused_rather_than_replayed
    """
    scn = _completed_call_scenario()
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    acked = acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])

    resp = api_client.acknowledge_enrollment(
        enrollment["id"], {"carrier_id": scn["carrier"]["id"]}, CARRIER_INT)
    validate_error(resp, "ERR_ENROLLMENT_NOT_SUBMITTED", expected_status=409)

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    assert len(rows) == 2, "the refusal posted no further entry"

    after = get_success_data(api_client.get_enrollment(enrollment["id"], DIRECTOR))
    assert after["acknowledged_on"] == acked["acknowledged_on"]
    assert after["version"] == acked["version"]

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["commission_balance_cents"] == pytest.approx(5400.00, abs=0.01)


def test_no_flag_or_configuration_input_changes_the_disclaimer_obligation():
    """PRD §2.6: "This pair of obligations is waived only when the attached scope's
    `capture_channel` is `WRITTEN`."
    PRD §2.6: "Before any plan type is discussed, two obligations must be satisfied
    together: a recording must exist for the call, and the CMS disclaimer identified by
    `disclaimer_script_code` must have been delivered."

    Design: Corner/cross_cutting/no_flag_or_configuration_input_changes_the_disclaimer_obligation
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = setup_master_data()
    # A second agency with every retention and capacity setting different.
    other = get_success_data(api_client.create_agency(create_agency_payload(
        name="Cascade Health Partners", service_center_code="CAS-PDX-02",
        aep_daily_submission_capacity=9, recording_retention_days=100,
        soa_retention_days=50, soa_max_age_days=5,
        rapid_disenrollment_day_limit=10), ADMIN))
    assert other["id"] != scn["agency"]["id"]

    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"],
                     recording_id=None, disclaimer_script_code=None,
                     disclaimer_delivered=False, marketing_rule_set_version=None)

    resp = api_client.connect_call(call["id"], {"disclaimer_delivered": False},
                                   make_licensed_agent_headers(agent["id"]))
    validate_error(resp, "ERR_DISCLAIMER_NOT_DELIVERED", expected_status=422)

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["compliance_posture"] == "OPEN"
    assert "disclaimer_flag" not in agency
    assert "disclaimer_required" not in agency

    after = get_call(agent["id"], call["id"])
    assert after["status"] == "RINGING"
    assert after["version"] == 1
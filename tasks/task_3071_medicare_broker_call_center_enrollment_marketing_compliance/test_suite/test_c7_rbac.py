"""Role-based access control: each role owns a separable operational surface."""
import pytest

from test_helpers import (
    validate_paginated, api_client, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_carrier_payload, create_plan_payload, create_complaint_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, submit_enrollment,
    acknowledge_enrollment, effectuate_enrollment, setup_master_data,
    setup_complaint_in_review, CLOCK_START, TEST_USERS,
    make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LICENSING = TEST_USERS["licensing_coordinator_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def _master_with_agent(**agency_overrides):
    scn = setup_master_data(**agency_overrides)
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    scn["agent"] = agent
    return scn


def _completed_call_scenario():
    scn = _master_with_agent()
    member, version = create_member_for_agent(scn["agency"]["id"], scn["agent"]["id"])
    scope = capture_scope(member["id"], scn["agent"]["id"], version)
    call = open_call(scn["agent"]["id"], member["id"], scope["id"])
    connect_call(scn["agent"]["id"], call["id"])
    call = complete_call(scn["agent"]["id"], call["id"])
    scn.update({"member": member, "scope": scope, "call": call})
    return scn


def test_licensed_agent_cannot_file_a_complaint_against_itself():
    """PRD §2.1: "`ComplianceOfficer` governs posture, adjudicates complaints, oversees
    coaching, reinstates agents, amends calls and voids scopes".
    PRD §2.1: "The eighth role is different. When `X-User-Role` is `LicensedAgent`,
    `X-User-ID` is the `id` of the acting `Agent`".

    Design: Corner/rbac/licensed_agent_cannot_file_a_complaint_against_itself
    """
    scn = _completed_call_scenario()
    payload = {
        "agent_id": scn["agent"]["id"], "complaint_type": "MISREPRESENTATION",
        "source": "BENEFICIARY", "severity": "LOW", "filed_on": "2026-09-28T00:00:00Z",
    }
    resp = api_client.create_complaint(
        payload, make_licensed_agent_headers(scn["agent"]["id"]))
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    rows, _meta = validate_paginated(api_client.list_agent_complaints(
        scn["agent"]["id"], COMPLIANCE))
    assert len(rows) == 0
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["open_complaint_count"] == 0

    ok = validate_success(api_client.create_complaint(payload, COMPLIANCE), 201)
    assert ok["status"] == "OPEN"


def test_director_of_sales_cannot_substantiate_a_complaint():
    """PRD §2.1: "`DirectorOfSales` owns the agent lifecycle on the staffing side, plus
    every ledger finalization, reversal, correction and carrier reconciliation; it may not
    substantiate complaints and may not capture a scope of appointment."
    PRD §2.1: "Authorization beyond authentication is a strict allow-list: each endpoint
    names the roles permitted to call it, and a role that is not named is denied outright
    rather than silently downgraded to a read-only view. A denied call returns
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/director_of_sales_cannot_substantiate_a_complaint
    """
    scn = _completed_call_scenario()
    complaint = setup_complaint_in_review(scn, complaint_type="MISREPRESENTATION",
                                          source="CMS", severity="MEDIUM",
                                          filed_on="2026-09-28T00:00:00Z")
    cid = complaint["id"]

    resp = api_client.substantiate_complaint(cid, DIRECTOR)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    after = get_success_data(api_client.get_complaint(cid, COMPLIANCE))
    assert after["status"] == "UNDER_REVIEW"
    assert after["finding_code"] is None
    assert after["substantiated_on"] is None

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["substantiated_complaint_count"] == 0
    assert agent["open_coaching_count"] == 0

    done = validate_success(api_client.substantiate_complaint(cid, COMPLIANCE), 200)
    assert done["finding_code"] == "MARKETING_VIOLATION"


def test_coach_cannot_close_a_complaint():
    """PRD §2.1: "`Coach` works only the coaching assignments, and may not open or close a
    complaint."

    Design: Corner/rbac/coach_cannot_create_or_close_a_coaching_assignment
    """
    scn = _completed_call_scenario()
    complaint = setup_complaint_in_review(scn, complaint_type="MISREPRESENTATION",
                                          source="CMS", severity="MEDIUM",
                                          filed_on="2026-09-28T00:00:00Z")
    cid = complaint["id"]
    validate_success(api_client.substantiate_complaint(cid, COMPLIANCE), 200)

    assignments, _meta = validate_paginated(api_client.list_coaching_assignments(
        COACH, params={"complaint_id": cid}))
    assert len(assignments) == 1
    coaching_id = assignments[0]["id"]

    readable = validate_success(
        api_client.get_coaching_assignment(coaching_id, COACH), 200)
    assert readable["status"] == "ASSIGNED"

    validate_error(api_client.close_complaint(cid, COACH),
                   "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    after = get_success_data(api_client.get_complaint(cid, COMPLIANCE))
    assert after["status"] == "SUBSTANTIATED"
    # The complaint is no longer OPEN or UNDER_REVIEW, so it no longer counts as
    # open (PRD §2.7: "the number of complaints in status `OPEN` or `UNDER_REVIEW`").
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["open_complaint_count"] == 0

    assignment_after = get_success_data(
        api_client.get_coaching_assignment(coaching_id, COACH))
    assert assignment_after["status"] == "ASSIGNED"
    assert assignment_after["completed_on"] is None

    started = validate_success(api_client.start_coaching(coaching_id, COACH), 200)
    assert started["status"] == "IN_PROGRESS"


def test_platform_admin_cannot_connect_an_agent_call():
    """PRD §2.1: "`PlatformAdmin` configures agencies, carriers, plans, formulary rows,
    pharmacy network entries and provider directory entries, sets the logical clock, and
    never performs an agent's call or enrollment work."
    PRD §2.1: "Seven of the eight roles are opaque operator identities."

    Design: Corner/rbac/platform_admin_cannot_connect_an_agent_call
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = _master_with_agent()
    member, version = create_member_for_agent(scn["agency"]["id"], scn["agent"]["id"])
    scope = capture_scope(member["id"], scn["agent"]["id"], version)
    call = open_call(scn["agent"]["id"], member["id"], scope["id"])

    resp = api_client.connect_call(call["id"], {
        "disclaimer_delivered": True, "plan_type_discussed": "MAPD",
        "recording_id": "REC-1001", "disclaimer_script_code": "CMS-DISC-2026",
        "marketing_rule_set_version": "MKT-2026-V3",
    }, ADMIN)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    after = get_call(scn["agent"]["id"], call["id"])
    assert after["status"] == "RINGING"
    assert after["version"] == 1

    # PlatformAdmin's own configuration surface still works without an entity id.
    validate_success(api_client.create_plan({
        "carrier_id": scn["carrier"]["id"], "plan_id_code": "MER-H0021-009",
        "plan_type": "MAPD", "state_code": "TX", "county_code": "TX-201",
        "monthly_premium_cents": 1500, "annual_drug_deductible_cents": 20000,
        "star_rating": 4.5, "formulary_id": "FORM-2026-V1",
        "pharmacy_network_id": "PHARM-2026-V1",
        "provider_directory_id": "PROV-2026-V1",
    }, ADMIN), 201)

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["live_call_count"] == 0


def test_licensing_coordinator_cannot_touch_plans_or_money():
    """PRD §2.1: "`LicensingCoordinator` records state licenses, carrier certifications and
    carrier appointments, and touches neither enrollments nor money."

    Design: Corner/rbac/licensing_coordinator_cannot_touch_plans_or_money
    """
    scn = _master_with_agent()
    member, version = create_member_for_agent(scn["agency"]["id"], scn["agent"]["id"])
    scope = capture_scope(member["id"], scn["agent"]["id"], version)
    call = open_call(scn["agent"]["id"], member["id"], scope["id"])
    connect_call(scn["agent"]["id"], call["id"])
    call = complete_call(scn["agent"]["id"], call["id"])
    enrollment = submit_enrollment(scn["agent"]["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    # An effectuated enrollment carries its INITIAL and its RENEWAL entry.
    assert len(rows) == 2
    entry_id = rows[0]["id"]

    validate_error(api_client.create_plan({
        "carrier_id": scn["carrier"]["id"], "plan_id_code": "MER-H0021-002",
        "plan_type": "MAPD", "state_code": "TX", "county_code": "TX-201",
        "monthly_premium_cents": 1500, "annual_drug_deductible_cents": 20000,
        "star_rating": 4.5, "formulary_id": "FORM-2026-V1",
        "pharmacy_network_id": "PHARM-2026-V1",
        "provider_directory_id": "PROV-2026-V1",
    }, LICENSING), "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    validate_error(api_client.finalize_ledger_entry(entry_id, LICENSING),
                   "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    plans, _meta = validate_paginated(api_client.list_carrier_plans(scn["carrier"]["id"], ADMIN))
    assert len(plans) == 1, "the refused plan creation persisted nothing"
    after = get_success_data(api_client.get_ledger_entry(entry_id, DIRECTOR))
    assert after["status"] == "PROVISIONAL"
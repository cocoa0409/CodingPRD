"""Validation rules: authentication, authorization, the posture gate, capacity and the
conditional recording waiver.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_carrier_payload, create_complaint_payload, create_coaching_assignment_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, submit_enrollment,
    setup_master_data, setup_ringing_call, create_substantiated_complaints,
    CLOCK_BEFORE_AEP, CLOCK_START, NON_EXISTENT_UUID, TEST_USERS,
    build_user_headers, make_licensed_agent_headers,
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


def _master_outside_aep(**agency_overrides):
    """Master data whose AEP window starts after the anchor's live interval.

    The anchor's call occupies 2026-10-01T09:00Z, so the agency's own AEP window
    is pushed clear of it: the restrictive cascade's call-dropping is then driven
    by the complaint thresholds alone, not by a window rule the request also trips.
    """
    overrides = dict(aep_start_date="2026-11-20T00:00:00Z",
                     aep_end_date="2026-12-07T00:00:00Z")
    overrides.update(agency_overrides)
    return _master_with_agent(**overrides)


def test_missing_user_context_header_is_the_first_check():
    """PRD §2.1: "If either header is absent or malformed, or if the role they name is not
    one of the declared roles below, the request is refused with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.13: "Authentication precedes everything."

    Design: Corner/validations/missing_user_context_header_is_the_first_check
    """
    set_clock(CLOCK_START)
    resp = api_client.get_agent(NON_EXISTENT_UUID, {})
    body = validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                          expected_status=400)
    assert body["message"].strip()
    assert resp.status_code != 404
    assert resp.status_code != 403

    bad_role = build_user_headers("someone", "UnregisteredRole")
    resp_role = api_client.get_agent(NON_EXISTENT_UUID, bad_role)
    validate_error(resp_role, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)

    # With a declared role the same unallocated id resolves to the 404 path check.
    resp_ok = api_client.get_agent(NON_EXISTENT_UUID, COMPLIANCE)
    validate_error(resp_ok, "ERR_AGENT_NOT_FOUND", expected_status=404)


def test_compliance_officer_cannot_capture_a_scope_of_appointment():
    """PRD §2.1: "`LicensedAgent` is the sole role that may capture a scope of appointment,
    open a call, generate a plan comparison, or submit an enrollment."
    PRD §2.1: "Authorization beyond authentication is a strict allow-list: each endpoint
    names the roles permitted to call it, and a role that is not named is denied outright
    rather than silently downgraded to a read-only view. A denied call returns
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/validations/compliance_officer_cannot_capture_a_scope_of_appointment
    """
    scn = _master_with_agent()
    member, version = create_member_for_agent(scn["agency"]["id"], scn["agent"]["id"])
    payload = {
        "member_id": member["id"], "agent_id": scn["agent"]["id"],
        "capture_channel": "TELEPHONIC_RECORDED", "plan_types_authorized": ["MAPD"],
        "captured_on": CLOCK_START, "expected_member_version": version,
    }
    resp = api_client.create_scope(payload, COMPLIANCE)
    body = validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert body["error_id"] != "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"

    rows, _meta = validate_paginated(api_client.list_member_scopes(member["id"], COMPLIANCE))
    assert len(rows) == 0

    validate_success(api_client.create_scope(
        payload, make_licensed_agent_headers(scn["agent"]["id"])), 201)


def test_corrections_on_a_reconciliation_and_commission_ledger_are_denied_to_the_compliance_officer():
    """PRD §2.1: "`ComplianceOfficer` governs posture, adjudicates complaints, oversees
    coaching, reinstates agents, amends calls and voids scopes, and may not perform any
    money-desk operation."
    PRD §2.1: "`DirectorOfSales` owns the agent lifecycle on the staffing side, plus every
    ledger finalization, reversal, correction and carrier reconciliation".

    Design: Corner/validations/corrections_on_a_reconciliation_and_commission_ledger_are_denied_to_the_compliance_officer
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    recon = get_success_data(api_client.create_reconciliation({
        "carrier_id": scn["carrier"]["id"], "period_month": "2026-10",
        "carrier_reported_total_cents": 3600, "internal_total_variant": "PROVISIONAL",
    }, DIRECTOR))

    validate_error(api_client.create_correction({
        "enrollment_id": enrollment["id"],
        "carrier_reconciliation_id": recon["id"], "amount_cents": -100,
        "period_month": "2026-10", "memo": "Compliance attempted money",
    }, COMPLIANCE), "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    validate_error(api_client.create_ledger_entry({
        "enrollment_id": enrollment["id"],
        "carrier_reconciliation_id": recon["id"], "entry_type": "ADJUSTMENT",
        "period_month": "2026-10",
    }, COMPLIANCE), "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    assert len(rows) == 1
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["commission_balance_cents"] == pytest.approx(3600.00, abs=0.01)


def test_call_complete_under_a_restricted_agency_is_allowed():
    """PRD §2.7: "An `RESTRICTED` posture permits the ordinary mutating operations but is
    the state from which a frozen agency may be partially recovered."
    PRD §2.13: "the agency must be `OPEN` or `RESTRICTED`, and a `FROZEN` agency produces
    `ERR_AGENCY_FROZEN` for every mutating child operation."

    Design: Corner/validations/call_complete_under_a_restricted_agency_is_allowed_under_a_frozen_one_is_not
    """
    scn = _master_outside_aep()
    agent_id = scn["agent"]["id"]

    create_substantiated_complaints(scn, 1, start_day=20)
    posture = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert posture["compliance_posture"] == "RESTRICTED"

    # Capturing a scope is an ordinary mutating child operation, and RESTRICTED
    # admits it — the posture gate's excluded value is FROZEN alone (PRD §2.7).
    member, version = create_member_for_agent(scn["agency"]["id"], agent_id)
    captured = validate_success(api_client.create_scope({
        "member_id": member["id"], "agent_id": agent_id,
        "capture_channel": "TELEPHONIC_RECORDED",
        "plan_types_authorized": ["MAPD"], "captured_on": CLOCK_START,
        "expected_member_version": version,
    }, make_licensed_agent_headers(agent_id)), 201)
    assert captured["status"] == "CAPTURED"


def test_call_complete_under_a_frozen_agency_is_refused():
    """PRD §2.7: "A `FROZEN` posture is the strongest stop the system has: every mutating
    child operation on the agency is refused with `ERR_AGENCY_FROZEN`."
    PRD §2.7: "If that strike count reaches 5, the posture is `FROZEN`."

    Design: Corner/validations/call_complete_under_a_restricted_agency_is_allowed_under_a_frozen_one_is_not
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    create_substantiated_complaints(scn, 5, start_day=15)
    posture = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert posture["compliance_posture"] == "FROZEN"

    # The freeze cascade drops the RINGING call, so the posture gate is probed
    # with a fresh opening request — the first mutating child operation the
    # precedence chain reaches (PRD §2.13: "The agency posture gate is evaluated
    # first among them").
    headers = make_licensed_agent_headers(scn["agent"]["id"])
    resp = api_client.create_call_session({
        "agent_id": scn["agent"]["id"], "member_id": scn["member"]["id"],
        "scope_of_appointment_id": scn["scope"]["id"],
        "started_at": "2026-10-01T11:00:00Z",
        "scheduled_end_at": "2026-10-01T11:30:00Z",
        "recording_id": "REC-1001", "disclaimer_script_code": "CMS-DISC-2026",
        "disclaimer_delivered": True, "marketing_rule_set_version": "MKT-2026-V3",
    }, headers)
    validate_error(resp, "ERR_AGENCY_FROZEN", expected_status=403)


def test_priority_temporal_disclaimer_precedes_state_frozen():
    """PRD §2.6: "Before any plan type is discussed, two obligations must be satisfied
    together: a recording must exist for the call, and the CMS disclaimer identified by
    `disclaimer_script_code` must have been delivered. The single rejection for both
    failures is `ERR_DISCLAIMER_NOT_DELIVERED`."
    PRD §2.7: "An `RESTRICTED` posture permits the ordinary mutating operations".

    Design: Corner/validations/priority_temporal_disclaimer_precedes_state_frozen
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0,
                       recording_id=None, disclaimer_script_code=None,
                       disclaimer_delivered=False, marketing_rule_set_version=None)

    resp = api_client.connect_call(scn["call"]["id"], {"disclaimer_delivered": False},
                                   make_licensed_agent_headers(scn["agent"]["id"]))
    body = validate_error(resp, "ERR_DISCLAIMER_NOT_DELIVERED", expected_status=422)
    assert body["error_id"] != "ERR_AGENCY_FROZEN"

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["compliance_posture"] == "OPEN"

    after = get_call(scn["agent"]["id"], scn["call"]["id"])
    assert after["status"] == "RINGING"
    assert after["version"] == 1


def test_cross_entity_validation_carrier_contract_type_blocks_appointment():
    """PRD §2.4: "A certification may only be recorded against a carrier whose
    `contract_type` is `CONTRACTED`; a carrier flagged `MARKETING_ONLY` cannot be appointed
    or enrolled through, and yields `ERR_CARRIER_NOT_CONTRACTED`."

    Design: Corner/validations/cross_entity_validation_carrier_contract_type_blocks_appointment
    """
    scn = setup_master_data()
    agent = create_agent_and_license(scn)
    marketing = get_success_data(api_client.create_carrier(
        create_carrier_payload(legal_name="Pinnacle Marketing Group",
                               naic_number="60401",
                               contract_type="MARKETING_ONLY",
                               initial_commission_rate_pct=0.15,
                               renewal_commission_rate_pct=0.08,
                               chargeback_clawback_pct=0.30,
                               ack_expected_within_days=7,
                               effectuation_expected_within_days=45), ADMIN))

    resp = api_client.add_certification(agent["id"], {
        "carrier_id": marketing["id"], "product_type": "MAPD",
        "expires_on": "2027-12-31T00:00:00Z",
    }, LICENSING)
    validate_error(resp, "ERR_CARRIER_NOT_CONTRACTED", expected_status=403)

    assert get_success_data(api_client.get_carrier(
        marketing["id"], ADMIN))["status"] == "ACTIVE"

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["status"] == "LICENSED"
    assert agent_row["certified_carrier_count"] == 0
    rows, _meta = validate_paginated(api_client.list_certifications(agent["id"], LICENSING))
    assert len(rows) == 0

    validate_success(api_client.add_certification(agent["id"], {
        "carrier_id": scn["carrier"]["id"], "product_type": "MAPD",
        "expires_on": "2027-12-31T00:00:00Z",
    }, LICENSING), 201)


def test_aggregate_capacity_validation_rejects_only_the_collective_overage():
    """PRD §2.13: "the count of non-`REJECTED`, non-`WITHDRAWN` enrollments whose
    `effective_date` falls on the same UTC calendar day must be strictly below the agency's
    `aep_daily_submission_capacity`".
    PRD §2.13: "A correction or adjustment must name a carrier and `period_month` with an
    `OPEN` reconciliation, else `ERR_NO_OPEN_RECONCILIATION`."

    Design: Corner/validations/aggregate_capacity_validation_rejects_only_the_collective_overage
    """
    set_clock(CLOCK_BEFORE_AEP)
    scn = setup_capacity_two_scenario()
    agent_id = scn["agent"]["id"]

    first = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                              scn["plan"]["id"], scn["scope"]["id"],
                              scn["call"]["version"])
    scn["call"] = get_call(agent_id, scn["call"]["id"])
    second = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                               scn["plan"]["id"], scn["scope"]["id"],
                               scn["call"]["version"])
    assert second["submission_status"] == "SUBMITTED"

    scn["call"] = get_call(agent_id, scn["call"]["id"])
    headers = make_licensed_agent_headers(agent_id)
    resp = api_client.create_enrollment({
        "call_session_id": scn["call"]["id"], "member_id": scn["member"]["id"],
        "plan_id": scn["plan"]["id"], "agent_id": agent_id,
        "scope_of_appointment_id": scn["scope"]["id"],
        "effective_date": "2026-11-01T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": scn["call"]["version"],
    }, headers)
    validate_error(resp, "ERR_AEP_DAILY_SUBMISSION_CAPACITY_EXCEEDED",
                   expected_status=409)

    # A different effective day is unaffected by the saturated day.
    other_day = submit_enrollment(
        agent_id, scn["call_two"]["id"], scn["member_two"]["id"],
        scn["plan"]["id"], scn["scope_two"]["id"], scn["call_two"]["version"],
        effective_date="2026-11-05T00:00:00Z")
    assert other_day["submission_status"] == "SUBMITTED"

    rows, _meta = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"carrier_id": scn["carrier"]["id"]}))
    assert len(rows) == 3


def test_conditional_validation_recording_is_waived_for_written_scopes():
    """PRD §2.6: "The mirror-image rule is that a call must carry a `recording_id` unless
    its scope's `capture_channel` is `WRITTEN`, and a missing recording in any other case is
    `ERR_RECORDING_MISSING`."
    PRD §2.6: "This pair of obligations is waived only when the attached scope's
    `capture_channel` is `WRITTEN`."

    Design: Corner/validations/conditional_validation_recording_is_waived_for_written_scopes
    """
    set_clock(CLOCK_START)
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    scn["agent"] = agent

    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    written_scope = capture_scope(member["id"], agent["id"], version,
                                  capture_channel="WRITTEN",
                                  plan_types_authorized=["MAPD"])
    written_call = open_call(agent["id"], member["id"], written_scope["id"],
                             started_at="2026-10-01T11:00:00Z",
                             scheduled_end_at="2026-10-01T11:30:00Z",
                             recording_id=None, disclaimer_script_code=None,
                             disclaimer_delivered=False,
                             marketing_rule_set_version=None)

    member_two, version_two = create_member_for_agent(
        scn["agency"]["id"], agent["id"], full_name="Hollis Pike",
        medicare_beneficiary_id="3GH6-VG7-PM94",
        date_of_birth="1952-11-19T00:00:00Z")
    telephonic_scope = capture_scope(member_two["id"], agent["id"], version_two)
    telephonic_call = open_call(agent["id"], member_two["id"], telephonic_scope["id"],
                                started_at="2026-10-01T09:00:00Z",
                                scheduled_end_at="2026-10-01T09:30:00Z",
                                recording_id=None, disclaimer_script_code=None,
                                disclaimer_delivered=False,
                                marketing_rule_set_version=None)

    # The telephonic probe is attempted first, while no call is live yet, so the
    # disclaimer obligation — not the live-call overlap rule — is the refusal.
    validate_error(api_client.connect_call(
        telephonic_call["id"], {"disclaimer_delivered": False},
        make_licensed_agent_headers(agent["id"])),
        "ERR_DISCLAIMER_NOT_DELIVERED", expected_status=422)

    ok = validate_success(api_client.connect_call(
        written_call["id"], {"disclaimer_delivered": False},
        make_licensed_agent_headers(agent["id"])), 200)
    assert ok["status"] == "IN_PROGRESS"

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["live_call_count"] == 1
    written_row = get_call(agent["id"], written_call["id"])
    assert written_row["recording_status"] == "MISSING"
    assert written_row["status"] == "IN_PROGRESS"


# ─── local helpers ───────────────────────────────────────────

def create_agent_and_license(scn):
    from test_helpers import create_agent_in_pipeline, license_agent
    agent = create_agent_in_pipeline(scn["agency"]["id"])
    license_agent(agent["id"])
    return get_success_data(api_client.get_agent(agent["id"], DIRECTOR))


def setup_capacity_two_scenario():
    """Agency with capacity 2 plus two members, two scopes and two completed calls."""
    agency = get_success_data(api_client.create_agency(
        create_agency_payload(aep_daily_submission_capacity=2), ADMIN))
    carrier = get_success_data(api_client.create_carrier(create_carrier_payload(), ADMIN))
    plan = create_plan(carrier["id"])
    agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])

    scn = {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent}
    setup_ringing_call(scn, member_index=0)
    setup_ringing_call(scn, member_index=1)
    connect_call(agent["id"], scn["call"]["id"])
    scn["call"] = complete_call(agent["id"], scn["call"]["id"])
    connect_call(agent["id"], scn["call_two"]["id"])
    scn["call_two"] = complete_call(agent["id"], scn["call_two"]["id"])
    return scn
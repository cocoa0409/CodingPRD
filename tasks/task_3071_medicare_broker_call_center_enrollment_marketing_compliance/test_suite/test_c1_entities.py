"""Entity creation, retrieval and listing behaviour."""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error, validate_success, validate_paginated, utc,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_carrier_payload, create_plan_payload, create_member_payload,
    create_call_session_payload, create_enrollment_payload,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    setup_ringing_call, setup_submitted_enrollment, setup_three_enrollment_listing_scenario,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call,
    CLOCK_START, NON_EXISTENT_UUID, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LICENSING = TEST_USERS["licensing_coordinator_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def test_agency_create_returns_every_declared_field_and_opens_posture():
    """PRD §3.1: "A newly created agency starts its derived life in a known configuration:
    `compliance_posture` begins at `OPEN`, `commission_balance_cents` begins at 0,
    `open_complaint_count` begins at 0, and `substantiated_complaint_rate` begins at 0."
    PRD §2.10: "`version` is an integer that increments by one on every mutation of the
    resource and is used for optimistic concurrency control."

    Design: Corner/entities/agency_create_returns_every_declared_field_and_opens_posture
    """
    set_clock(CLOCK_START)
    agency = validate_success(
        api_client.create_agency(create_agency_payload(), ADMIN), 201)

    assert agency["compliance_posture"] == "OPEN"
    assert agency["posture_since"] == utc(CLOCK_START)
    assert agency["commission_balance_cents"] == 0
    assert agency["open_complaint_count"] == 0
    assert agency["substantiated_complaint_rate"] == 0
    assert agency["loss_ratio"] == 0
    assert agency["version"] == 1
    assert agency["id"]
    assert agency["created_at"]
    assert agency["updated_at"]
    assert agency["aep_daily_submission_capacity"] == 3
    assert agency["recording_retention_days"] == 2555


def test_plan_create_returns_declared_fields_and_opens_active():
    """PRD §3.1: "A new plan starts in status `ACTIVE` with `enrolled_member_count` at 0;
    the plan status enum is `ACTIVE` or `TERMINATED`, and only `ACTIVE` plans may be
    recommended or enrolled into."
    PRD §3.1: "Three version identifiers pin the reference data the plan was built from:
    `formulary_id`, `pharmacy_network_id` and `provider_directory_id`."

    Design: Corner/entities/plan_create_returns_declared_fields_and_opens_active
    """
    set_clock(CLOCK_START)
    agency = create_agency()
    carrier = create_carrier()
    plan = validate_success(api_client.create_plan(
        create_plan_payload(carrier["id"]), ADMIN), 201)

    assert plan["status"] == "ACTIVE"
    assert plan["enrolled_member_count"] == 0
    assert plan["formulary_id"] == "FORM-2026-V1"
    assert plan["pharmacy_network_id"] == "PHARM-2026-V1"
    assert plan["provider_directory_id"] == "PROV-2026-V1"
    assert plan["star_rating"] == pytest.approx(4.5, abs=1e-9)
    assert plan["monthly_premium_cents"] == 1500

    rows, _meta = validate_paginated(api_client.list_carrier_plans(carrier["id"], ADMIN))
    assert len(rows) == 1
    assert rows[0]["id"] == plan["id"]


def test_carrier_get_returns_stored_contract_terms():
    """PRD §3.1: "Two timing expectations are configured here as well:
    `ack_expected_within_days` defaults to 5 and gives the carrier that many days from the
    submission instant to acknowledge, while `effectuation_expected_within_days` defaults
    to 30".
    PRD §3.1: "A new carrier begins with `status` `ACTIVE`; the status enum is `ACTIVE` or
    `SUSPENDED`."

    Design: Corner/entities/carrier_get_returns_stored_contract_terms
    """
    set_clock(CLOCK_START)
    carrier = validate_success(api_client.create_carrier(
        create_carrier_payload(), ADMIN), 201)
    fetched = validate_success(
        api_client.get_carrier(carrier["id"], CARRIER_INT), 200)

    assert fetched["initial_commission_rate_pct"] == pytest.approx(0.20, abs=1e-9)
    assert fetched["renewal_commission_rate_pct"] == pytest.approx(0.10, abs=1e-9)
    assert fetched["chargeback_clawback_pct"] == pytest.approx(0.25, abs=1e-9)
    assert fetched["ack_expected_within_days"] == 5
    assert fetched["effectuation_expected_within_days"] == 30
    assert fetched["contract_type"] == "CONTRACTED"
    assert fetched["status"] == "ACTIVE"
    assert fetched["version"] == 1
    assert fetched["created_at"] == fetched["updated_at"]


def test_enrollments_list_paginates_and_filters_by_carrier():
    """PRD §2.3: "`limit` caps the number of items returned, defaults to 10, and must fall
    between a minimum of 1 and a maximum of 100. `offset` skips that many items and defaults
    to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`".

    Design: Corner/entities/enrollments_list_paginates_and_filters_by_carrier
    """
    scn = setup_three_enrollment_listing_scenario()
    carrier_id = scn["carrier"]["id"]

    data, meta = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"carrier_id": carrier_id, "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"carrier_id": carrier_id, "limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_enrollments_list_filters_narrow_the_total_count():
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`; single-resource responses omit those four fields."

    Design: Corner/entities/enrollments_list_paginates_and_filters_by_carrier
    """
    scn = setup_three_enrollment_listing_scenario()

    data, meta = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"member_id": scn["member_two"]["id"]}))
    assert len(data) == 1
    assert meta["total_count"] == 1

    data_all, meta_all = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"submission_status": "SUBMITTED"}))
    assert len(data_all) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_agent_get_with_an_unknown_id_returns_agent_not_found():
    """PRD §2.9: "the identifiers are validated left to right in the order they appear in
    the path, and the request is rejected at the first segment that does not resolve,
    producing that segment's entity-specific not-found error."
    PRD §2.9: "along with `ERR_AGENCY_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_AGENT_NOT_FOUND`".

    Design: Corner/entities/agent_get_with_an_unknown_id_returns_agent_not_found
    """
    set_clock(CLOCK_START)
    resp = api_client.get_agent(NON_EXISTENT_UUID, COMPLIANCE)
    body = validate_error(resp, "ERR_AGENT_NOT_FOUND", expected_status=404)
    assert body["message"].strip()
    assert resp.status_code != 400
    assert resp.status_code != 500


def test_call_session_create_missing_scope_returns_invalid_request():
    """PRD §2.13: "Next come existence checks. Path resource identifiers are resolved left
    to right in path order and the first unresolvable segment produces its entity-specific
    not-found error at HTTP 404."
    PRD §3.3: "With a scope in hand the agent opens a **CallSession**, attaching the scope
    through `scope_of_appointment_id` and naming the `agent_id` and `member_id`."

    Design: Corner/entities/call_session_create_missing_scope_returns_invalid_request
    """
    scn = setup_master_data_for_corner()
    scn = setup_scope_and_completed_call(scn, member_index=0)
    payload = create_call_session_payload(
        scn["agent"]["id"], scn["member"]["id"], scn["scope"]["id"])
    del payload["scope_of_appointment_id"]

    headers = make_licensed_agent_headers(scn["agent"]["id"])
    resp = api_client.create_call_session(payload, headers)
    body = validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)
    assert body["error_id"] != "ERR_SCOPE_OF_APPOINTMENT_MISSING"

    rows, _meta = validate_paginated(api_client.list_agent_call_sessions(
        scn["agent"]["id"], DIRECTOR))
    assert len(rows) == 1  # only the completed call from the anchor


def test_call_session_create_omitting_optional_fields_applies_declared_defaults():
    """PRD §3.3: "Optional fields captured at open time include the `recording_id`, the
    `disclaimer_script_code` naming the CMS disclaimer that must be played, the
    `disclaimer_delivered` flag, and the `marketing_rule_set_version`"
    PRD §2.6: "`recording_retained_until` is the call's `started_at` plus the owning
    agency's `recording_retention_days`, which defaults to 2555."
    PRD §2.6: "It reads `MISSING` when `recording_id` is null."

    Design: Corner/entities/call_session_create_omitting_optional_fields_applies_declared_defaults
    """
    scn = setup_master_data_for_corner()
    setup_scope_and_completed_call(scn, member_index=0)
    setup_ringing_call(scn, member_index=1)
    headers = make_licensed_agent_headers(scn["agent"]["id"])
    call = validate_success(api_client.create_call_session(
        create_call_session_payload(
            scn["agent"]["id"], scn["member_two"]["id"], scn["scope_two"]["id"],
            started_at="2026-10-01T11:00:00Z",
            scheduled_end_at="2026-10-01T11:30:00Z",
            recording_id=None, disclaimer_script_code=None,
            disclaimer_delivered=False, marketing_rule_set_version=None),
        headers), 201)

    assert call["status"] == "RINGING"
    assert call["recording_id"] is None
    assert call["disclaimer_delivered"] is False
    assert call["disclaimer_script_code"] is None
    assert call["marketing_rule_set_version"] is None
    assert call["recording_status"] == "MISSING"
    assert call["recording_retained_until"] == utc("2033-09-29T11:00:00Z")


def test_agency_and_agent_counts_are_computed_on_read():
    """PRD §2.10: "Any mutation that changes a derived or stored field on a versioned
    resource — a posture change on an agency, a status advance on an agent, a recomputed
    count — refreshes `updated_at` and increments `version`."
    PRD §3.2: "On success the agent advances from `PROVISIONING` to `LICENSED` and
    `licensed_state_count` is recomputed as the number of the agent's licenses whose
    `license_status` reads `VALID`."

    Design: Corner/entities/agency_and_agent_counts_are_computed_on_read
    """
    scn = setup_master_data_for_corner()
    agent, _, _, _ = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"])
    api_client.add_license(agent["id"], {
        "state_code": "NV", "license_number": "NV-LIC-44120",
        "issued_on": "2026-08-06T00:00:00Z", "expires_on": "2027-12-31T00:00:00Z",
    }, LICENSING)

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["licensed_state_count"] == 2
    assert agent_row["certified_carrier_count"] == 1
    assert agent_row["appointed_carrier_count"] == 1
    assert agent_row["live_call_count"] == 0

    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    assert get_success_data(api_client.get_agent(
        agent["id"], DIRECTOR))["live_call_count"] == 0

    connect_call(agent["id"], call["id"])
    assert get_success_data(api_client.get_agent(
        agent["id"], DIRECTOR))["live_call_count"] == 1

    complete_call(agent["id"], call["id"])
    agent_after = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_after["live_call_count"] == 0
    assert agent_after["status"] == "ACTIVE"
    assert get_success_data(api_client.get_agency(
        scn["agency"]["id"], ADMIN))["compliance_posture"] == "OPEN"


def test_agent_state_license_status_is_computed_on_read_and_never_stored():
    """PRD §3.2: "That status is never stored — it is derived on every read by comparing
    `expires_on` against the logical clock — so a license silently lapses the moment the
    clock passes its expiry."
    PRD §2.4: "A license's `license_status` is not stored but derived on every read from
    the logical clock against `expires_on`, and reads either `VALID` or `LAPSED`."

    Design: Corner/entities/agent_state_license_status_is_computed_on_read_and_never_stored
    """
    scn = setup_master_data_for_corner()
    agent, _, _, _ = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"],
        license_overrides={"expires_on": "2026-12-31T00:00:00Z"})

    rows, _meta = validate_paginated(api_client.list_licenses(agent["id"], LICENSING,
                                                     params={"state_code": "TX"}))
    assert len(rows) == 1
    license_id = rows[0]["id"]
    assert rows[0]["license_status"] == "VALID"

    set_clock("2026-12-30T23:59:59Z")
    rows, _meta = validate_paginated(api_client.list_licenses(agent["id"], LICENSING,
                                                     params={"state_code": "TX"}))
    assert rows[0]["license_status"] == "VALID"

    set_clock("2027-01-01T00:00:00Z")
    rows, _meta = validate_paginated(api_client.list_licenses(agent["id"], LICENSING,
                                                     params={"state_code": "TX"}))
    assert rows[0]["license_status"] == "LAPSED", (
        "a clock strictly past expires_on lapses the license"
    )
    assert rows[0]["version"] == 1, "the row is never rewritten"

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["licensed_state_count"] == 0


def test_enrollment_create_extra_field_submission_status_is_ignored_input():
    """PRD §3.6: "The `submission_status` begins at `SUBMITTED` and the
    `disenrollment_status` begins at `NOT_APPLICABLE`; `submitted_on` takes the logical
    clock."
    PRD §2.10: "`version` is an integer that increments by one on every mutation of the
    resource".

    Design: Corner/entities/enrollment_create_extra_field_submission_status_is_ignored_input
    """
    scn = setup_master_data_for_corner()
    setup_scope_and_completed_call(scn, member_index=0)
    headers = make_licensed_agent_headers(scn["agent"]["id"])
    payload = create_enrollment_payload(
        scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
        scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"])
    payload["submission_status"] = "EFFECTUATED"
    payload["version"] = 99

    enrollment = validate_success(api_client.create_enrollment(payload, headers), 201)
    assert enrollment["submission_status"] == "SUBMITTED"
    assert enrollment["disenrollment_status"] == "NOT_APPLICABLE"
    assert enrollment["version"] == 1
    assert enrollment["submitted_on"] == utc(CLOCK_START)
    assert enrollment["disenrolled_day_number"] is None
    assert enrollment["is_rapid_disenrollment"] is False


def test_complaint_create_with_an_out_of_enum_source_returns_invalid_request():
    """PRD §3.9: "The `source` records who raised it and is one of `BENEFICIARY`, `CMS`,
    `CARRIER` or `SECRET_SHOPPER`. The `severity` is `LOW`, `MEDIUM` or `HIGH`."

    Design: Corner/entities/complaint_create_with_an_out_of_enum_source_returns_invalid_request
    """
    scn = setup_master_data_for_corner()
    agent, _, _, _ = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"])

    resp_source = api_client.create_complaint({
        "agent_id": agent["id"], "complaint_type": "MISREPRESENTATION",
        "source": "PORTAL", "severity": "HIGH", "filed_on": "2026-09-28T00:00:00Z",
    }, COMPLIANCE)
    validate_error(resp_source, "ERR_INVALID_REQUEST", expected_status=400)

    resp_severity = api_client.create_complaint({
        "agent_id": agent["id"], "complaint_type": "MISREPRESENTATION",
        "source": "CMS", "severity": "CRITICAL", "filed_on": "2026-09-28T00:00:00Z",
    }, COMPLIANCE)
    validate_error(resp_severity, "ERR_INVALID_REQUEST", expected_status=400)

    rows, _meta = validate_paginated(api_client.list_agent_complaints(agent["id"], COMPLIANCE))
    assert len(rows) == 0
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["open_complaint_count"] == 0


def test_commission_ledger_entry_has_no_update_or_delete_endpoint():
    """PRD §2.8: "Commission is tracked as a signed ledger keyed to cents, never as a
    mutable balance."
    PRD §2.8: "A correction naming a carrier and `period_month` with no `OPEN`
    reconciliation is refused with `ERR_NO_OPEN_RECONCILIATION`."

    Design: Corner/entities/commission_ledger_entry_has_no_update_or_delete_endpoint
    """
    scn = setup_master_data_for_corner()
    setup_scope_and_completed_call(scn, member_index=0)
    setup_submitted_enrollment(scn)
    enrollment_id = scn["enrollment"]["id"]

    # A correction is only admissible inside an OPEN reconciliation period; with
    # no period opened for this carrier and month the request is malformed, since
    # the period identifier can resolve to nothing at all.
    resp = api_client.create_correction({
        "enrollment_id": enrollment_id,
        "carrier_reconciliation_id": NON_EXISTENT_UUID,
        "amount_cents": -500, "period_month": "2026-10",
        "memo": "Attempted in-place correction",
    }, DIRECTOR)
    validate_error(resp, "ERR_RECONCILIATION_NOT_FOUND", expected_status=404)

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment_id}))
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == pytest.approx(3600.00, abs=0.01)
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["commission_balance_cents"] == pytest.approx(3600.00, abs=0.01)


def test_call_session_body_foreign_keys_are_checked_in_declared_input_order():
    """PRD §2.9: "Identifiers supplied in a request body are validated separately, in the
    order the endpoint's input list declares them, and the first unresolvable one produces
    its entity-specific not-found error."

    Design: Corner/entities/call_session_body_foreign_keys_are_checked_in_declared_input_order
    """
    scn = setup_master_data_for_corner()
    setup_scope_and_completed_call(scn, member_index=0)
    headers = make_licensed_agent_headers(scn["agent"]["id"])

    unknown = "00000000-0000-4000-8000-0000000000"
    resp_all = api_client.create_call_session(
        create_call_session_payload(unknown + "01", unknown + "02", unknown + "03"),
        headers)
    body_all = validate_error(resp_all, "ERR_AGENT_NOT_FOUND", expected_status=404)
    assert body_all["error_id"] != "ERR_MEMBER_NOT_FOUND"
    assert body_all["error_id"] != "ERR_SCOPE_OF_APPOINTMENT_NOT_FOUND"

    resp_member = api_client.create_call_session(
        create_call_session_payload(scn["agent"]["id"], unknown + "02",
                                    scn["scope"]["id"]), headers)
    validate_error(resp_member, "ERR_MEMBER_NOT_FOUND", expected_status=404)

    rows, _meta = validate_paginated(api_client.list_agent_call_sessions(
        scn["agent"]["id"], DIRECTOR))
    assert len(rows) == 1
    agent_row = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent_row["live_call_count"] == 0


# ─── local helpers ───────────────────────────────────────────

def setup_master_data_for_corner(**agency_overrides):
    set_clock(CLOCK_START)
    agency = create_agency(**agency_overrides)
    carrier = create_carrier()
    plan = create_plan(carrier["id"])
    agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
    return {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent}
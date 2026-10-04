"""Agency roll, agency creation, activation, termination and OCC writes."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_agency_payload,
    create_campaign_payload,
    make_agency_principal_headers,
    set_clock,
    create_agency,
    create_agency_active,
    read_agency,
    activate_agency,
    inject_agent,
    create_policy,
    setup_active_staff_member,
    setup_agency_at_staffing_cap,
    appoint_agent_via_application,
)

EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_newly_created_agency_is_approved_version_one(api):
    """PRD §3.9: "An AppointingExecutive creates it with a unique agency_code, a
    display name, the region_code that will later drive successor ranking, and a
    market_need_score between 0 and 100. It starts in APPROVED".
    PRD §2.4: "version is a system-managed integer that starts at 1".

    Design: Corner/entities/agency_create_returns_declared_fields_and_starts_approved
    """
    set_clock()
    created = validate_success(
        api.create_agency(
            create_agency_payload(agency_code="CA-101", name="Alpha Agency", market_need_score=55),
            EXEC,
        ),
        201,
    )
    assert created["status"] == "APPROVED"
    assert created["version"] == 1
    assert created["region_code"] == "W"
    assert created["market_need_score"] == 55

    fetched = validate_success(api.get_agency(created["id"], EXEC), 200)
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "APPROVED"


def test_agency_creation_ignores_client_supplied_system_fields(api):
    """PRD §2.4: "id is a server-minted unique identifier formatted as a UUID
    string with no type prefix and no embedded entity name."
    PRD §3.9: "It starts in APPROVED".
    PRD §2.4: "version is a system-managed integer that starts at 1 and increments
    by one on every modification to the record."

    Design: Corner/entities/agency_create_ignores_client_supplied_system_fields
    """
    set_clock()
    payload = create_agency_payload(agency_code="CA-104", name="Smuggle")
    payload["id"] = "attacker-supplied-id"
    payload["status"] = "TERMINATED"
    payload["version"] = 99

    created = get_success_data(api_client.create_agency(payload, EXEC))
    assert created["status"] == "APPROVED"
    assert created["version"] == 1
    assert created["id"] != "attacker-supplied-id"


def test_unknown_agency_id_returns_agency_not_found(api):
    """PRD §2.6: "The failure code names the first unresolved step, not the last: an
    unresolvable agency identifier produces ERR_AGENCY_NOT_FOUND, an unresolvable
    agent identifier produces ERR_AGENT_NOT_FOUND".
    PRD §2.6: "All five carry HTTP 404."

    Design: Corner/entities/err_agency_not_found_on_unknown_id
    """
    set_clock()
    res = api_client.get_agency(NON_EXISTENT_UUID, EXEC)
    validate_error(res, ApiErrorId.ERR_AGENCY_NOT_FOUND, expected_status=404)


def test_re_activating_an_active_agency_returns_invalid_state(api):
    """PRD §3.9: "Activation moves an APPROVED agency to ACTIVE."
    PRD §2.12: "State checks come next: a resource not in the state the
    transition requires yields ERR_INVALID_STATE (409)".

    Design: Corner/state_machines/agency_activate_twice_returns_invalid_state
    """
    set_clock()
    agency = create_agency(agency_code="CA-108")
    activated = activate_agency(agency["id"], agency["version"])
    assert activated["status"] == "ACTIVE"

    res = api.activate_agency(
        agency["id"], {"expected_agency_version": activated["version"]}, EXEC
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_activation_stamps_the_term_start_and_zeroes_the_ops_index(api):
    """PRD §3.9: "It stamps term_start_date with the current logical instant and
    resets ops_run_index to zero, beginning the first twelve-month anniversary
    term."
    PRD §2.11: "Every timestamp the server mints — created_at, updated_at,
    appointment_date, term_start_date, license_verified_at,
    termination_initiated_at — is read from this logical clock."

    Design: Corner/endpoints/run_ops_second_call_recomputes_without_drift
    """
    set_clock("2026-09-01T00:00:00Z")
    agency = create_agency(agency_code="CA-131")
    activated = activate_agency(agency["id"], agency["version"])
    assert activated["term_start_date"].startswith("2026-09-01")
    assert activated["ops_run_index"] == 0


def test_agency_termination_requires_every_agent_to_have_ceased(api):
    """PRD §3.9: "Termination moves an ACTIVE agency to TERMINATED, which is
    terminal. It is permitted only once every agent contracted to the agency has
    a status of PENDING_TERMINATION or TERMINATED; an agency still carrying a
    live agent is refused with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.5: "When an agency agreement expires or the agency itself terminates,
    its ACTIVE staff members become TERMINATED."

    Design: Difficulty/transitive_cascade/staff_termination_cascade_reimbursement
    """
    set_clock()
    # An agency carrying a live, contracted agent cannot terminate. The agent is
    # minted through the application pipeline and transitioned onto the agency's
    # book, so the agency holds a live agent and the transition is exercised
    # through the real path.
    agency = create_agency_active(agency_code="CA-132")
    agent = appoint_agent_via_application()
    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO"]},
            FIELD,
        )
    )
    moved = get_success_data(
        api_client.transition_book(
            agent["id"],
            {"agency_id": agency["id"], "expected_agent_version": licensed["version"]},
            FIELD,
        )
    )
    assert moved["status"] == "TRANSITIONING"
    # The agency is carrying a live agent contracted to it, so the "every agent
    # has ceased" precondition is unmet.
    assert moved["agency_id"] == agency["id"], (
        "the live agent is contracted to the agency"
    )
    assert moved["status"] not in ("PENDING_TERMINATION", "TERMINATED")

    res = api.terminate_agency(agency["id"], EXEC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_terminating_an_agency_cancels_its_campaigns_and_terminates_its_staff(api):
    """PRD §3.9: "Termination cascades in two directions: every StaffMember under
    the agency becomes TERMINATED, which in turn recomputes the agency's
    agency_level_units and then its staffing_reimbursement_cents; and every
    MarketingCampaign under the agency becomes CANCELLED."
    PRD §3.5: "That termination then feeds a two-hop cascade: first
    agency_level_units is recomputed from the agency's remaining ACTIVE
    agreements, and then staffing_reimbursement_cents is recomputed from the
    recomputed unit count."

    Design: Difficulty/transitive_cascade/staff_termination_cascade_reimbursement
    """
    set_clock()
    agency, agent, agreement, staff = setup_active_staff_member()
    campaign = get_success_data(
        api_client.create_campaign(
            agency["id"],
            create_campaign_payload(
                campaign_type="BRAND",
                marketing_allowance_cents=1_000,
                expected_leads=5,
                start_date="2026-09-02T00:00:00Z",
                end_date="2026-09-20T00:00:00Z",
            ),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert staff["status"] == "ACTIVE"

    # Cease the sole agent so the agency is eligible for termination.
    get_success_data(
        api_client.cessation(
            agent["id"],
            {"last_day_iso8601": "2026-08-31T00:00:00Z"},
            make_agency_principal_headers(agency["id"]),
        )
    )
    terminated = get_success_data(api_client.terminate_agency(agency["id"], EXEC))
    assert terminated["status"] == "TERMINATED"

    staff_after = get_success_data(
        api_client.get_staff(staff["id"], make_agency_principal_headers(agency["id"]))
    )
    assert staff_after["status"] == "TERMINATED"

    campaign_after = get_success_data(
        api_client.get_campaign(agency["id"], campaign["id"], make_agency_principal_headers(agency["id"]))
    )
    assert campaign_after["status"] == "CANCELLED"


def test_agency_staffing_cap_refuses_a_twelfth_unit_transition(api):
    """PRD §2.10: "An agency may carry at most eleven agency-level units before it
    can absorb another agent; a transition or a team-member appointment targeting
    an agency already at twelve units is refused with ERR_AGENCY_STAFFING_CAP
    (HTTP 409)."
    PRD §3.2: "the target agency's agency_level_units must be below twelve; an
    agency already at twelve is refused with ERR_AGENCY_STAFFING_CAP (HTTP 409)."

    Design: Corner/errors/err_agency_staffing_cap_triggered
    """
    set_clock()
    agency, _owners = setup_agency_at_staffing_cap(units=12)
    assert read_agency(agency["id"])["agency_level_units"] == 12

    new_agent = appoint_agent_via_application()
    licensed = get_success_data(
        api_client.read_license(
            new_agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO"]},
            FIELD,
        )
    )
    res = api.transition_book(
        new_agent["id"],
        {"agency_id": agency["id"], "expected_agent_version": licensed["version"]},
        FIELD,
    )
    validate_error(res, ApiErrorId.ERR_AGENCY_STAFFING_CAP, expected_status=409)


def test_transition_book_requires_an_active_target_agency(api):
    """PRD §3.2: "The target agency must be ACTIVE."
    PRD §2.12: "State checks come next: a resource not in the state the
    transition requires yields ERR_INVALID_STATE (409)".
    PRD §3.2: "On success the agent's agency_id is bound to the target agency and
    the agency's agency_level_units is recomputed."

    Design: Difficulty/cross_entity_state_dependency/transition_book_requires_target_agency_active
    """
    set_clock()
    approved_agency = create_agency(agency_code="CA-006")
    agent = appoint_agent_via_application()
    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO"]},
            FIELD,
        )
    )
    res = api.transition_book(
        agent["id"],
        {"agency_id": approved_agency["id"], "expected_agent_version": licensed["version"]},
        FIELD,
    )
    assert res.status_code >= 400, "an APPROVED agency cannot absorb a book transition"

    activate_agency(approved_agency["id"], approved_agency["version"])
    moved = get_success_data(
        api_client.transition_book(
            agent["id"],
            {"agency_id": approved_agency["id"], "expected_agent_version": licensed["version"]},
            FIELD,
        )
    )
    assert moved["agency_id"] == approved_agency["id"]


def test_first_run_ops_recomputes_without_drift_on_the_second_run(api):
    """PRD §3.9: "Each run increments ops_run_index by one, so the counter always
    records how many sweeps the agency has seen."
    PRD §2.5: "The rebuild is from source, not incremental".

    Design: Corner/endpoints/run_ops_second_call_recomputes_without_drift
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-117")
    agent = inject_agent(full_name="Cal Ops", status="ACTIVE", is_new_agent=False)
    policy = get_success_data(
        api_client.create_policy(
            {
                "policy_number": "CA-P15",
                "product_line": "AUTO",
                "annual_premium_cents": 400_000,
                "is_new_business": True,
                "holder_agent_id": agent["id"],
                "owner_agency_id": agency["id"],
            },
            FIELD,
        )
    )
    claim = get_success_data(
        api_client.create_claim({"policy_id": policy["id"], "claim_amount_cents": 20_000}, TEST_USERS["claims_adjuster_headers"])
    )
    get_success_data(api_client.settle_claim(claim["id"], TEST_USERS["claims_adjuster_headers"]))

    first = get_success_data(api_client.run_ops(agency["id"], ADMIN))
    second = get_success_data(api_client.run_ops(agency["id"], ADMIN))

    assert second["ops_run_index"] == first["ops_run_index"] + 1, (
        "ops_run_index increments by exactly one per sweep"
    )
    assert second["exposure_inforce_cents"] == first["exposure_inforce_cents"], (
        "a re-run must not drift the exposure total"
    )

def test_agency_creation_without_a_region_code_is_rejected(api):
    """PRD §3.9: "An AppointingExecutive creates it with a unique agency_code, a
    display name, the region_code that will later drive successor ranking, and a
    market_need_score between 0 and 100."
    PRD §2.4: "created_at is an ISO 8601 timestamp in UTC with three fractional
    digits (for example 2025-05-24T10:30:00.123Z) recording when the record was
    first created."

    Design: Corner/entities/agency_create_missing_required_region_code_rejected
    """
    set_clock()
    payload = create_agency_payload(agency_code="CA-103", name="No Region")
    del payload["region_code"]
    res = api_client.create_agency(payload, EXEC)
    assert res.status_code == 400, (
        f"omitting region_code must be rejected, got {res.status_code}"
    )
    body = res.json()
    assert body["response_type"] == "error", "a rejected create returns the error envelope"

    listed = get_success_data(api_client.list_agencies(EXEC, params={"region_code": "W"}))
    assert all(a["agency_code"] != "CA-103" for a in listed), (
        "no agency is written when the required region_code is missing"
    )


def test_transition_onto_an_active_agency_binds_the_agent(api):
    """PRD §3.2: "The target agency must be ACTIVE. And the target agency's
    agency_level_units must be below twelve".
    PRD §3.2: "On success the agent's agency_id is bound to the target agency and
    the agency's agency_level_units is recomputed."

    Design: Difficulty/cross_entity_state_dependency/transition_book_requires_target_agency_active
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-180")
    agent = appoint_agent_via_application()
    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO"]},
            FIELD,
        )
    )
    moved = validate_success(
        api_client.transition_book(
            agent["id"],
            {"agency_id": agency["id"], "expected_agent_version": licensed["version"]},
            FIELD,
        ),
        200,
    )
    assert moved["status"] == "TRANSITIONING"
    assert moved["agency_id"] == agency["id"]


def test_ops_run_recomputes_a_flagged_agency_to_at_risk(api):
    """PRD §3.9: "A run ... recomputes performance_status and agency_valuation_cents
    for every ACTIVE agency."
    PRD §3.6: "If the agency's loss_ratio is greater than 70, the status is
    AT_RISK. Otherwise, if growth_new_pct is below zero, the status is BEHIND.
    Otherwise the status is ON_TRACK. The order matters and is not negotiable".

    Design: Difficulty/dual_variant_calc/agency_performance_ordered_elif_performance_status
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-181")
    agent = inject_agent(full_name="Ops Keeper", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-181-P1", annual_premium_cents=50_000_000, is_new_business=True,
    )
    claim = get_success_data(
        api_client.create_claim(
            {"policy_id": policy["id"], "claim_amount_cents": 5_000_000},
            TEST_USERS["claims_adjuster_headers"],
        )
    )
    get_success_data(api_client.settle_claim(claim["id"], TEST_USERS["claims_adjuster_headers"]))
    get_success_data(
        api_client.book_settlement(agency["id"], {"annualized_commission_cents": 1_000_000}, ADMIN)
    )

    swept = get_success_data(api_client.run_ops(agency["id"], ADMIN))
    assert swept["loss_ratio"] == pytest.approx(83.33, abs=0.01)
    assert swept["performance_status"] == "AT_RISK", (
        "the sweep's ordered chain pins a flagged loss ratio to AT_RISK"
    )

    snapshot = get_success_data(api_client.get_agency_performance(agency["id"], EXEC))
    assert snapshot["performance_status"] == "AT_RISK"

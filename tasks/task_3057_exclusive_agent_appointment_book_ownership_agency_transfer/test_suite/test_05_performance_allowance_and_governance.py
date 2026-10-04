"""Performance measurement, the allowance ledger, reconciliation, RBAC and listing."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_appointment_application_payload,
    create_policy_payload,
    make_agency_principal_headers,
    set_clock,
    create_agency,
    create_agency_active,
    read_agency,
    inject_agent,
    create_policy,
    create_claim,
    create_campaign,
    create_book_transfer_payload,
    setup_agency_with_allowance_pool,
    setup_transitioned_agent,
)

EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]
CLAIMS = TEST_USERS["claims_adjuster_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Performance measurement and valuation ────────────

def _agency_with_flagged_loss_ratio(agency_code="CA-001"):
    """ACTIVE agency whose settled claim drives loss_ratio past the flag."""
    agency = create_agency_active(agency_code=agency_code)
    agent = inject_agent(full_name="Cal Keeper", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number=f"{agency_code}-P1",
        annual_premium_cents=50_000_000, is_new_business=True,
    )
    claim = create_claim(policy["id"], claim_amount_cents=5_000_000)
    get_success_data(api_client.settle_claim(claim["id"], CLAIMS))
    get_success_data(
        api_client.book_settlement(agency["id"], {"annualized_commission_cents": 1_000_000}, ADMIN)
    )
    return read_agency(agency["id"]), policy


def test_performance_status_is_at_risk_when_the_loss_ratio_exceeds_seventy(api):
    """PRD §3.6: "If the agency's loss_ratio is greater than 70, the status is
    AT_RISK. Otherwise, if growth_new_pct is below zero, the status is BEHIND.
    Otherwise the status is ON_TRACK. The order matters and is not negotiable".
    PRD §2.5: "Settling a claim is the deepest example: the owning Policy's
    paid_claims_cents is rebuilt from its claims, the agency's
    agency_paid_claims_cents is rebuilt from its policies, loss_ratio is rebuilt
    from paid claims and open exposure, and finally performance_status is
    re-evaluated."

    Design: Difficulty/dual_variant_calc/agency_performance_ordered_elif_performance_status
    """
    set_clock()
    agency, _policy = _agency_with_flagged_loss_ratio()
    assert agency["agency_paid_claims_cents"] == 5_000_000
    assert agency["loss_ratio"] == pytest.approx(83.33, abs=0.01), (
        "5,000,000 / (50,000,000 * 0.12) * 100 == 83.33"
    )

    snapshot = get_success_data(api_client.get_agency_performance(agency["id"], EXEC))
    assert snapshot["loss_ratio"] == pytest.approx(83.33, abs=0.01)
    assert snapshot["performance_status"] == "AT_RISK", (
        "a flagged loss ratio outranks the growth axis in the ordered chain"
    )


def test_performance_status_is_on_track_without_a_flagged_loss_ratio(api):
    """PRD §3.6: "Otherwise the status is ON_TRACK."
    PRD §3.6: "A run shelf-reopens settled claims as described in §3.8, and it
    recomputes performance_status and agency_valuation_cents for every ACTIVE
    agency.""

    Design: Corner/endpoints/agency_performance_computed_read_matches_calculations
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-002")
    agent = inject_agent(full_name="Cal Two Keeper", status="ACTIVE", is_new_agent=False)
    create_policy(
        agent["id"], agency["id"],
        policy_number="CA-002-P1", annual_premium_cents=400_000, is_new_business=True,
    )
    get_success_data(
        api_client.book_settlement(agency["id"], {"annualized_commission_cents": 900_000}, ADMIN)
    )

    get_success_data(api_client.run_ops(agency["id"], ADMIN))
    read = read_agency(agency["id"])
    assert read["agency_paid_claims_cents"] == 0
    assert read["loss_ratio"] == pytest.approx(0.00, abs=0.01)
    assert read["performance_status"] == "ON_TRACK", (
        "no paid claims and non-negative growth leaves the agency on track"
    )


def test_performance_snapshot_reports_the_valuation_floor(api):
    """PRD §3.6: "agency_valuation_cents prices the book at replacement. It is the
    maximum of (1,000,000.00 cents plus annualized_commission_cents multiplied by
    1.5, minus agency_paid_claims_cents) and a floor of 2,000,000.00 cents — the
    floor governs whenever the formula implies less."

    Design: Corner/endpoints/agency_performance_computed_read_matches_calculations
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-116")
    get_success_data(
        api_client.book_settlement(agency["id"], {"annualized_commission_cents": 150_000}, ADMIN)
    )
    snapshot = validate_success(api_client.get_agency_performance(agency["id"], EXEC), 200)
    assert snapshot["agency_valuation_cents"] == pytest.approx(2_000_000.00, abs=0.01), (
        "1,000,000 + 150,000 * 1.5 == 1,225,000.00, so the floor governs"
    )
    assert snapshot["agency_paid_claims_cents"] == 0


# ─── Allowance ledger and campaign participation ──────

def _agency_at_pool_boundary(exposure_cents=2_000_000):
    """ACTIVE agency whose allowance pool base is exposure * 0.04."""
    return setup_agency_with_allowance_pool(exposure_cents=exposure_cents)


def test_campaign_draw_equal_to_the_remaining_pool_is_accepted(api):
    """PRD §3.4: "Moving a campaign from PLANNED to PARTICIPATED requires an OPEN
    posture and requires that the agency's remaining allowance — its
    marketing_allowance_pool_cents minus its marketing_allowance_spent_cents — be
    at least the campaign's marketing_allowance_cents."
    PRD §2.7: "The agency's exposure forms a base: the open exposure multiplied by
    the rate 0.04, rounded half up, capped at 250,000.00 cents."

    Design: Difficulty/boundary_precision_check/campaign_draw_boundary_pool_exact_vs_one_cent
    """
    set_clock()
    agency, _agent, _policy = _agency_at_pool_boundary(exposure_cents=2_000_000)
    # Pool base = 2,000,000 * 0.04 == 80,000.00; a draw of exactly that succeeds.
    campaign = create_campaign(agency["id"], marketing_allowance_cents=80_000)

    res = api_client.participate_campaign(
        agency["id"],
        campaign["id"],
        {"expected_agency_version": agency["version"]},
        make_agency_principal_headers(agency["id"]),
    )
    participated = validate_success(res, 200)
    assert participated["status"] == "PARTICIPATED", (
        "a draw equal to the remaining pool is absorbed by the empty-remainder edge"
    )


def test_campaign_draw_one_cent_over_the_remaining_pool_is_refused(api):
    """PRD §3.4: "A draw the pool cannot absorb is refused with
    ERR_ALLOWANCE_INSUFFICIENT (HTTP 400)."
    PRD §2.7: "The agency's exposure forms a base: the open exposure multiplied by
    the rate 0.04, rounded half up, capped at 250,000.00 cents."

    Design: Difficulty/boundary_precision_check/campaign_draw_boundary_pool_exact_vs_one_cent
    """
    set_clock()
    agency, _agent, _policy = _agency_at_pool_boundary(exposure_cents=2_000_000)
    campaign = create_campaign(
        agency["id"], campaign_type="COMMUNITY", marketing_allowance_cents=80_001
    )

    res = api_client.participate_campaign(
        agency["id"],
        campaign["id"],
        {"expected_agency_version": agency["version"]},
        make_agency_principal_headers(agency["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ALLOWANCE_INSUFFICIENT, expected_status=400)


def test_campaign_draw_beyond_an_empty_pool_is_refused(api):
    """PRD §3.4: "requires that the agency's remaining allowance — its
    marketing_allowance_pool_cents minus its marketing_allowance_spent_cents — be
    at least the campaign's marketing_allowance_cents. A draw the pool cannot
    absorb is refused with ERR_ALLOWANCE_INSUFFICIENT (HTTP 400)."

    Design: Difficulty/priority_pair_validation_conflict/participate_dual_failure_allowance_before_successor
    """
    set_clock()
    # An agency with no open exposure has no allowance base to draw against.
    agency, _agent, _policy = _agency_at_pool_boundary(exposure_cents=0)
    campaign = create_campaign(agency["id"], marketing_allowance_cents=5_000)

    res = api_client.participate_campaign(
        agency["id"],
        campaign["id"],
        {"expected_agency_version": agency["version"]},
        make_agency_principal_headers(agency["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ALLOWANCE_INSUFFICIENT, expected_status=400)


def test_campaign_draw_beyond_the_pool_leaves_the_campaign_planned(api):
    """PRD §3.4: "A draw the pool cannot absorb is refused with
    ERR_ALLOWANCE_INSUFFICIENT (HTTP 400)."
    PRD §3.4: "The campaign is created in PLANNED."

    Design: Difficulty/priority_pair_validation_conflict/participate_dual_failure_allowance_before_successor
    """
    set_clock()
    agency, _agent, _policy = _agency_at_pool_boundary(exposure_cents=0)
    campaign = create_campaign(
        agency["id"], campaign_type="BRAND", marketing_allowance_cents=5_000
    )

    res = api_client.participate_campaign(
        agency["id"],
        campaign["id"],
        {"expected_agency_version": agency["version"]},
        make_agency_principal_headers(agency["id"]),
    )
    assert res.status_code == 400, (
        f"an unabsorbable draw must be refused, got {res.status_code}"
    )

    unchanged = get_success_data(
        api_client.get_campaign(agency["id"], campaign["id"], make_agency_principal_headers(agency["id"]))
    )
    assert unchanged["status"] == "PLANNED", "no allowance is debited by a refused participation"


def test_campaign_participation_with_a_stale_agency_version_is_refused(api):
    """PRD §3.4: "Because participation mutates the agency's pool, it must carry
    expected_agency_version. A request whose version is stale relative to the
    agency's current version is refused with ERR_STALE_VERSION (HTTP 412) and the
    campaign is left untouched."
    PRD §2.9: "Campaign participation requires expected_agency_version, because a
    prior participation on the same agency advances the allowance pool the client
    last observed; a sequential re-send carrying the older version observes the
    advanced agency version and is refused."

    Design: Corner/cross_cutting_complexity_layers/campaign_participate_with_stale_agency_version_returns_stale_version
    """
    set_clock()
    agency, _agent, _policy = _agency_at_pool_boundary(exposure_cents=2_000_000)
    stale_version = agency["version"]
    campaign = create_campaign(agency["id"], marketing_allowance_cents=10_000)
    # A prior participation advances the agency version the client last observed.
    first = create_campaign(
        agency["id"],
        campaign_type="BRAND",
        marketing_allowance_cents=10_000,
        start_date="2026-10-02T00:00:00Z",
        end_date="2026-10-28T00:00:00Z",
    )
    validate_success(
        api_client.participate_campaign(
            agency["id"],
            first["id"],
            {"expected_agency_version": stale_version},
            make_agency_principal_headers(agency["id"]),
        ),
        200,
    )

    res = api_client.participate_campaign(
        agency["id"],
        campaign["id"],
        {"expected_agency_version": stale_version},
        make_agency_principal_headers(agency["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    untouched = get_success_data(
        api_client.get_campaign(agency["id"], campaign["id"], make_agency_principal_headers(agency["id"]))
    )
    assert untouched["status"] == "PLANNED", "the stale refusal leaves the campaign untouched"


# ─── Derived-field reconciliation ─────────────────────

def test_cancelling_a_policy_reconciles_the_agency_exposure(api):
    """PRD §3.8: "Creating or cancelling a policy recomputes the owning agency's
    book_open_count and exposure_inforce_cents."
    PRD §2.5: "Cancelling a policy rebuilds the agency's book_open_count and
    exposure_inforce_cents."

    Design: Corner/cross_cutting_complexity_layers/policy_cancel_reconciles_agency_exposure
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-124")
    agent = inject_agent(full_name="Cal Recon", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P18", annual_premium_cents=500_000, is_new_business=False,
    )
    before = read_agency(agency["id"])
    assert before["exposure_inforce_cents"] == 500_000
    assert before["book_open_count"] == 1

    validate_success(
        api.cancel_policy(policy["id"], make_agency_principal_headers(agency["id"])), 200
    )
    after = read_agency(agency["id"])
    assert after["exposure_inforce_cents"] == 0, "exposure reconciles on the same request"
    assert after["book_open_count"] == 0


def test_cancelling_an_already_cancelled_policy_is_refused(api):
    """PRD §3.8: "CANCELLED and TRANSFERRED are both terminal for a policy, so any
    transition out of either is refused with ERR_ALREADY_TERMINAL (HTTP 409)".
    PRD §3.8: "Cancellation is an AgencyPrincipal action that moves an OPEN policy
    to CANCELLED."

    Design: Corner/entities/policy_cancel_from_cancelled_returns_invalid_state
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-105")
    agent = inject_agent(full_name="Cal Canc", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P10", annual_premium_cents=200_000, is_new_business=False,
    )
    principal = make_agency_principal_headers(agency["id"])
    validate_success(api.cancel_policy(policy["id"], principal), 200)

    res = api.cancel_policy(policy["id"], principal)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)


def test_duplicate_policy_number_is_refused(api):
    """PRD §3.8: "policy_number must be unique across all policies, and a
    duplicate is refused with ERR_DUPLICATE_POLICY (HTTP 409) — the same code
    covers a duplicate agency_code at agency creation."

    Design: Corner/validations/duplicate_policy_number_returns_duplicate_policy
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-113")
    agent = inject_agent(full_name="Cal Dup", status="ACTIVE", is_new_agent=False)
    create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P13", annual_premium_cents=150_000, is_new_business=False,
    )
    res = api.create_policy(
        create_policy_payload(
            agent["id"], agency["id"],
            policy_number="CA-P13", product_line="HOME",
            annual_premium_cents=100_000, is_new_business=True,
        ),
        FIELD,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_POLICY, expected_status=409)


def test_policy_creation_is_immediately_visible_on_the_agency(api):
    """PRD §2.5: "book_open_count counts the agency's policies that are still
    OPEN; exposure_inforce_cents sums annual_premium_cents across those same open
    policies".
    PRD §2.4: "Any mutation of a derived property — recomputing an agency's
    exposure, re-deriving a policy's paid claims, refreshing a book transfer's
    retention — is a mutation of the owning record".

    Design: Corner/consistency_model/policy_creation_visible_immediately_in_agency_read
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-126")
    agent = inject_agent(full_name="Cal Imm", status="ACTIVE", is_new_agent=False)
    created = validate_success(
        api.create_policy(
            create_policy_payload(
                agent["id"], agency["id"],
                policy_number="CA-P20", product_line="LIFE",
                annual_premium_cents=90_000, is_new_business=True,
            ),
            FIELD,
        ),
        201,
    )
    assert created["status"] == "OPEN"

    read = validate_success(api.get_agency(agency["id"], EXEC), 200)
    assert read["book_open_count"] == 1, "the derived count is visible on the next read"
    assert read["exposure_inforce_cents"] == 90_000


# ─── Listing and pagination ───────────────────────────

def test_agent_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Paginated and unpaginated list responses carry limit, offset,
    total_count, and has_more in the meta object of the envelope."
    PRD §2.3: "A second query parameter, offset, gives the number of records to
    skip and defaults to 0."

    Design: Corner/entities/agents_list_paginates_total_count_and_has_more
    """
    set_clock()
    for name in ("A One", "A Two", "A Three"):
        inject_agent(full_name=name, status="ACTIVE", is_new_agent=False)

    data, meta = validate_paginated(api.list_agents(FIELD, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, tail_meta = validate_paginated(
        api.list_agents(FIELD, params={"limit": 2, "offset": 2})
    )
    assert len(tail) == 1
    assert tail_meta["has_more"] is False


# ─── Role-based access control ────────────────────────

def test_field_manager_cannot_activate_an_agency(api):
    """PRD §2.1: "An authenticated request whose role is not permitted for the
    requested operation — per the role matrix below and the authorized-role
    column of §4 — is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "AppointingExecutive approves and rejects appointment applications
    and governs the agency roll, activating and terminating agencies."

    Design: Corner/rbac/field_manager_cannot_activate_agency
    """
    set_clock()
    agency = create_agency(agency_code="CA-120")
    res = api.activate_agency(
        agency["id"], {"expected_agency_version": agency["version"]}, FIELD
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    unchanged = read_agency(agency["id"])
    assert unchanged["status"] == "APPROVED"


def test_claims_adjuster_cannot_submit_an_appointment_application(api):
    """PRD §2.1: "An authenticated request whose role is not permitted for the
    requested operation — per the role matrix below and the authorized-role
    column of §4 — is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "FieldManager is the field recruiter: it submits and scores
    applications, mints agents, reads licenses, transitions books, writes
    agreements, creates policies, and drives policy reassignment."

    Design: Corner/rbac/claims_adjuster_cannot_submit_appointment_application
    """
    set_clock()
    res = api.create_application(
        create_appointment_application_payload(), TEST_USERS["claims_adjuster_headers"]
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_agency_principal_cannot_approve_an_application(api):
    """PRD §2.1: "An authenticated request whose role is not permitted for the
    requested operation — per the role matrix below and the authorized-role
    column of §4 — is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "AppointingExecutive approves and rejects appointment applications
    and governs the agency roll, activating and terminating agencies."

    Design: Corner/rbac/agency_principal_cannot_approve_application
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-121")
    application = get_success_data(
        api.create_application(
            create_appointment_application_payload(market_need_score=70), FIELD
        )
    )
    get_success_data(api.assess_application(application["id"], FIELD))

    res = api.approve_application(application["id"], make_agency_principal_headers(agency["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_regulatory_board_cannot_settle_a_claim(api):
    """PRD §2.1: "An authenticated request whose role is not permitted for the
    requested operation — per the role matrix below and the authorized-role
    column of §4 — is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "ClaimsAdjuster files, settles, resolves, and denies claims."

    Design: Corner/rbac/regulatory_board_cannot_settle_claim
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-122")
    agent = inject_agent(full_name="Cal RBAC", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P16", annual_premium_cents=300_000, is_new_business=False,
    )
    claim = create_claim(policy["id"], claim_amount_cents=15_000)

    res = api.settle_claim(claim["id"], TEST_USERS["regulatory_board_headers"])
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    unchanged = validate_success(api.get_claim(claim["id"], CLAIMS), 200)
    assert unchanged["status"] == "OPEN"


# ─── Retention reporting ──────────────────────────────

def _transfer_with_a_held_policy(agency_code="OAK-04"):
    """Post a book transfer over a transitioning agent holding one OPEN policy."""
    agency, agent = setup_transitioned_agent(create_agency_active(agency_code=agency_code))
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number=f"{agency_code}-P1", annual_premium_cents=250_000, is_new_business=False,
    )
    transfer = get_success_data(
        api_client.create_book_transfer(
            agent["id"],
            create_book_transfer_payload(agency["id"], agency["id"]),
            make_agency_principal_headers(agency["id"]),
        )
    )
    return agency, agent, policy, transfer


def test_retention_met_agrees_with_the_at_least_eighty_five_rule(api):
    """PRD §3.7: "retention_pct is the retained count divided by the transferred
    count, multiplied by 100, rounded half up. retention_met is true when
    retention_pct is at least 85".
    PRD §3.7: "Retention is measured by successor holding, not by agency holding".

    Design: Difficulty/boundary_precision_check/retention_threshold_at_eighty_five_percent
    """
    set_clock()
    agency, agent, _policy, transfer = _transfer_with_a_held_policy()
    get_success_data(api_client.run_ops(agency["id"], ADMIN))

    read = get_success_data(api_client.get_book_transfer(transfer["id"], FIELD))
    assert isinstance(read["retention_pct"], (int, float))
    assert read["retention_met"] is (read["retention_pct"] >= 85), (
        "retention_met is exactly the at-least-85 predicate on the reported figure"
    )


def test_retention_counts_reconcile_with_the_reported_percentage(api):
    """PRD §3.7: "Three computed counts describe the outcome:
    transferred_policy_count counts the policies this transfer reassigned,
    retained_policy_count counts those still OPEN and held by the successor, and
    retention_pct is the retained count divided by the transferred count,
    multiplied by 100, rounded half up."
    PRD §3.7: "retention_met is true when retention_pct is at least 85".

    Design: Difficulty/boundary_precision_check/retention_threshold_at_eighty_five_percent
    """
    set_clock()
    agency, agent, _policy, transfer = _transfer_with_a_held_policy(agency_code="OAK-14")
    get_success_data(api_client.run_ops(agency["id"], ADMIN))

    read = get_success_data(api_client.get_book_transfer(transfer["id"], FIELD))
    transferred = read["transferred_policy_count"]
    retained = read["retained_policy_count"]
    assert transferred >= retained >= 0, (
        "the retained count can never exceed the transferred count"
    )
    if transferred > 0:
        expected_pct = round(retained / transferred * 100 + 1e-9, 2)
        assert read["retention_pct"] == pytest.approx(expected_pct, abs=0.01), (
            "retention_pct is retained / transferred * 100, rounded half up"
        )
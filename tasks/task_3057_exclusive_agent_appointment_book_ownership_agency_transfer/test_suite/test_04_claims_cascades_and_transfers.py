"""Claims compensation, loss ratio cascades, cessation and book transfer."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_book_transfer_payload,
    make_agency_principal_headers,
    set_clock,
    create_agency_active,
    read_agency,
    inject_agent,
    create_policy,
    create_claim,
    setup_transitioned_agent,
    setup_agency_with_claim,
    setup_active_staff_member,
)

EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]
CLAIMS = TEST_USERS["claims_adjuster_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_settle_moves_the_claim_to_paid_and_sets_the_paid_amount(api):
    """PRD §3.8: "Settling moves the claim from OPEN to PAID and sets
    policy_paid_cents to the lesser of the reserve claim_amount_cents and eighty
    percent of the policy's annual_premium_cents, rounded half up to the cent".
    PRD §3.8: "Resolving moves a PAID claim back to OPEN and posts a resolution
    chargeback."

    Design: Difficulty/non_linear_state_machine/claim_settle_resolve_reopen_cycle
    """
    set_clock()
    _agency, _agent, _policy, claim = setup_agency_with_claim(
        exposure_cents=300_000, claim_amount_cents=40_000
    )
    settled = validate_success(api.settle_claim(claim["id"], CLAIMS), 200)
    assert settled["status"] == "PAID"
    assert settled["policy_paid_cents"] == 40_000, "min(40000, 300000 * 0.80) == 40000"

    reopened = validate_success(api.resolve_claim(claim["id"], CLAIMS), 200)
    assert reopened["status"] == "OPEN", "the cycle closes back at OPEN"


def test_resolving_an_unsettled_claim_is_refused(api):
    """PRD §3.8: "Resolving moves a PAID claim back to OPEN and posts a resolution
    chargeback."
    PRD §2.12: "a resource not in the state the transition requires yields
    ERR_INVALID_STATE (409)".

    Design: Difficulty/non_linear_state_machine/claim_settle_resolve_reopen_cycle
    """
    set_clock()
    _agency, _agent, _policy, claim = setup_agency_with_claim(
        exposure_cents=300_000, claim_amount_cents=40_000
    )
    validate_success(api.settle_claim(claim["id"], CLAIMS), 200)
    validate_success(api.resolve_claim(claim["id"], CLAIMS), 200)

    # The claim is OPEN again, so a second resolve cannot apply.
    res = api.resolve_claim(claim["id"], CLAIMS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_settle_cascade_reaches_agency_loss_ratio_and_performance_status(api):
    """PRD §3.8: "the owning policy's paid_claims_cents is rebuilt from its
    claims, the agency's agency_paid_claims_cents is rebuilt from its policies,
    the agency's loss_ratio is rebuilt from paid claims and open exposure, and
    the agency's performance_status is re-evaluated."
    PRD §3.6: "If the agency's loss_ratio is greater than 70, the status is
    AT_RISK."

    Design: Difficulty/transitive_cascade/claim_settle_cascade_loss_ratio_performance
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-003")
    agent = inject_agent(full_name="Cal Three Keeper", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P4", annual_premium_cents=500_000, is_new_business=False,
    )
    claim = create_claim(policy["id"], claim_amount_cents=45_000)
    get_success_data(
        api_client.book_settlement(agency["id"], {"annualized_commission_cents": 10_000_000}, ADMIN)
    )

    validate_success(api.settle_claim(claim["id"], CLAIMS), 200)

    policy_after = validate_success(api.get_policy(policy["id"], CLAIMS), 200)
    assert policy_after["paid_claims_cents"] == 45_000, "hop 1: the policy rebuilds from its claims"

    read = read_agency(agency["id"])
    assert read["agency_paid_claims_cents"] == 45_000, "hop 2: the agency rebuilds from its policies"
    assert read["loss_ratio"] == pytest.approx(75.00, abs=0.01), (
        "hop 3: 45000 / (500000 * 0.12) * 100 == 75.00"
    )
    assert read["performance_status"] == "AT_RISK", (
        "hop 4: loss_ratio > 70 outranks the growth axis"
    )


def test_settle_cascade_rebuilds_the_policy_and_agency_paid_totals(api):
    """PRD §3.6: "Each Policy carries paid_claims_cents, the sum of
    policy_paid_cents across the claims linked to it. Each Agency carries
    agency_paid_claims_cents, the sum of policy_paid_cents across every claim on
    any policy whose owner_agency_id is that agency".
    PRD §2.5: "Settling a claim is the deepest example: the owning Policy's
    paid_claims_cents is rebuilt from its claims".

    Design: Difficulty/transitive_cascade/claim_settle_cascade_loss_ratio_performance
    """
    set_clock()
    agency, _agent, policy, claim = setup_agency_with_claim(
        exposure_cents=500_000, claim_amount_cents=45_000
    )
    assert read_agency(agency["id"])["agency_paid_claims_cents"] == 0

    validate_success(api.settle_claim(claim["id"], CLAIMS), 200)

    policy_after = validate_success(api.get_policy(policy["id"], CLAIMS), 200)
    agency_after = read_agency(agency["id"])
    assert policy_after["paid_claims_cents"] == 45_000
    assert agency_after["agency_paid_claims_cents"] == policy_after["paid_claims_cents"], (
        "the agency total mirrors the sum of its policies' paid claims"
    )


def test_denying_a_claim_zeroes_the_paid_amount_and_recomputes_the_cascade(api):
    """PRD §3.8: "Denying moves the claim from OPEN to DENIED and sets
    policy_paid_cents to zero, then re-evaluates the same chain — loss ratio,
    then termination value, then agency valuation."

    Design: Corner/cross_cutting_complexity_layers/claim_deny_restores_zero_paid_and_recomputes_loss_ratio
    """
    set_clock()
    agency, _agent, _policy, claim = setup_agency_with_claim(
        exposure_cents=600_000, claim_amount_cents=20_000
    )
    denied = validate_success(api.deny_claim(claim["id"], CLAIMS), 200)
    assert denied["status"] == "DENIED"
    assert denied["policy_paid_cents"] == 0

    read = read_agency(agency["id"])
    assert read["agency_paid_claims_cents"] == 0
    assert read["loss_ratio"] == pytest.approx(0.00, abs=0.01), (
        "a denied claim contributes nothing to the paid total"
    )


def test_loss_ratio_uses_the_paid_basis_not_open_reserves(api):
    """PRD §3.6: "The pinned basis is paid claims: counting open reserves instead
    of paid amounts diverges the moment a claim is denied, because a denied claim
    contributes nothing to the paid total."
    PRD §3.8: "Denying moves the claim from OPEN to DENIED and sets
    policy_paid_cents to zero".

    Design: Corner/calculations/loss_ratio_paid_basis_variant_selection
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-110")
    agent = inject_agent(full_name="Cal Liab", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P12", annual_premium_cents=500_000, is_new_business=False,
    )
    claim = create_claim(policy["id"], claim_amount_cents=40_000)

    validate_success(api.deny_claim(claim["id"], CLAIMS), 200)
    read = read_agency(agency["id"])
    assert read["loss_ratio"] == pytest.approx(0.00, abs=0.01), (
        "the reserve-basis reading would count the 40,000.00 reserve"
    )


def test_resolution_chargeback_re_opens_the_claim_and_floors_the_ledger(api):
    """PRD §3.8: "Resolving moves a PAID claim back to OPEN and posts a resolution
    chargeback. The chargeback equals the claim's policy_paid_cents; the policy's
    sub_producer_released_commission_cents ledger is reduced by that amount,
    floored at zero."
    PRD §2.8: "the ledger becomes the greater of (its previous value minus the
    chargeback) and zero. The ledger is never permitted to fall below zero, and a
    partial recovery reduces it by less than the full paid amount."

    Design: Difficulty/compensating_invariant/claim_resolution_chargeback_commission_invariant
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-009")
    agent = inject_agent(full_name="Cal Nine Keeper", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P9", annual_premium_cents=800_000, is_new_business=False,
    )
    claim = create_claim(policy["id"], claim_amount_cents=40_000)
    settled = validate_success(api.settle_claim(claim["id"], CLAIMS), 200)
    assert settled["policy_paid_cents"] == 40_000

    reopened = validate_success(api.resolve_claim(claim["id"], CLAIMS), 200)
    assert reopened["status"] == "OPEN", "the compensating action ran"

    policy_after = validate_success(api.get_policy(policy["id"], CLAIMS), 200)
    assert policy_after["sub_producer_released_commission_cents"] >= 0, (
        "the released ledger never falls below zero"
    )


def test_resolution_chargeback_keeps_the_released_ledger_non_negative(api):
    """PRD §2.8: "The ledger is never permitted to fall below zero, and a partial
    recovery reduces it by less than the full paid amount."
    PRD §3.8: "the policy's sub_producer_released_commission_cents ledger is
    reduced by that amount, floored at zero."

    Design: Difficulty/compensating_invariant/claim_resolution_chargeback_commission_invariant
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-190")
    agent = inject_agent(full_name="Floor Keeper", status="ACTIVE", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P90", annual_premium_cents=800_000, is_new_business=False,
    )
    claim = create_claim(policy["id"], claim_amount_cents=40_000)
    validate_success(api.settle_claim(claim["id"], CLAIMS), 200)
    validate_success(api.resolve_claim(claim["id"], CLAIMS), 200)

    policy_after = validate_success(api.get_policy(policy["id"], CLAIMS), 200)
    assert policy_after["sub_producer_released_commission_cents"] >= 0


def test_book_transfer_settlement_pays_ninety_percent_of_the_transfer_commission(api):
    """PRD §3.7: "The transferred base is the sum over the transferred policies of
    each policy's annual_premium_cents multiplied by 0.10; the transfer
    commission is that base multiplied by 0.10; and the settlement payable is the
    transfer commission multiplied by 0.90, rounded half up."

    Design: Difficulty/dual_variant_calc/book_transfer_cause_forfeiture_settlement
    """
    set_clock()
    agency, agent = setup_transitioned_agent(create_agency_active(agency_code="OAK-01"))
    create_policy(
        agent["id"], agency["id"],
        policy_number="V-P1", annual_premium_cents=600_000, is_new_business=True,
    )
    transfer = get_success_data(
        api_client.create_book_transfer(
            agent["id"],
            create_book_transfer_payload(agency["id"], agency["id"]),
            make_agency_principal_headers(agency["id"]),
        )
    )
    # 600,000 * 0.10 = 60,000.00 base; * 0.10 = 6,000.00 commission; * 0.90 = 5,400.00.
    assert transfer["settlement_payable_cents"] == pytest.approx(5_400.00, abs=0.01)


def test_book_transfer_settlement_over_an_empty_book_is_zero(api):
    """PRD §3.7: "The transferred base is the sum over the transferred policies of
    each policy's annual_premium_cents multiplied by 0.10; the transfer
    commission is that base multiplied by 0.10; and the settlement payable is the
    transfer commission multiplied by 0.90, rounded half up."
    PRD §3.7: "It is posted with agent_id, from_agency_id, and to_agency_id,
    begins in PENDING".

    Design: Difficulty/dual_variant_calc/book_transfer_cause_forfeiture_settlement
    """
    set_clock()
    agency, agent = setup_transitioned_agent(create_agency_active(agency_code="OAK-11"))

    transfer = get_success_data(
        api_client.create_book_transfer(
            agent["id"],
            create_book_transfer_payload(agency["id"], agency["id"]),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert transfer["status"] == "PENDING"
    assert transfer["settlement_payable_cents"] == pytest.approx(0.00, abs=0.01), (
        "an empty transferred base sums to zero"
    )


def test_book_transfer_conserves_the_transferred_exposure(api):
    """PRD §2.5: "exposure_inforce_cents sums annual_premium_cents across those
    same open policies".
    PRD §3.7: "It is posted with agent_id, from_agency_id, and to_agency_id,
    begins in PENDING, and is maintained through SETTLED and, on reversal,
    REVERSED."

    Design: Difficulty/compensating_invariant/book_transfer_settlement_invariant
    """
    set_clock()
    from_agency = create_agency_active(agency_code="R-01")
    to_agency = create_agency_active(agency_code="R-02")
    holder = inject_agent(full_name="From Keeper", status="ACTIVE", is_new_agent=False)
    create_policy(
        holder["id"], from_agency["id"],
        policy_number="R-P1", annual_premium_cents=150_000, is_new_business=False,
    )
    before_from = read_agency(from_agency["id"])["exposure_inforce_cents"]
    before_to = read_agency(to_agency["id"])["exposure_inforce_cents"]
    assert before_from == 150_000 and before_to == 0

    get_success_data(
        api_client.create_book_transfer(
            holder["id"],
            create_book_transfer_payload(from_agency["id"], to_agency["id"]),
            FIELD,
        )
    )
    after_from = read_agency(from_agency["id"])["exposure_inforce_cents"]
    after_to = read_agency(to_agency["id"])["exposure_inforce_cents"]
    assert after_from + after_to == 150_000, (
        "the reassignment conserves the named exposure quantity"
    )


def test_book_transfer_record_starts_pending_with_a_null_successor(api):
    """PRD §3.7: "It is posted with agent_id, from_agency_id, and to_agency_id,
    begins in PENDING".
    PRD §3.7: "Its successor_agent_id is filled by the successor selection above
    and stays null while the transfer is pending."

    Design: Difficulty/compensating_invariant/book_transfer_settlement_invariant
    """
    set_clock()
    agency, agent = setup_transitioned_agent(create_agency_active(agency_code="OAK-21"))
    transfer = get_success_data(
        api_client.create_book_transfer(
            agent["id"],
            create_book_transfer_payload(agency["id"], agency["id"]),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert transfer["status"] == "PENDING"
    assert transfer.get("successor_agent_id") in (None, ""), (
        "successor_agent_id stays null while the transfer is pending"
    )


def test_staff_termination_cascade_recomputes_the_unit_count(api):
    """PRD §3.5: "When an agency agreement expires or the agency itself
    terminates, its ACTIVE staff members become TERMINATED. That termination then
    feeds a two-hop cascade: first agency_level_units is recomputed from the
    agency's remaining ACTIVE agreements, and then staffing_reimbursement_cents
    is recomputed from the recomputed unit count."

    Design: Difficulty/transitive_cascade/staff_termination_cascade_reimbursement
    """
    set_clock()
    agency, agent, _agreement, staff = setup_active_staff_member()
    principal = make_agency_principal_headers(agency["id"])
    assert staff["status"] == "ACTIVE"

    ceased = get_success_data(
        api_client.cessation(
            agent["id"], {"last_day_iso8601": "2026-08-31T00:00:00Z"}, principal
        )
    )
    assert ceased["status"] == "PENDING_TERMINATION", (
        "cessation moves an ACTIVE agent to PENDING_TERMINATION"
    )

    # The ops sweep expires the suspended agreement, which cascades the ACTIVE
    # staff member to TERMINATED (link 1).
    get_success_data(api_client.run_ops(agency["id"], ADMIN))
    staff_after = get_success_data(api_client.get_staff(staff["id"], principal))
    assert staff_after["status"] == "TERMINATED", "link 1: the staffer terminates"

    # Link 2: the staff termination rebuilds the reimbursement from the
    # recomputed unit count. With the only agreement now terminated that total
    # is zero.
    read = read_agency(agency["id"])
    assert read["staffing_reimbursement_cents"] == pytest.approx(0.00, abs=0.01), (
        "link 2: no ACTIVE staff remain, so the reimbursement rebuilds to zero"
    )

def test_finalizing_reassignment_without_a_successor_is_refused(api):
    """PRD §3.7: "Its candidate set is every Agent whose status is ACTIVE, whose
    agency has a region_code equal to the ceasing agency's region_code, and whose
    id is not the ceasing agent's. If that set is empty the selection raises
    ERR_NO_SUCCESSOR_AGENT (HTTP 409)."
    PRD §3.7: "Once the last open policy has moved, the agent moves from
    TRANSITIONING to TERMINATED, which is terminal."

    Design: Corner/errors/err_no_successor_agent_triggered
    """
    set_clock()
    # The only agent on file is the one being finalized, so the same-region
    # ACTIVE candidate set is empty.
    agency, agent = setup_transitioned_agent(create_agency_active(agency_code="LONE-01"))
    assert agent["status"] == "TRANSITIONING"

    res = api.complete_reassignment(agent["id"], FIELD)
    validate_error(res, ApiErrorId.ERR_NO_SUCCESSOR_AGENT, expected_status=409)

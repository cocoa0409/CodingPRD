"""Cascades: agreement termination firing consent revocation, claim voiding
and escrow reservation; disbursement runs (gating, success, and atomic
failure); priority pairs on routing.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_network,
    setup_routed_referral, setup_submitted_claim, setup_approved_claim,
    route_referral, accept_referral, start_service, confirm_outcome,
    submit_claim, review_claim, approve_claim,
    add_referral, get_referral, get_offering, get_client, get_claim,
    create_and_approve_agreement, get_consent, get_org,
    make_case_worker_headers, make_org_admin_headers, make_funder_admin_headers,
)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade /
#   agreement_termination_depth3_consent_referral_claim_escrow
# ---------------------------------------------------------------------------

def _setup_agreement_cascade_scenario():
    """One ROUTED referral (rf1) plus a completed referral (rf2) with a
    SUBMITTED claim, both under the same sender/receiver agreement.
    Returns (ctx, rf1, rf2, claim)."""
    ctx, rf1 = setup_routed_referral(
        with_funder=True,
        network_overrides={"network_escrow_cents": 100_000})
    rf2, client2, consent2 = add_referral(ctx)
    route_referral(ctx, rf2["id"])
    accept_referral(ctx, rf2["id"])
    start_service(ctx, rf2["id"])
    confirm_outcome(ctx, rf2["id"], "DELIVERED", 50)
    claim = submit_claim(ctx, rf2["id"], 50)  # provisional 50 * 100 = 5000
    return ctx, rf1, rf2, claim


def test_agreement_termination_cascades_consent_referral_and_capacity():
    """PRD §3.4: "Terminating an agreement — by a coordinator's explicit act or
    by the cascade from an organization's termination — moves it `ACTIVE` →
    `TERMINATED` and fires the consent cascade: every consent whose
    (`sender_org_id`, `receiver_org_id`) pair matches either party direction of
    the agreement moves `ACTIVE` → `REVOKED` with its `revoked_at` set to the
    clock, and each such revocation then fires the full revocation consequences
    described below."
    PRD §3.4: "First, every referral riding on this consent that is in `DRAFT`,
    `ROUTED`, `DECLINED`, or `ESCALATED` is cancelled with the reason
    `CONSENT_REVOKED`. Second, for each such cancelled referral that was in
    `ROUTED`, the receiving offering's `capacity_consumed` is decremented by 1,
    releasing the reservation."

    Design: Difficulty/transitive_cascade/agreement_termination_depth3_consent_referral_claim_escrow
    """
    ctx, rf1, rf2, claim = _setup_agreement_cascade_scenario()
    get_success_data(api_client.terminate_agreement(ctx["agreement_id"], COORDINATOR))

    assert get_consent(ctx["consent_id"])["status"] == "REVOKED"
    assert get_referral(rf1["id"])["status"] == "CANCELLED"
    assert get_offering(ctx["offering_id"])["capacity_consumed"] == 0
    assert get_client(ctx["client_id"])["open_referral_count"] == 0


def test_agreement_termination_cascades_claim_void_with_escrow_reserve():
    """PRD §3.4: "every payment claim in `SUBMITTED` or `UNDER_REVIEW` whose
    referral rode on this consent is voided — regardless of whether that
    referral itself was cancelled — with the clawback reserve funded from the
    network escrow: the reserve equals the claim's `approved_amount_cents` when
    set, otherwise its `provisional_amount_cents`; `network_escrow_cents` is
    debited by the reserve and `network_escrow_reserved_cents` credited by the
    same amount."

    Design: Difficulty/transitive_cascade/agreement_termination_depth3_consent_referral_claim_escrow
    """
    ctx, rf1, rf2, claim = _setup_agreement_cascade_scenario()
    get_success_data(api_client.terminate_agreement(ctx["agreement_id"], COORDINATOR))

    claim = get_claim(claim["id"])
    assert claim["status"] == "VOIDED"
    assert claim["clawback_reserve_cents"] == 5_000

    network = get_success_data(api_client.get_network(ctx["network_id"], COORDINATOR))
    assert network["network_escrow_cents"] == 95_000
    assert network["network_escrow_reserved_cents"] == 5_000


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / escrow_hold_invariant_void_then_settle
# ---------------------------------------------------------------------------

def test_escrow_hold_invariant_consent_revoke_voids_submitted_claim():
    """PRD §3.4: "every payment claim in `SUBMITTED` or `UNDER_REVIEW` whose
    referral rode on this consent is voided — regardless of whether that
    referral itself was cancelled — with the clawback reserve funded from the
    network escrow: the reserve equals the claim's `approved_amount_cents` when
    set, otherwise its `provisional_amount_cents`; `network_escrow_cents` is
    debited by the reserve and `network_escrow_reserved_cents` credited by the
    same amount."

    Design: Difficulty/compensating_invariant/escrow_hold_invariant_void_then_settle
    """
    ctx, referral, claim = setup_submitted_claim(
        delivered_units=50, network_overrides={"network_escrow_cents": 100_000})
    before = get_success_data(api_client.get_network(ctx["network_id"], COORDINATOR))

    get_success_data(api_client.revoke_consent(
        ctx["consent_id"], make_case_worker_headers(ctx["sender_id"])))

    claim = get_claim(claim["id"])
    assert claim["status"] == "VOIDED"
    assert claim["clawback_reserve_cents"] == 5_000  # provisional 50 * 100

    after = get_success_data(api_client.get_network(ctx["network_id"], COORDINATOR))
    assert after["network_escrow_cents"] == 95_000
    assert after["network_escrow_reserved_cents"] == 5_000


def test_escrow_hold_invariant_conserved_sum_unchanged_by_void():
    """PRD §2.9: "The escrow-hold invariant requires that
    `network_escrow_reserved_cents` always equals the sum of
    `clawback_reserve_cents` over all claims currently in `VOIDED` status."

    Design: Difficulty/compensating_invariant/escrow_hold_invariant_void_then_settle
    """
    ctx, referral, claim = setup_submitted_claim(
        delivered_units=50, network_overrides={"network_escrow_cents": 100_000})
    get_success_data(api_client.revoke_consent(
        ctx["consent_id"], make_case_worker_headers(ctx["sender_id"])))

    claim = get_claim(claim["id"])
    network = get_success_data(api_client.get_network(ctx["network_id"], COORDINATOR))
    # Money moves from escrow into the reserve; the sum is conserved and the
    # escrow-hold invariant holds.
    assert (network["network_escrow_cents"]
            + network["network_escrow_reserved_cents"]) == 100_000
    assert network["network_escrow_reserved_cents"] == claim["clawback_reserve_cents"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / disbursement_run_requires_claims_approved
# ---------------------------------------------------------------------------

def test_disbursement_run_rejects_unapproved_claim_then_succeeds():
    """PRD §3.8: "Running the batch is all-or-nothing: every listed claim must
    be `APPROVED` and belong to the named provider, else
    `ERR_CLAIM_NOT_PAYABLE`, and the provider organization must be `ACTIVE`,
    else `ERR_ORG_NOT_ACTIVE`. A successful run computes `total_amount_cents`
    as the sum of the included claims' `approved_amount_cents` at run time,
    moves each claim `APPROVED` → `PAID`, and settles each claim against the
    provider's `payable_balance_cents`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_run_requires_claims_approved
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    review_claim(ctx, claim["id"], "rev1")  # UNDER_REVIEW, not APPROVED
    disbursement = get_success_data(api_client.create_disbursement(
        {"provider_org_id": ctx["receiver_id"], "funder_org_id": ctx["funder_id"],
         "claim_ids": [claim["id"]]},
        ctx["funder_admin"]))

    validate_error(api_client.run_disbursement(
        disbursement["id"], {}, ctx["funder_admin"]),
        ApiErrorId.ERR_CLAIM_NOT_PAYABLE, expected_status=409)
    disbursement = get_success_data(
        api_client.get_disbursement(disbursement["id"], ctx["funder_admin"]))
    assert disbursement["status"] == "SCHEDULED"

    # After approval the same run succeeds and pays out.
    approve_claim(ctx, claim["id"], "rev2")
    ran = validate_success(api_client.run_disbursement(
        disbursement["id"], {}, ctx["funder_admin"]))
    assert ran["status"] == "PAID"
    assert ran["total_amount_cents"] == 1_000
    assert get_claim(claim["id"])["status"] == "PAID"
    assert get_org(ctx["receiver_id"])["payable_balance_cents"] == 0


def test_disbursement_run_rejection_changes_no_claim_state():
    """PRD §3.8: "Running the batch is all-or-nothing: every listed claim must
    be `APPROVED` and belong to the named provider, else
    `ERR_CLAIM_NOT_PAYABLE`".

    Design: Difficulty/cross_entity_state_dependency/disbursement_run_requires_claims_approved
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    disbursement = get_success_data(api_client.create_disbursement(
        {"provider_org_id": ctx["receiver_id"], "funder_org_id": ctx["funder_id"],
         "claim_ids": [claim["id"]]},
        ctx["funder_admin"]))
    validate_error(api_client.run_disbursement(
        disbursement["id"], {}, ctx["funder_admin"]),
        ApiErrorId.ERR_CLAIM_NOT_PAYABLE, expected_status=409)
    # All-or-nothing: the rejected run moves nothing.
    assert get_claim(claim["id"])["status"] == "SUBMITTED"
    assert get_org(ctx["receiver_id"])["payable_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: cross_cutting / disbursement_failure_is_atomic_no_partial_payout
# ---------------------------------------------------------------------------

def test_disbursement_failure_is_atomic_no_partial_payout():
    """PRD §3.8: "A run invoked with `simulate_failure` set true instead moves
    the batch to `FAILED`, captures the `failure_reason`, and touches nothing
    else — no claim changes state and the provider balance is unchanged, so no
    partial payout is ever observable."

    Design: Corner/cross_cutting/disbursement_failure_is_atomic_no_partial_payout
    """
    ctx, referral1, claim1 = setup_approved_claim(delivered_units=5)
    referral2, _, _ = add_referral(ctx)
    route_referral(ctx, referral2["id"])
    accept_referral(ctx, referral2["id"])
    start_service(ctx, referral2["id"])
    confirm_outcome(ctx, referral2["id"], "DELIVERED", 7)
    claim2 = submit_claim(ctx, referral2["id"], 7)
    review_claim(ctx, claim2["id"], "rev1")
    approve_claim(ctx, claim2["id"], "rev2")

    disbursement = get_success_data(api_client.create_disbursement(
        {"provider_org_id": ctx["receiver_id"], "funder_org_id": ctx["funder_id"],
         "claim_ids": [claim1["id"], claim2["id"]]},
        ctx["funder_admin"]))

    failed = validate_success(api_client.run_disbursement(
        disbursement["id"], {"simulate_failure": True}, ctx["funder_admin"]))
    assert failed["status"] == "FAILED"
    assert isinstance(failed["failure_reason"], str) and failed["failure_reason"]

    assert get_claim(claim1["id"])["status"] == "APPROVED"
    assert get_claim(claim2["id"])["status"] == "APPROVED"
    # 500 + 700 cents accrued at approval; the failed run settles nothing.
    assert get_org(ctx["receiver_id"])["payable_balance_cents"] == 1_200


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#   agreement_inactive_beats_capacity_exhausted_on_route
# ---------------------------------------------------------------------------

def test_agreement_inactive_beats_capacity_exhausted_on_route():
    """PRD §2.6: "A request that fails an earlier category never surfaces a
    later category's error — a stale-version conflict, for instance, is
    reported before a state-machine violation, and a state-machine violation
    before any consent, agreement, eligibility, or capacity failure."
    PRD §3.4: "Expiring an agreement moves it `ACTIVE` → `EXPIRED`, after which
    new referrals between the parties are blocked with `ERR_AGREEMENT_INACTIVE`
    while existing non-terminal referrals are unaffected."

    Design: Difficulty/priority_pair_validation_conflict/agreement_inactive_beats_capacity_exhausted_on_route
    """
    # Capacity 1 fully consumed by a first ROUTED referral.
    ctx, rf1 = setup_routed_referral(capacity_total=1)
    rf2, client2, consent2 = add_referral(ctx)
    # Expire the agreement: now BOTH the agreement gate and the capacity gate
    # would fail for rf2's route; the agreement check wins by category order.
    get_success_data(api_client.expire_agreement(ctx["agreement_id"], COORDINATOR))

    validate_error(api_client.route_referral(
        rf2["id"], make_case_worker_headers(ctx["sender_id"])),
        ApiErrorId.ERR_AGREEMENT_INACTIVE, expected_status=422)
    assert get_referral(rf2["id"])["status"] == "DRAFT"


def test_expired_agreement_blocks_route_even_with_capacity_available():
    """PRD §3.4: "Expiring an agreement moves it `ACTIVE` → `EXPIRED`, after
    which new referrals between the parties are blocked with
    `ERR_AGREEMENT_INACTIVE` while existing non-terminal referrals are
    unaffected."

    Design: Difficulty/priority_pair_validation_conflict/agreement_inactive_beats_capacity_exhausted_on_route
    """
    ctx, rf1 = setup_routed_referral(capacity_total=10)
    rf2, client2, consent2 = add_referral(ctx)
    get_success_data(api_client.expire_agreement(ctx["agreement_id"], COORDINATOR))

    validate_error(api_client.route_referral(
        rf2["id"], make_case_worker_headers(ctx["sender_id"])),
        ApiErrorId.ERR_AGREEMENT_INACTIVE, expected_status=422)
    # The already-ROUTED referral is unaffected by the agreement expiring.
    assert get_referral(rf1["id"])["status"] == "ROUTED"

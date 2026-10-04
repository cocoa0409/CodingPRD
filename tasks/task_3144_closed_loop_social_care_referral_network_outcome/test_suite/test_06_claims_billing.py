"""Claims and adjudication: provisional quotes, tier boundary, cap waterfall,
segregation of duties, OCC on approve, duplicates, and billability gates.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_completed_referral, setup_submitted_claim, setup_approved_claim,
    setup_routed_referral, accept_referral, start_service, confirm_outcome,
    submit_claim, review_claim, approve_claim, get_claim, get_org,
    add_referral, route_referral,
    make_org_admin_headers, make_funder_admin_headers,
    create_rate_card,
)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / claim_quote_provisional_vs_final_cap_clamp
# ---------------------------------------------------------------------------

def test_claim_quote_provisional_ignores_cap_final_clamps():
    """PRD §3.7: "the provisional amount is simply `claimed_units` times that
    per-unit rate, with no monthly cap applied."
    PRD §3.7: "finally `approved_amount_cents` is the gross clamped to the
    remaining cap, floored at zero."

    Design: Difficulty/dual_variant_calc/claim_quote_provisional_vs_final_cap_clamp
    """
    ctx, referral, claim = setup_submitted_claim(
        delivered_units=200,
        rate_card_overrides={"rate_cents_per_unit": 100, "min_units": 1,
                             "monthly_cap_cents": 15_000})
    # PROVISIONAL variant: 200 * 100 = 20000, no monthly cap applied.
    assert claim["provisional_amount_cents"] == 20_000

    review_claim(ctx, claim["id"], "rev1")
    claim = approve_claim(ctx, claim["id"], "rev2")
    # FINAL variant: cap waterfall clamps 20000 gross to the 15000 cap.
    assert claim["approved_amount_cents"] == 15_000
    assert claim["provisional_amount_cents"] != claim["approved_amount_cents"]


def test_claim_approval_credits_provider_with_cap_clamped_amount():
    """PRD §3.7: "Approval credits the provider's `payable_balance_cents` by
    the approved amount and adds the same amount to the funder's monthly
    paid-to-date accumulator."
    PRD §3.7: "The provisional figure is deliberately optimistic: it can exceed
    the final approved amount."

    Design: Difficulty/dual_variant_calc/claim_quote_provisional_vs_final_cap_clamp
    """
    ctx, referral, claim = setup_submitted_claim(
        delivered_units=200,
        rate_card_overrides={"rate_cents_per_unit": 100, "min_units": 1,
                             "monthly_cap_cents": 15_000})
    review_claim(ctx, claim["id"], "rev1")
    approve_claim(ctx, claim["id"], "rev2")
    # The provider accrues the cap-clamped amount, not the optimistic quote.
    assert get_org(ctx["receiver_id"])["payable_balance_cents"] == 15_000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / claim_amount_circular_cap_evaluation_order
# ---------------------------------------------------------------------------

def _setup_two_claim_scenario(cap_cents, units=200, rate=100):
    """Two completed referrals with a claim each; the first claim approved.
    Returns (ctx, claim1, claim2)."""
    ctx, referral1, claim1 = setup_submitted_claim(
        delivered_units=units,
        rate_card_overrides={"rate_cents_per_unit": rate,
                             "monthly_cap_cents": cap_cents})
    review_claim(ctx, claim1["id"], "rev1")
    claim1 = approve_claim(ctx, claim1["id"], "rev2")

    referral2, _, _ = add_referral(ctx)
    route_referral(ctx, referral2["id"])
    accept_referral(ctx, referral2["id"])
    start_service(ctx, referral2["id"])
    confirm_outcome(ctx, referral2["id"], "DELIVERED", units)
    claim2 = submit_claim(ctx, referral2["id"], units)
    review_claim(ctx, claim2["id"], "rev1")
    return ctx, claim1, claim2


def test_cap_evaluation_order_excludes_the_claim_being_approved():
    """PRD §3.7: "The approved amount is the final variant of the quote,
    computed in a fixed order: first the gross is `claimed_units` times the
    tier-selected per-unit rate; then the funder's paid-to-date for the current
    calendar month is summed from the `approved_amount_cents` of this funder's
    other claims approved in that same month, explicitly excluding this claim;
    then the remaining cap is `monthly_cap_cents` minus that paid-to-date
    (treated as unbounded when the card is uncapped); and finally
    `approved_amount_cents` is the gross clamped to the remaining cap, floored
    at zero. A claim never contributes to its own cap residue".

    Design: Difficulty/combinatorial_formula/claim_amount_circular_cap_evaluation_order
    """
    ctx, claim1, claim2 = _setup_two_claim_scenario(cap_cents=25_000, units=200)
    claim2 = approve_claim(ctx, claim2["id"], "rev2")
    assert get_claim(claim1["id"])["approved_amount_cents"] == 20_000
    # 20000 gross clamped to the remaining cap 25000 - 20000 = 5000; wrongly
    # including the claim's own gross in paid-to-date would yield 0.
    assert claim2["approved_amount_cents"] == 5_000


def test_cap_evaluation_order_provider_balance_sums_both_approvals():
    """PRD §3.7: "Approval credits the provider's `payable_balance_cents` by
    the approved amount and adds the same amount to the funder's monthly
    paid-to-date accumulator."

    Design: Difficulty/combinatorial_formula/claim_amount_circular_cap_evaluation_order
    """
    ctx, claim1, claim2 = _setup_two_claim_scenario(cap_cents=25_000, units=200)
    approve_claim(ctx, claim2["id"], "rev2")
    assert get_org(ctx["receiver_id"])["payable_balance_cents"] == 25_000


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / rate_card_monthly_cap_rollover_boundary
# ---------------------------------------------------------------------------

def test_monthly_cap_rollover_first_claim_in_september_window():
    """PRD §3.7: "then the funder's paid-to-date for the current calendar month
    is summed from the `approved_amount_cents` of this funder's other claims
    approved in that same month, explicitly excluding this claim".

    Design: Difficulty/resource_temporal_overlap/rate_card_monthly_cap_rollover_boundary
    """
    ctx, claim1, claim2 = _setup_two_claim_scenario(cap_cents=25_000, units=200)
    assert claim1["approved_amount_cents"] == 20_000
    # Approve the second claim in the SAME calendar month: clamped by residue.
    claim2 = approve_claim(ctx, claim2["id"], "rev2")
    assert claim2["approved_amount_cents"] == 5_000


def test_monthly_cap_rollover_october_approval_uses_fresh_window():
    """PRD §3.7: "then the funder's paid-to-date for the current calendar month
    is summed from the `approved_amount_cents` of this funder's other claims
    approved in that same month, explicitly excluding this claim; then the
    remaining cap is `monthly_cap_cents` minus that paid-to-date (treated as
    unbounded when the card is uncapped); and finally `approved_amount_cents`
    is the gross clamped to the remaining cap, floored at zero."

    Design: Difficulty/resource_temporal_overlap/rate_card_monthly_cap_rollover_boundary
    """
    from test_helpers import set_clock
    ctx, claim1, claim2 = _setup_two_claim_scenario(cap_cents=25_000, units=200)
    assert claim1["approved_amount_cents"] == 20_000
    # Cross into October: a fresh monthly window, not clamped by September.
    set_clock("2026-10-01T00:00:00Z")
    claim2 = approve_claim(ctx, claim2["id"], "rev2")
    assert claim2["approved_amount_cents"] == 20_000


# ---------------------------------------------------------------------------
# Corner: calculations / claim_provisional_tier_boundary_at_min_units
# ---------------------------------------------------------------------------

def test_claim_provisional_tier_boundary_at_min_units():
    """PRD §3.7: "the per-unit rate is selected from the funder's `ACTIVE` rate
    card for the referral's category — the flat `rate_cents_per_unit` when no
    tier-2 rate is set or when `claimed_units` is strictly below `min_units`,
    otherwise the `tier2_rate_cents_per_unit`, with the tier-2 rate applying
    exactly at `min_units` — and the provisional amount is simply
    `claimed_units` times that per-unit rate, with no monthly cap applied."

    Design: Corner/calculations/claim_provisional_tier_boundary_at_min_units
    """
    rate_card = {"rate_cents_per_unit": 100, "min_units": 5,
                 "tier2_rate_cents_per_unit": 80}
    # 4 units: strictly below min_units, so the flat rate applies.
    ctx, referral1, claim1 = setup_submitted_claim(
        delivered_units=4, rate_card_overrides=rate_card)
    assert claim1["provisional_amount_cents"] == 400  # 4 * 100

    # 5 units: exactly at min_units, so the tier-2 rate applies (5 * 80 = 400).
    referral2, _, _ = add_referral(ctx)
    route_referral(ctx, referral2["id"])
    accept_referral(ctx, referral2["id"])
    start_service(ctx, referral2["id"])
    confirm_outcome(ctx, referral2["id"], "DELIVERED", 5)
    claim2 = submit_claim(ctx, referral2["id"], 5)
    assert claim2["provisional_amount_cents"] == 400  # 5 * 80


# ---------------------------------------------------------------------------
# Corner: state_machines / review_terminal_claim_returns_invalid_state
# ---------------------------------------------------------------------------

def test_review_terminal_claim_returns_invalid_state():
    """PRD §3.7: "Denial — `UNDER_REVIEW` → `DENIED`, with a stored `reason` —
    carries the same segregation-of-duties rule as approval."
    PRD §2.6: "then state validity, where a resource not in a valid from-state
    for the requested transition is rejected with `ERR_INVALID_STATE` (HTTP
    409)".

    Design: Corner/state_machines/review_terminal_claim_returns_invalid_state
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    review_claim(ctx, claim["id"], "rev1")
    denied = validate_success(api_client.deny_claim(
        claim["id"], {"reason": "insufficient documentation"},
        ctx["funder_admin_rev2"]))
    assert denied["status"] == "DENIED"

    # DENIED is terminal: a second review is a state violation.
    validate_error(api_client.review_claim(claim["id"], ctx["funder_admin_rev1"]),
                   ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_claim(claim["id"])["status"] == "DENIED"


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_claim_for_same_referral_rejected
# ---------------------------------------------------------------------------

def test_duplicate_claim_for_same_referral_rejected():
    """PRD §3.7: "exactly one claim may exist per referral, else
    `ERR_DUPLICATE_CLAIM`".

    Design: Corner/validations/duplicate_claim_for_same_referral_rejected
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    validate_error(api_client.create_claim(
        {"referral_id": referral["id"], "funder_org_id": ctx["funder_id"],
         "claimed_units": 10},
        make_org_admin_headers(ctx["receiver_id"])),
        ApiErrorId.ERR_DUPLICATE_CLAIM, expected_status=409)


# ---------------------------------------------------------------------------
# Corner: errors / error_claim_on_nonterminal_referral_not_billable
# ---------------------------------------------------------------------------

def test_error_claim_on_nonterminal_referral_not_billable():
    """PRD §3.7: "the referral must be `OUTCOME_RECORDED` with a billable
    outcome, else `ERR_REFERRAL_NOT_BILLABLE`".

    Design: Corner/errors/error_claim_on_nonterminal_referral_not_billable
    """
    ctx, referral = setup_routed_referral(with_funder=True)
    accept_referral(ctx, referral["id"])
    start_service(ctx, referral["id"])
    # The referral is IN_SERVICE with no recorded outcome.
    validate_error(api_client.create_claim(
        {"referral_id": referral["id"], "funder_org_id": ctx["funder_id"],
         "claimed_units": 10},
        make_org_admin_headers(ctx["receiver_id"])),
        ApiErrorId.ERR_REFERRAL_NOT_BILLABLE, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: rbac / segregation_of_duties_same_user_approve_rejected
# ---------------------------------------------------------------------------

def test_segregation_of_duties_same_user_approve_rejected():
    """PRD §3.7: "Approval — `UNDER_REVIEW` → `APPROVED`, OCC-guarded by
    `expected_claim_version` — must come from a `FunderAdmin` of the same
    funder whose full `X-User-ID` differs from `reviewed_by_user_id`; sameness
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "A `FunderAdmin` of the billed funder moves the claim `SUBMITTED`
    → `UNDER_REVIEW`, and the system records that caller's full `X-User-ID`
    into `reviewed_by_user_id`."

    Design: Corner/rbac/segregation_of_duties_same_user_approve_rejected
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    review_claim(ctx, claim["id"], "rev1")
    claim = get_claim(claim["id"], ctx["funder_admin"])
    assert claim["reviewed_by_user_id"] == f"{ctx['funder_id']}#rev1"

    # The same staff user (identical full X-User-ID) cannot approve.
    validate_error(api_client.approve_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        ctx["funder_admin_rev1"]),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)


def test_segregation_of_duties_different_staff_user_approves():
    """PRD §3.7: "Approval — `UNDER_REVIEW` → `APPROVED`, OCC-guarded by
    `expected_claim_version` — must come from a `FunderAdmin` of the same
    funder whose full `X-User-ID` differs from `reviewed_by_user_id`; sameness
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.1: "Segregation-of-duties checks, by contrast, compare the full
    `X-User-ID` string, suffix included, so two staff members of the same
    funder must use distinct staff labels to act as different adjudicators."

    Design: Corner/rbac/segregation_of_duties_same_user_approve_rejected
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    review_claim(ctx, claim["id"], "rev1")
    claim = get_claim(claim["id"], ctx["funder_admin"])
    # A different staff user of the same funder org can approve.
    approved = validate_success(api_client.approve_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        ctx["funder_admin_rev2"]))
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 1000  # 10 units * 100


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#   stale_version_beats_segregation_of_duties_on_claim_approve
# ---------------------------------------------------------------------------

def _setup_stale_and_sod_conflict():
    """Claim UNDER_REVIEW by rev1; the version captured at submission is stale
    (review advanced it) AND the approving caller is the same user rev1."""
    ctx, referral, claim = setup_submitted_claim(delivered_units=10)
    stale_version = claim["version"]
    review_claim(ctx, claim["id"], "rev1")
    return ctx, claim, stale_version


def test_stale_version_beats_segregation_of_duties_on_claim_approve():
    """PRD §2.6: "A request that fails an earlier category never surfaces a
    later category's error — a stale-version conflict, for instance, is
    reported before a state-machine violation, and a state-machine violation
    before any consent, agreement, eligibility, or capacity failure."
    PRD §2.8: "Approving a payment claim requires `expected_claim_version`
    matching the claim's current `version`."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_segregation_of_duties_on_claim_approve
    """
    ctx, claim, stale_version = _setup_stale_and_sod_conflict()
    # Both violations present: stale version (earlier category) wins over the
    # segregation-of-duties business rule.
    validate_error(api_client.approve_claim(
        claim["id"], {"expected_claim_version": stale_version},
        ctx["funder_admin_rev1"]),
        ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_stale_version_rejection_leaves_claim_unchanged():
    """PRD §2.8: "Approving a payment claim requires `expected_claim_version`
    matching the claim's current `version`. This captures the case where
    another writer has just mutated the claim — for example, a void that
    escrowed the reserve — so the approving writer's view is stale."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_segregation_of_duties_on_claim_approve
    """
    ctx, claim, stale_version = _setup_stale_and_sod_conflict()
    validate_error(api_client.approve_claim(
        claim["id"], {"expected_claim_version": stale_version},
        ctx["funder_admin_rev1"]),
        ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"

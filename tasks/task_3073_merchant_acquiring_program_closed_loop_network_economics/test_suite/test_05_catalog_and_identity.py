"""Industry catalog, card-member registration, and merchant identity counters."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    create_and_accept_merchant,
    create_and_activate_merchant,
    create_merchant_in_state,
    create_cardmember,
    create_active_cardmember,
    mark_merchant_dormant,
    get_merchant,
    get_cardmember,
    get_merchant_risk_state,
    list_industry_categories,
    set_clock,
)
from test_helpers.fixtures import ACQ, ISSUER, COMPLIANCE


# ═══ Difficulty: merchant identity counters ══════════════

def test_merchant_version_advances_once_per_mutation(api):
    """PRD §2.4: "Each mutable row also carries a `version` integer that begins
    at zero and increases by exactly one on every accepted mutation"

    Design: Corner/complexity_layers/merchant_version_increments_on_each_mutation
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], merchant_name="OCC Merchant 3b")
    assert merchant["version"] == 0

    accepted = api_client.accept_merchant(
        merchant["id"], {"expected_merchant_version": merchant["version"]}, ACQ)
    accepted = validate_success(accepted, 200)
    assert accepted["version"] == 1

    activated = validate_success(api_client.activate_merchant(accepted["id"], ACQ), 200)
    assert activated["version"] == 2

    dormant = mark_merchant_dormant(activated)
    assert dormant["version"] == 3


def test_status_version_tracks_only_the_two_status_activations(api):
    """PRD §3.1: "Every acceptance-status activation — the `PROSPECT` →
    `ACCEPTED` step and the `ACCEPTED` → `ACTIVE` step, but not the deactivation
    steps — advances `status_version` by exactly one and by no more."

    Design: Corner/complexity_layers/merchant_version_increments_on_each_mutation
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="OCC Merchant 3")
    assert merchant["status_version"] == 2

    dormant = mark_merchant_dormant(merchant)
    assert dormant["acceptance_status"] == "DORMANT"
    assert dormant["status_version"] == 2, (
        "marking an outlet dormant is not an activation, so status_version holds")


def test_acceptance_advances_status_version_off_zero(api):
    """PRD §3.1: "On success the merchant's `applied_discount_rate_bps` is
    recomputed against its current `volume_tier`, `status_version` advances by
    one, and `version` rises by one. This is the transition that first lifts a
    merchant off `status_version` 0."

    Design: Difficulty/non_linear_state_machine/merchant_acceptance_cycle_closes_on_declined_attempt_plus_sweep
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"])
    assert merchant["status_version"] == 0

    accepted = create_and_accept_merchant(category["id"], merchant_name="Cycle Merchant Base")
    assert accepted["status_version"] == 1, (
        "PROSPECT -> ACCEPTED is the transition that lifts the counter off zero")


# ═══ Corner: risk-state defaults ═════════════════════════

def test_merchant_risk_state_is_synthesized_flat_at_creation(api):
    """PRD §3.1: "it mints a `MerchantRiskState` row for the merchant with a
    `rolling_chargeback_count` of 0"
    PRD §3.7: "`unresolved_chargeback_count` counts the disputes still `OPEN` or
    `MERCHANT_RESPONDED` attributed to the merchant."

    Design: Corner/endpoints/merchant_risk_state_defaults_to_zero_after_create
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], merchant_name="Endpoint Merchant")

    risk_state = get_merchant_risk_state(merchant["id"])
    assert risk_state["merchant_id"] == merchant["id"]
    assert risk_state["rolling_chargeback_count"] == 0
    assert risk_state["unresolved_chargeback_count"] == 0
    assert risk_state["rolling_dispute_amount_cents"] == 0
    assert risk_state["suppression_flag"] is False


def test_merchant_create_stamps_the_prospect_defaults(api):
    """PRD §3.1: "Creation lands the outlet in `PROSPECT` with a `status_version`
    of 0, a `billed_volume_mtd_cents` of 0, a `rolling_90d_billed_volume_cents`
    of 0, and a `reserve_required_cents` of 0"

    Design: Corner/endpoints/merchant_risk_state_defaults_to_zero_after_create
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"])

    assert merchant["acceptance_status"] == "PROSPECT"
    assert merchant["status_version"] == 0
    assert merchant["billed_volume_mtd_cents"] == 0
    assert merchant["rolling_90d_billed_volume_cents"] == 0
    assert merchant["reserve_required_cents"] == 0
    assert merchant["volume_tier"] == "ACTIVITY"


# ═══ Corner: card-member registration defaults ═══════════

def test_cardmember_registration_applies_product_defaults(api):
    """PRD §3.6: "Registration takes a `member_name` and a `card_product` of
    `GREEN`, `GOLD`, `PLATINUM`, or `CENTURION`; the row opens with
    `annual_fee_cents` set from the card product, `reward_points_balance` at
    zero, and `lounge_access_tier` at `NONE`."

    Design: Corner/entities/cardmember_create_applies_card_product_defaults
    """
    set_clock()
    member = create_cardmember(card_product="PLATINUM")

    assert member["card_product"] == "PLATINUM"
    assert member["annual_fee_cents"] == 69500
    assert member["member_status"] == "PENDING"
    assert member["lounge_access_tier"] == "NONE"
    assert member["reward_points_balance"] == 0


def test_cardmember_get_with_an_unallocated_id_is_not_found(api):
    """PRD §2.10: "Third, existence: a missing merchant yields
    `ERR_MERCHANT_NOT_FOUND` (404) and a missing offer, statement, settlement,
    dispute, complaint, or acceptance yields `ERR_NOT_FOUND` (404)"

    Design: Corner/entities/cardmember_get_with_unknown_id_returns_not_found
    """
    set_clock()
    res = api_client.get_cardmember(
        "2f9c1a44-0000-4000-8000-000000000000", ISSUER)
    error_data = validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
    assert "member_name" not in error_data
    assert "card_product" not in error_data


# ═══ Corner: industry-category pagination ════════════════

def test_industry_category_list_paginates_with_a_whole_set_total(api):
    """PRD §2.3: "`total_count` counts the full filtered result set, not the
    page, and `has_more` is true exactly when `offset` plus the number of items
    returned is still below `total_count`."

    Design: Corner/endpoints/industry_category_list_paginates_with_total_count
    """
    set_clock()
    create_industry_category(industry_code="USD-1", industry_name="Alpha")
    create_industry_category(industry_code="USD-2", industry_name="Beta")
    create_industry_category(industry_code="USD-3", industry_name="Gamma")

    data, meta = validate_paginated(
        api_client.list_industry_categories(ACQ, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page_two, meta_two = validate_paginated(
        api_client.list_industry_categories(ACQ, params={"limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["has_more"] is False


def test_industry_category_list_orders_by_created_at_ascending(api):
    """PRD §2.3: "Collection results are ordered by `created_at` ascending unless
    an endpoint's specification pins a different deterministic order."

    Design: Corner/endpoints/industry_category_list_paginates_with_total_count
    """
    set_clock()
    create_industry_category(industry_code="USD-1", industry_name="Alpha")
    create_industry_category(industry_code="USD-2", industry_name="Beta")
    create_industry_category(industry_code="USD-3", industry_name="Gamma")

    categories = list_industry_categories()
    assert [c["industry_code"] for c in categories] == ["USD-1", "USD-2", "USD-3"]


# ═══ Difficulty: stale-version OCC ═══════════════════════

def _drive_to_prospect_again(category_id: str):
    """Full DORMANT -> PROSPECT cycle; returns (merchant, stale_version)."""
    merchant = create_and_activate_merchant(category_id, merchant_name="OCC Cycle Merchant")
    dormant = mark_merchant_dormant(merchant)
    stale_version = dormant["version"]
    return dormant, stale_version


def test_accept_with_a_superseded_merchant_version_is_rejected(api):
    """PRD §2.6: "That request must carry `expected_merchant_version`, the
    client's last-observed `version` of the target `Merchant`. If the merchant's
    current `version` no longer matches — because another writer has already
    driven the outlet forward through the acceptance cycle, legitimately
    superseding the state the client believed it was acting on — the request is
    refused with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/occ_stale_merchant_version_on_reactivation_round
    """
    set_clock()
    from test_helpers import rollup_gap, stamp_sweep, submit_declined_attempt
    from test_helpers.fixtures import create_unique_industry_category
    category = create_unique_industry_category()
    merchant = create_and_activate_merchant(
        category["id"], merchant_name="OCC Cycle Merchant")
    merchant = mark_merchant_dormant(merchant)
    # The version observed while the outlet was DORMANT -- the client's view that
    # the cycle is about to supersede.
    stale_version = merchant["version"]

    # Close the cycle back to PROSPECT through the sweep guard; this advances the
    # merchant version past stale_version.
    window_start = "2026-08-01T00:00:00Z"
    window_end = "2026-08-31T00:00:00Z"
    for day in (10, 11, 12, 13):
        submit_declined_attempt(
            merchant["id"], attempted_amount_cents=100000,
            decline_reason="MERCHANT_NOT_ACCEPTED",
            occurred_at=f"2026-08-{day:02d}T00:00:00Z")
    rollup_gap("US-NE", category["id"], window_start, window_end, 30)
    current = get_merchant(merchant["id"])
    stamp_sweep(current["status_version"], rolled_at="2026-09-01T00:00:00Z")
    assert get_merchant(merchant["id"])["acceptance_status"] == "PROSPECT"

    res = api_client.accept_merchant(
        merchant["id"], {"expected_merchant_version": stale_version}, ACQ)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_accept_with_the_current_merchant_version_succeeds(api):
    """PRD §2.6: "This is a staleness test, not an ordering test: it refuses any
    write issued against a superseded observation of the merchant, whether or not
    another request happened to be in flight."

    Design: Corner/complexity_layers/occ_current_version_on_first_acceptance_succeeds
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], merchant_name="OCC Merchant 2")
    observed = get_merchant(merchant["id"])

    res = api_client.accept_merchant(
        merchant["id"], {"expected_merchant_version": observed["version"]}, ACQ)
    accepted = validate_success(res, 200)
    assert accepted["acceptance_status"] == "ACCEPTED"
    assert accepted["version"] == observed["version"] + 1, (
        "a fresh observed version is accepted and advances by exactly one")
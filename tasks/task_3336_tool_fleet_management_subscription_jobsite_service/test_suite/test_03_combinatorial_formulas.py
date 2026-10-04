"""Combinatorial formulas: tiered billing, pack rounding, theft deductible."""
from test_helpers import (
    api_client, validate_success, setup_agreement_with_assets,
    setup_deployed_asset, report_claim, verify_claim,
    create_account, create_consumable_product,
    set_clock, make_contractor_manager_headers, make_claims_adjuster_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]

SIX_UNIT_DRILL_CARD = {
    "tool_category": "DRILL", "base_monthly_rate_cents": 10000,
    "tier2_threshold": 5, "tier2_monthly_rate_cents": 9000,
    "tier3_threshold": 10, "tier3_monthly_rate_cents": 8000,
    "min_monthly_fee_cents": 25000,
}


def test_activation_billing_tier_straddle_with_proration(api):
    """PRD §3.3: "tier-1 units are the smaller of `n` and one less than the
    card's `tier2_threshold`; tier-2 units exist only when `n` has reached the
    `tier2_threshold`, and then number the smaller of (`n` minus
    `tier2_threshold` plus one) and the width of the tier-2 band
    (`tier3_threshold` minus `tier2_threshold`)"
    PRD §3.3: "The evaluation order is pinned: tier split, then per-category
    minimum fee, then summation, then proration, then the single floor."

    Design: Difficulty/combinatorial_formula/billing_tier_straddle_min_fee_proration
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=6, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z", activate=False)
    r = api_client.activate_agreement(env["account_id"], env["agreement_id"], ADMIN)
    agreement = validate_success(r)
    # 6 units: tier1 = min(6, 4) = 4 @10000 = 40000; tier2 = min(6-5+1, 10-5) = 2 @9000
    # = 18000; charge = 58000; max(58000, 25000) = 58000; floor(58000 * 15/30) = 29000
    assert agreement["billed_this_month_cents"] == 29000, (
        f"expected 29000, got {agreement['billed_this_month_cents']}")


def test_activation_billing_posts_to_outstanding_balance(api):
    """PRD §3.3: "Activation runs the first monthly billing in its prorated
    variant, commits the result to `billed_this_month_cents`, adds the billed
    amount to the account's `outstanding_balance_cents`, and increments the
    agreement's `version` by 1."

    Design: Difficulty/combinatorial_formula/billing_tier_straddle_min_fee_proration
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=6, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z", activate=False)
    r = api_client.activate_agreement(env["account_id"], env["agreement_id"], ADMIN)
    agreement = validate_success(r)
    account = validate_success(api_client.get_account(env["account_id"], ADMIN))
    assert agreement["status"] == "ACTIVE"
    assert account["outstanding_balance_cents"] == 29000
    assert agreement["version"] == env["agreement_version"] + 1


def test_consumable_pack_rounding_per_line_then_sum(api):
    """PRD §3.8: "Order totals are computed per line and then summed: each
    line's pack count is its `quantity_units` divided by the product's
    `pack_size` rounded up to a whole pack, the line total is that pack count
    times `pack_size` times `unit_price_cents` in integer arithmetic, and
    `total_cents` is the sum of the line totals."
    PRD §3.8: "Merging quantities across lines of the same product and rounding
    once is forbidden, because two under-filled lines of one product would round
    to fewer packs together than apart."

    Design: Difficulty/combinatorial_formula/consumable_pack_rounding_per_line_then_sum
    """
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="RND-1", name="Anchor bolt", unit_price_cents=500, pack_size=10,
        requires_application_approval=False)
    r = api_client.create_consumable_order(
        acct, [{"product_id": product["id"], "quantity_units": 6},
               {"product_id": product["id"], "quantity_units": 4}], cm)
    order = validate_success(r, expected_status=201)
    r = api_client.submit_consumable_order(acct, order["id"], cm)
    submitted = validate_success(r)
    assert submitted["status"] == "SUBMITTED"
    # ceil(6/10)=1 pack + ceil(4/10)=1 pack -> 2 * 10 * 500
    assert submitted["total_cents"] == 10000, (
        f"per-line rounding gives 10000, got {submitted['total_cents']}")


def test_consumable_pack_rounding_computed_at_creation(api):
    """PRD §3.8: "The total is computed when the order is created and recomputed
    when it is submitted."

    Design: Difficulty/combinatorial_formula/consumable_pack_rounding_per_line_then_sum
    """
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="RND-2", name="Anchor bolt B", unit_price_cents=500, pack_size=10,
        requires_application_approval=False)
    r = api_client.create_consumable_order(
        acct, [{"product_id": product["id"], "quantity_units": 6},
               {"product_id": product["id"], "quantity_units": 4}], cm)
    order = validate_success(r, expected_status=201)
    assert order["total_cents"] == 10000
    assert order["status"] == "DRAFT"


def test_theft_deductible_floor_binds_after_depreciation(api):
    """PRD §3.7: "Third, the `deductible_cents` is 10 percent of the depreciated
    value, rounded half-up to whole cents, then clamped: raised to at least
    50000 cents and lowered to at most 250000 cents."
    PRD §3.7: "Second, the depreciated value is the model's
    `replacement_value_cents` scaled by the age band — 100 percent when the
    asset is at most 12 months old, 70 percent from month 13 through month 36,
    40 percent beyond 36 months — rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/theft_deductible_floor_binds_after_depreciation
    """
    env = setup_deployed_asset(
        clock="2026-09-01T00:00:00Z",
        category="DRILL", weight_class="LIGHT", replacement_value_cents=100000,
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 1000,
            "effective_to": "2028-12-31T00:00:00Z",
        },
        term_months=24)
    # commissioned_on 2026-09-01; report at 2027-10-15 -> 409 days -> 13 months
    set_clock("2027-10-15T00:00:00Z")
    claim = report_claim(env["asset"]["id"], env["js"])
    verify_claim(claim["id"], "PR-T1", "2027-10-15T12:00:00Z", "admin-t1")
    adj = make_claims_adjuster_headers("adj-t1")
    r = api_client.decide_theft_claim(claim["id"], "APPROVE", adj)
    claim = validate_success(r)
    assert claim["status"] == "APPROVED"
    # age 13 months -> 70% of 100000 = 70000; 10% = 7000 < 50000 floor
    assert claim["deductible_cents"] == 50000
    assert claim["approved_replacement_value_cents"] == 20000


def test_theft_depreciation_age_boundary_twelve_months(api):
    """PRD §3.7: "First, the asset's age in whole months is the floor of the
    days between its `commissioned_on` and the claim's `reported_at`, divided
    by 30. Second, the depreciated value is the model's
    `replacement_value_cents` scaled by the age band — 100 percent when the
    asset is at most 12 months old, 70 percent from month 13 through month 36,
    40 percent beyond 36 months — rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/theft_deductible_floor_binds_after_depreciation
    """
    env = setup_deployed_asset(
        clock="2026-09-01T00:00:00Z",
        category="DRILL", weight_class="LIGHT", replacement_value_cents=100000,
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 1000,
            "effective_to": "2028-12-31T00:00:00Z",
        },
        term_months=24)
    # commissioned 2026-09-01; report 2027-09-01 -> 365 days -> age 12 months
    set_clock("2027-09-01T00:00:00Z")
    claim = report_claim(env["asset"]["id"], env["js"])
    verify_claim(claim["id"], "PR-T1B", "2027-09-01T12:00:00Z", "admin-t1b")
    adj = make_claims_adjuster_headers("adj-t1b")
    r = api_client.decide_theft_claim(claim["id"], "APPROVE", adj)
    claim = validate_success(r)
    # age 12 -> 100% tier: depreciated 100000; 10% = 10000 < 50000 floor
    assert claim["deductible_cents"] == 50000
    assert claim["approved_replacement_value_cents"] == 50000
    assert claim["status"] == "APPROVED"

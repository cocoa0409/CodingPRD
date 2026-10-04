"""Enterprise agreements: volume-tier derivation from trailing spend, the
half-open window overlap rule, and the EXPIRING renewal cycle with OCC.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    CLOCK_START_UTC,
    ApiErrorId,
    api_client,
    assert_enterprise_agreement,
    create_account,
    create_enterprise_agreement,
    enterprise_agreement_payload,
    get_enterprise_agreement,
    plus_days,
    plus_months,
    renew_enterprise_agreement,
    same_instant,
    set_clock,
    setup_account_with_agreement,
    validate_error,
    validate_success,
)

# Tier derivation is read back through GET: any trailing spend at or above
# the SILVER floor is invoiced spend far above the credit line, so the
# account stands on HOLD and no further order can be submitted - the tier
# assertion is therefore made on the agreement read, per the PRD's band text.


def test_pricing_tier_gold_at_floor_reads_discount_10(api):
    """PRD section 3.2: "Trailing spend below 10000000 cents reads `BASE`; at
    least 10000000 but below 50000000 reads `SILVER`; at least 50000000 but
    below 200000000 reads `GOLD`; and at least 200000000 reads `PLATINUM`."
    and "The tier maps to a `discount_pct` applied to the account's orders:
    `BASE` discounts 0 percent, `SILVER` 5 percent, `GOLD` 10 percent, and
    `PLATINUM` 15 percent. Pricing is band-flat, never blended: the single
    rate of the band the account currently occupies applies to every order
    line in full."

    Design: Difficulty/dual_variant_calc/order_discount_flat_band_vs_blended_marginal
    """
    account, agreement = setup_account_with_agreement(
        50000000, committed_annual_spend_cents=50000000
    )
    fresh = get_enterprise_agreement(agreement)
    assert_enterprise_agreement(fresh)
    assert fresh["current_tier"] == "GOLD", (
        "trailing spend of exactly 50000000 reads GOLD (band floor inclusive)"
    )
    assert fresh["discount_pct"] == 10, "the GOLD band's flat rate is 10 percent"


def test_pricing_tier_gold_at_prd_example_spend(api):
    """PRD section 3.2: "An account with trailing spend of 60000000 cents sits
    in `GOLD` and prices a 10000-cent line at 9000 cents; an implementation
    that blended the marginal slices of each band — five percent on the
    portion of spend in the silver slice and ten percent on the remainder —
    would compute an effective rate near 6.667 percent and price the same
    line at 9333 cents, and that reading is wrong."

    Design: Difficulty/dual_variant_calc/order_discount_flat_band_vs_blended_marginal
    """
    account, agreement = setup_account_with_agreement(
        60000000, committed_annual_spend_cents=60000000
    )
    fresh = get_enterprise_agreement(agreement)
    assert fresh["current_tier"] == "GOLD"
    assert fresh["discount_pct"] == 10, (
        "the flat GOLD band rate is 10; the blended-marginal reading near "
        "6.667 percent is explicitly wrong"
    )


def test_tier_boundary_gold_floor_inclusive(api):
    """PRD section 3.2: "Every boundary is inclusive on its lower edge —
    trailing spend of exactly 50000000 cents is `GOLD`, not `SILVER`."

    Design: Difficulty/boundary_precision_check/ea_tier_boundary_inclusive_floor
    """
    account, agreement = setup_account_with_agreement(
        50000000, committed_annual_spend_cents=50000000
    )
    fresh = get_enterprise_agreement(agreement)
    assert fresh["current_tier"] == "GOLD"
    assert fresh["discount_pct"] == 10


def test_tier_boundary_one_cent_below_gold_floor(api):
    """PRD section 3.2: "at least 10000000 but below 50000000 reads `SILVER`"
    and "Every boundary is inclusive on its lower edge — trailing spend of
    exactly 50000000 cents is `GOLD`, not `SILVER`."

    Design: Difficulty/boundary_precision_check/ea_tier_boundary_inclusive_floor
    """
    account, agreement = setup_account_with_agreement(
        49999999, committed_annual_spend_cents=49999999
    )
    fresh = get_enterprise_agreement(agreement)
    assert fresh["current_tier"] == "SILVER", (
        "49999999 is one cent below the GOLD floor and stays SILVER"
    )
    assert fresh["discount_pct"] == 5


def test_agreement_window_overlap_rejected(api):
    """PRD section 3.2: "when the new window intersects the window of an
    existing agreement of the same account that reads `ACTIVE` or `EXPIRING`,
    creation is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency
    """
    account = create_account(name="Window Lab")
    create_enterprise_agreement(
        account,
        start_date=plus_months(CLOCK_START_UTC, -8),   # 2026-01-01T00:00:00Z
        end_date=plus_months(CLOCK_START_UTC, 4),      # 2027-01-01T00:00:00Z
        committed_annual_spend_cents=50000,
    )
    response = api_client.create_enterprise_agreement(
        enterprise_agreement_payload(
            account["id"],
            start_date=plus_days(plus_months(CLOCK_START_UTC, 3), 30),  # 2026-12-31
            end_date=plus_months(CLOCK_START_UTC, 16),                  # 2028-01-01
            committed_annual_spend_cents=50000,
        ),
        headers=ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


def test_agreement_window_half_open_adjacency_allowed(api):
    """PRD section 3.2: "Adjacency is allowed, so a new agreement whose
    `start_date` equals the existing agreement's `end_date` does not overlap,
    and agreements that already read `EXPIRED` or `TERMINATED` never block a
    new one."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency
    """
    account = create_account(name="Window Lab")
    end_a = plus_months(CLOCK_START_UTC, 4)  # 2027-01-01T00:00:00Z
    create_enterprise_agreement(
        account,
        start_date=plus_months(CLOCK_START_UTC, -8),
        end_date=end_a,
        committed_annual_spend_cents=50000,
    )
    response = api_client.create_enterprise_agreement(
        enterprise_agreement_payload(
            account["id"],
            start_date=end_a,
            end_date=plus_months(CLOCK_START_UTC, 16),
            committed_annual_spend_cents=50000,
        ),
        headers=ACCOUNT_MANAGER,
    )
    created = validate_success(response, 201)
    assert created["status"] == "ACTIVE", (
        "half-open adjacency is not an overlap; the successor starts ACTIVE"
    )


def test_ea_expiring_renew_cycle_succeeds(api):
    """PRD section 3.2: "otherwise `EXPIRING` once the logical clock has
    reached the instant 60 days before `end_date`" and "While an agreement
    reads `EXPIRING`, an `AccountManager` may renew it, which extends
    `end_date` by 12 months, increments `renewal_count` by 1, and increments
    the agreement's `version` by 1; because the window now ends later, the
    derived status returns to `ACTIVE` on the next read."

    Design: Corner/state_machines/ea_expiring_renew_cycle_succeeds
    """
    account = create_account(name="Renew Lab")
    end_date = plus_months(CLOCK_START_UTC, 9)  # 2027-06-01T00:00:00Z
    agreement = create_enterprise_agreement(
        account,
        start_date=plus_months(CLOCK_START_UTC, -3),  # 2026-06-01T00:00:00Z
        end_date=end_date,
        committed_annual_spend_cents=50000,
    )
    observed_version = agreement["version"]

    set_clock(plus_days(plus_months(CLOCK_START_UTC, 7), 14))  # 2027-04-15
    due = get_enterprise_agreement(agreement)
    assert due["status"] == "EXPIRING", "60-day renewal window has opened"
    assert due["version"] == observed_version, (
        "the derived EXPIRING transition never bumps version"
    )

    renewed = renew_enterprise_agreement(agreement, observed_version)
    assert renewed["status"] == "ACTIVE"
    assert same_instant(renewed["end_date"], plus_months(end_date, 12))  # 2028-06-01
    assert renewed["renewal_count"] == 1
    assert renewed["version"] == observed_version + 1

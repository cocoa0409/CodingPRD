"""Advisory fee ladder, household aggregation and the billing basis floors."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_household_with_two_accounts,
    setup_two_households_fee_tier_boundary,
    refetch_household,
    settle_billing_run,
    refetch_account,
)
"""Advisory fee ladder, household aggregation and the billing basis floors."""
"""Advisory fee ladder, household aggregation and the billing basis floors."""

ADVISOR = TEST_USERS["advisor_ops_headers"]


class TestAdvisoryFeeLadder:

    def test_household_aggregated_fee_matches_the_pinned_ladder(self):
        """PRD §3.6: "The first step is the attributable tier fee. The platform
        walks the attributable tier ladder in ascending order of its lower bound."
        PRD §3.6: "The second step is the platform fee, and unlike the attributable
        ladder it selects a single tier rather than accumulating across bands."
        PRD §3.6: "The fifth step rounds that product half up to whole cents, and
        this is the only rounding the ladder performs — the result is the run's
        `gross_fee_cents`."

        Design: Difficulty/combinatorial_formula/fee_marginal_tiers_with_single_platform_tier
        """
        firm, _agreement, household, _accounts = setup_household_with_two_accounts(
            basis_by_account=(200_000_000, 120_000_000),
        )
        basis = refetch_household(household["id"])["household_fee_basis_cents"]
        assert basis == 320_000_000, f"expected the accounts to aggregate to 320000000, got {basis}"

        run = settle_billing_run(
            firm["id"], household["id"], stated_invoice_cents=890_553,
        )
        assert run["period_days"] == 91
        assert run["gross_fee_cents"] == 890_553
        assert run["billing_run_status"] == "SETTLED"

    def test_household_annual_fee_carries_both_tier_components(self):
        """PRD §3.6: "The third step sums the two components into the annual fee."
        PRD §3.6: "When at least one of the household's accounts has
        `householding_consent` of `OP_IN` or `NONE`, the ladder runs once against
        the single aggregate `household_fee_basis_cents`; this aggregate figure is
        the value stored on `household_annual_fee_cents`."

        Design: Difficulty/combinatorial_formula/fee_marginal_tiers_with_single_platform_tier
        """
        _firm, _agreement, household, _accounts = setup_household_with_two_accounts(
            basis_by_account=(200_000_000, 120_000_000),
        )
        billed = refetch_household(household["id"])
        assert billed["household_fee_basis_cents"] == 320_000_000
        # 3379999 attributable (110 bps on the first 250000000, 90 bps on the rest)
        # plus 192000 platform (6 bps on the whole balance).
        assert billed["household_annual_fee_cents"] == 3_571_999

    def test_platform_tier_selection_changes_at_the_quarter_billion_boundary(self):
        """PRD §3.6: "The platform finds the one platform-tier band whose range
        contains the household basis — the topmost band having no upper bound —
        takes that band's rate, and computes the household basis multiplied by that
        rate divided by one hundred, floored to whole cents."
        PRD §3.6: "up to 250000000 cents at 8 basis points; from 250000001 through
        500000000 cents at 6 basis points".

        Design: Difficulty/boundary_precision_check/fee_basis_tier_boundary_at_quarter_billion_cents
        """
        scenario = setup_two_households_fee_tier_boundary(250_000_000, 249_999_999)
        high = refetch_household(scenario["high_household"]["id"])
        assert high["household_fee_basis_cents"] == 250_000_000

        run = settle_billing_run(
            scenario["firm"]["id"], high["id"], stated_invoice_cents=735_479,
        )
        assert run["gross_fee_cents"] == 735_479
        assert run["billing_run_status"] == "SETTLED"

    def test_one_cent_below_the_minimum_basis_is_refused(self):
        """PRD §3.7: "Finally the basis must reach an inclusive minimum of 250000000
        cents before a run may be seeded; a basis of exactly 250000000 cents is
        accepted and one of 249999999 cents is refused with
        `ERR_FEE_BASIS_BELOW_MINIMUM` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/fee_basis_tier_boundary_at_quarter_billion_cents
        """
        scenario = setup_two_households_fee_tier_boundary(250_000_000, 249_999_999)
        low = refetch_household(scenario["low_household"]["id"])
        assert low["household_fee_basis_cents"] == 249_999_999

        res = api_client.create_billing_run(
            {
                "firm_id": scenario["firm"]["id"],
                "household_id": low["id"],
                "period_start_date": "2026-09-01T00:00:00Z",
                "period_end_date": "2026-12-01T00:00:00Z",
                "fee_variant_used": "HOUSEHOLD_AGGREGATED",
                "stated_invoice_cents": 0,
            },
            ADVISOR,
        )
        validate_error(res, "ERR_FEE_BASIS_BELOW_MINIMUM", expected_status=409)


class TestHouseholdAggregationVariants:

    def test_aggregated_variant_bills_the_whole_household_once(self):
        """PRD §3.6: "When at least one of the household's accounts has
        `householding_consent` of `OP_IN` or `NONE`, the ladder runs once against
        the single aggregate `household_fee_basis_cents`."
        PRD §3.6: "The sixth step subtracts the credits applied, giving
        `net_fee_cents` as the gross fee minus `credit_applied_cents`."

        Design: Difficulty/dual_variant_calc/fee_household_aggregated_vs_per_account_variant
        """
        firm, _agreement, household, _accounts = setup_household_with_two_accounts(
            basis_by_account=(200_000_000, 120_000_000),
        )
        billed = refetch_household(household["id"])
        assert billed["household_fee_basis_cents"] == 320_000_000

        run = settle_billing_run(
            firm["id"], household["id"], stated_invoice_cents=890_553,
        )
        assert run["gross_fee_cents"] == 890_553
        assert run["net_fee_cents"] == 890_553
        assert run["billing_run_status"] == "SETTLED"

    def test_per_account_variant_restarts_the_ladder_for_every_account(self):
        """PRD §3.6: "When every account of the household has `householding_consent`
        of `OP_OUT`, the same ladder runs independently for each account against that
        account's own `account_fee_basis_cents`, and the per-account annual fees are
        summed."
        PRD §3.6: "For identical data the per-account variant yields a strictly
        larger annual fee than the aggregated variant whenever the household holds
        more than one account, because the ladder restarts at its lowest band for
        every account."

        Design: Difficulty/dual_variant_calc/fee_household_aggregated_vs_per_account_variant
        """
        firm, _agreement, household, accounts = setup_household_with_two_accounts(
            basis_by_account=(200_000_000, 120_000_000),
        )
        aggregate_run = settle_billing_run(
            firm["id"], household["id"], stated_invoice_cents=890_553,
        )
        assert aggregate_run["gross_fee_cents"] == 890_553

        for account in accounts:
            validate_success(api_client.patch_account(
                account["id"], {"householding_consent": "OP_OUT"}, ADVISOR, row=refetch_account(account["id"])), 200)

        per_account_run = settle_billing_run(
            firm["id"], household["id"], stated_invoice_cents=941_414,
            fee_variant="PER_ACCOUNT",
        )
        assert per_account_run["gross_fee_cents"] == 941_414
        assert per_account_run["gross_fee_cents"] - aggregate_run["gross_fee_cents"] == 50_861
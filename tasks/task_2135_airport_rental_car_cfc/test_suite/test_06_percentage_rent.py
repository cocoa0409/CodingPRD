"""The two percentage-rent variants driven over an identical revenue stream."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    factories as f,
    fixtures as fx,
    validate_success,
)


def _two_variant_scenario(api):
    """Two brands at one facility, identical commercial terms, differing only in
    `rent_settlement_basis`, each fed 5,000,000 then 20,000,000 cents of audited revenue."""
    facility = fx.create_facility(api)
    cumulative = fx.add_brand_with_active_agreement(
        api, facility["id"], "AVX", "Avex Rent A Car",
        mag_annual_cents=12_000_000,
        percentage_rent_rate_bps=1_000,
        rent_settlement_basis="CUMULATIVE_YTD",
    )
    monthly = fx.add_brand_with_active_agreement(
        api, facility["id"], "BUD", "Budline Auto Rental",
        mag_annual_cents=12_000_000,
        percentage_rent_rate_bps=1_000,
        rent_settlement_basis="MONTHLY_STANDALONE",
    )

    for side in (cumulative, monthly):
        fx.create_accepted_report(
            api, side["agreement"]["id"], side["operator"],
            period_year=2026, period_month=1,
            reported_gross_revenue_cents=5_000_000,
            reported_on_airport_transaction_days=4_000,
        )
        side["month_two"] = fx.create_report_under_audit(
            api, side["agreement"]["id"], side["operator"],
            period_year=2026, period_month=2,
            reported_gross_revenue_cents=20_000_000,
            reported_on_airport_transaction_days=8_000,
        )

    for side in (cumulative, monthly):
        side["month_two_accepted"] = validate_success(
            api.accept_report(
                side["month_two"]["id"],
                f.accept_report_payload(
                    audited_gross_revenue_cents=20_000_000,
                    audited_on_airport_transaction_days=8_000,
                ),
                AUDITOR,
            )
        )
    return cumulative, monthly


def test_cumulative_ytd_nets_the_installment_against_prior_billing(api):
    """PRD §3.5: "Under the `CUMULATIVE_YTD` variant, the rent due to date is the greater of
    the year-to-date percentage rent and the minimum guarantee to date, and the installment
    for this acceptance is that rent due to date minus the agreement's
    `rent_billed_to_date_cents` as it stood before this acceptance."
    PRD §3.5: "Year-to-date percentage rent is the agreement's `gross_revenue_ytd_cents`
    multiplied by `percentage_rent_rate_bps`, divided by 10,000, and rounded half up."
    PRD §3.5: "The installment is also written onto the report as
    `period_rent_installment_cents`."

    Design: Difficulty/dual_variant_calc/percentage_rent_cumulative_ytd_vs_monthly_standalone_divergence
    """
    cumulative, _monthly = _two_variant_scenario(api)

    agreement = validate_success(api.get_agreement(cumulative["agreement"]["id"], ADMIN))

    assert agreement["gross_revenue_ytd_cents"] == 25_000_000
    assert agreement["percentage_rent_accrued_cents"] == 2_500_000
    assert agreement["rent_billed_to_date_cents"] == 2_500_000, (
        "the cumulative basis charges only the delta over what was already billed"
    )
    assert agreement["last_installment_cents"] == 1_500_000
    assert agreement["rent_tier"] == "PERCENTAGE"
    assert agreement["mag_shortfall_cents"] == 0
    assert cumulative["month_two_accepted"]["period_rent_installment_cents"] == 1_500_000


def test_monthly_standalone_never_recovers_the_guarantee_floor(api):
    """PRD §3.5: "Under the `MONTHLY_STANDALONE` variant, the month stands alone. The month's
    own percentage rent is this report's `audited_gross_revenue_cents` multiplied by
    `percentage_rent_rate_bps`, divided by 10,000 and rounded half up, and the installment is
    the greater of that month's percentage rent and the monthly minimum guarantee."
    PRD §3.5: "Nothing is netted against what was billed before, so a weak month's guarantee
    floor is never recovered by a later strong month, and an agreement on this basis always
    ends the year with a `rent_billed_to_date_cents` strictly higher than the cumulative basis
    would have produced whenever any single month fell below the monthly floor."
    PRD §3.5: "The monthly minimum guarantee is `mag_annual_cents` divided by 12 and truncated
    downward to a whole cent"

    Design: Difficulty/dual_variant_calc/percentage_rent_cumulative_ytd_vs_monthly_standalone_divergence
    """
    cumulative, monthly = _two_variant_scenario(api)

    monthly_agreement = validate_success(api.get_agreement(monthly["agreement"]["id"], ADMIN))
    cumulative_agreement = validate_success(
        api.get_agreement(cumulative["agreement"]["id"], ADMIN)
    )

    assert monthly_agreement["gross_revenue_ytd_cents"] == 25_000_000
    assert monthly_agreement["percentage_rent_accrued_cents"] == 2_500_000
    assert monthly_agreement["rent_billed_to_date_cents"] == 3_000_000, (
        "the standalone basis keeps month one's 1,000,000 floor and adds month two's 2,000,000"
    )
    assert monthly_agreement["last_installment_cents"] == 2_000_000
    assert monthly_agreement["rent_tier"] == "PERCENTAGE"
    assert monthly_agreement["mag_shortfall_cents"] == 0
    assert monthly["month_two_accepted"]["period_rent_installment_cents"] == 2_000_000
    assert (
        monthly_agreement["rent_billed_to_date_cents"]
        - cumulative_agreement["rent_billed_to_date_cents"]
        == 500_000
    ), "the two bases diverge by exactly the guarantee floor the strong month absorbed"

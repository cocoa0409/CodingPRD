"""Dual-variant derivations: the two FMV methods and the two benchmark bases.

Each family stores one field computed by two structurally different formulas
selected by a discriminator on the row, so identical inputs must land on
different answers.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.constants import (
    BENCHMARK_BASIS_COMP_PER_WRVU,
    BENCHMARK_BASIS_TOTAL_CASH_COMP,
    EMPLOYMENT_PROSPECTIVE,
    FMV_SAFE_HARBOR_PERCENTILE,
    METHOD_MARKET_APPROACH,
    MODEL_BASE_PLUS_INCENTIVE,
    MODEL_WRVU_PRODUCTIVITY,
    OPINION_STATUS_DRAFT,
)
from test_helpers.fixtures import (
    VALUATION_ANALYST,
    acquisition_version,
    create_plan,
    diligence_deal,
    file_income_fmv,
    file_opinion,
    read_acquisition,
)

# Income approach on 240,000,000 cents of EBITDA over three years at 300 bps
# growth, 1400 bps discount and 250 bps terminal growth.
INCOME_CONCLUDED_CENTS = 2_167_511_341
# Market approach on the same EBITDA at a six-and-a-half-times multiple.
MARKET_CONCLUDED_CENTS = 1_560_000_000
SHARED_EBITDA_CENTS = 240_000_000
MARKET_MULTIPLE_BPS = 65_000


def _market_on_same_ebitda(api: ApiClient, acquisition_id: str) -> dict:
    version = acquisition_version(api, acquisition_id, VALUATION_ANALYST)
    payload = f.market_fmv_payload(
        acquisition_id,
        version,
        normalized_ebitda_cents=SHARED_EBITDA_CENTS,
        market_multiple_bps=MARKET_MULTIPLE_BPS,
    )
    return file_opinion(api, payload)


def test_income_and_market_conclude_different_values_on_one_ebitda(api: ApiClient):
    """The two FMV methods diverge on byte-identical normalised EBITDA.

    PRD: "The growth rate, the discount rate, the terminal growth rate, and the
    projection horizon are ignored entirely under this variant, which is why the
    same normalised EBITDA can conclude at a materially different value
    depending on which method the analyst chose."

    Design: Difficulty/dual_variant_calc/fmv_income_vs_market_diverges_on_same_ebitda_inputs
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    income = file_income_fmv(api, acquisition_id)
    market = _market_on_same_ebitda(api, acquisition_id)

    assert income["normalized_ebitda_cents"] == market["normalized_ebitda_cents"]
    a.assert_money_equals(
        income["concluded_value_cents"], INCOME_CONCLUDED_CENTS, "income concluded_value_cents"
    )
    a.assert_money_equals(
        market["concluded_value_cents"], MARKET_CONCLUDED_CENTS, "market concluded_value_cents"
    )
    assert (
        market["concluded_value_cents"] - income["concluded_value_cents"]
        == MARKET_CONCLUDED_CENTS - INCOME_CONCLUDED_CENTS
    )


def test_market_approach_ignores_the_income_inputs_it_never_received(api: ApiClient):
    """A market-approach opinion carries its multiple and no discounted-cash-flow inputs.

    PRD: "For an `FMV` opinion filed under the **market approach**,
    `concluded_value_cents` is `normalized_ebitda_cents` multiplied by
    `market_multiple_bps`, divided by 10000, and rounded half up to a whole
    cent."

    Design: Difficulty/dual_variant_calc/fmv_income_vs_market_diverges_on_same_ebitda_inputs
    """
    deal = diligence_deal(api)
    market = _market_on_same_ebitda(api, deal["acquisition"]["id"])

    assert market["method"] == METHOD_MARKET_APPROACH
    a.assert_bps(market["market_multiple_bps"], "market_multiple_bps")
    assert market["market_multiple_bps"] == MARKET_MULTIPLE_BPS
    a.assert_fields_null(
        market, "projection_years", "discount_rate_bps", "terminal_growth_bps"
    )
    a.assert_money_equals(
        market["concluded_value_cents"], MARKET_CONCLUDED_CENTS, "concluded_value_cents"
    )


def test_both_filings_land_in_draft_and_expire_twelve_months_out(api: ApiClient):
    """Filing sets DRAFT and stamps expiry twelve calendar months after the effective date.

    PRD: "Every opinion, of either type, is stamped with an `expires_on`
    computed as `effective_on` plus twelve calendar months, keeping the same
    day-of-month and falling back to the last day of the target month where that
    day does not exist."

    Design: Difficulty/dual_variant_calc/fmv_income_vs_market_diverges_on_same_ebitda_inputs
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    income = file_income_fmv(api, acquisition_id)
    market = _market_on_same_ebitda(api, acquisition_id)

    for opinion in (income, market):
        a.assert_status(opinion, OPINION_STATUS_DRAFT)
        assert opinion["is_pinned"] is False
        a.assert_date_only(opinion["expires_on"], "expires_on")
        assert opinion["expires_on"] == "2027-08-01"


def test_each_opinion_filing_increments_the_acquisition_version(api: ApiClient):
    """Filing an opinion is a mutation of the acquisition aggregate.

    PRD: "The server stores the caller's `X-User-ID` as `prepared_by_user_id`,
    sets `status` to `DRAFT` and `is_pinned` to false, and increments the
    acquisition's `version`."

    Design: Difficulty/dual_variant_calc/fmv_income_vs_market_diverges_on_same_ebitda_inputs
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    before = read_acquisition(api, acquisition_id)
    file_income_fmv(api, acquisition_id)
    after_first = read_acquisition(api, acquisition_id)
    a.assert_version_bumped_by(before, after_first, 1)

    _market_on_same_ebitda(api, acquisition_id)
    after_second = read_acquisition(api, acquisition_id)
    a.assert_version_bumped_by(after_first, after_second, 1)
    a.assert_consideration_all_null(after_second)


def test_two_bases_diverge_on_identical_plan_economics(api: ApiClient):
    """Identical cash and per-wRVU economics benchmark differently under the two bases.

    PRD: "Under `COMP_PER_WRVU` the compared value is `comp_per_wrvu_cents` and
    the quartiles are the specialty's dollars-per-work-RVU figures, so two plans
    with identical total cash compensation land at different percentiles
    whenever their work-RVU volumes differ."

    Design: Difficulty/dual_variant_calc/comp_percentile_tcc_vs_per_wrvu_diverges_on_same_physician_economics
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]

    salary_plan = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_BASE_PLUS_INCENTIVE,
        base_salary_cents=6_000_000,
        conversion_factor_cents_per_wrvu=7_000,
        threshold_wrvu=0,
        projected_annual_wrvu=4_000,
    )
    wrvu_plan = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_WRVU_PRODUCTIVITY,
        base_salary_cents=0,
        conversion_factor_cents_per_wrvu=8_500,
        threshold_wrvu=0,
        projected_annual_wrvu=4_000,
    )

    for plan in (salary_plan, wrvu_plan):
        a.assert_money_equals(
            plan["projected_total_cash_comp_cents"], 34_000_000, "projected_total_cash_comp_cents"
        )
        a.assert_money_equals(plan["comp_per_wrvu_cents"], 8_500, "comp_per_wrvu_cents")

    assert salary_plan["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP
    assert wrvu_plan["benchmark_basis"] == BENCHMARK_BASIS_COMP_PER_WRVU
    a.assert_percentage_equals(salary_plan["benchmark_percentile"], 84.00, "benchmark_percentile")
    a.assert_percentage_equals(wrvu_plan["benchmark_percentile"], 91.07, "benchmark_percentile")


def test_one_basis_sits_inside_the_safe_harbour_and_the_other_outside(api: ApiClient):
    """The same economics fall on opposite sides of the ninetieth-percentile safe harbour.

    PRD: "The fair market value safe harbour is the ninetieth percentile, and
    exactly 90.00 is **inside** it."

    Design: Difficulty/dual_variant_calc/comp_percentile_tcc_vs_per_wrvu_diverges_on_same_physician_economics
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]

    salary_plan = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_BASE_PLUS_INCENTIVE,
        base_salary_cents=6_000_000,
        conversion_factor_cents_per_wrvu=7_000,
        threshold_wrvu=0,
        projected_annual_wrvu=4_000,
    )
    wrvu_plan = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_WRVU_PRODUCTIVITY,
        base_salary_cents=0,
        conversion_factor_cents_per_wrvu=8_500,
        threshold_wrvu=0,
        projected_annual_wrvu=4_000,
    )

    assert salary_plan["benchmark_percentile"] <= FMV_SAFE_HARBOR_PERCENTILE
    assert wrvu_plan["benchmark_percentile"] > FMV_SAFE_HARBOR_PERCENTILE

    physician = validate_success(api.get_physician(physician_id, VALUATION_ANALYST))
    assert physician["employment_status"] == EMPLOYMENT_PROSPECTIVE

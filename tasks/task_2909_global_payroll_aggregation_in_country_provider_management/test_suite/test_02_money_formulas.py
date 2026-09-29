"""Multi-input money formulas whose order of operations is load-bearing.

Two families are exercised: the funding conversion, where each component is
rounded before the buffer is taken, and the penalty assessment, where the
surcharge tier is chosen from the uncapped base before the indemnity cap bites.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import (
    FILING_LATE,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FUNDING_DRAFT,
    PENALTY_ASSESSED,
    PENALTY_OWNER_SHARED,
    PROVIDER_ACTIVE,
)

# 6 500 000 + 2 000 000 + 150 000 local minor units at 0.92 local per source unit.
_NET_SOURCE = 7065217
_EMPLOYER_COST_SOURCE = 2173913
_PROVIDER_FEE_SOURCE = 163043
_SUBTOTAL_SOURCE = 9402173
_BUFFER_SOURCE = 141033
_FUNDED_SOURCE = 9543206
# What converting the aggregate once instead of each component would have produced.
_AGGREGATE_ONCE_SOURCE = 9543207

# A country whose single obligation accrues 15 000 minor units a day, engaged to a
# small provider whose indemnity cap is 25.00 percent of a 200 000 annual fee.
_SMALL_COUNTRY = {
    "country_code": "FR",
    "required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING],
    "penalty_daily_rate_minor": 15000,
}
_SMALL_PROVIDER = {
    "legal_name": "MicroPay SARL",
    "annual_fee_minor": 200000,
    "indemnity_cap_pct": 25.0,
}


def _capped_provider_late_filing(api):
    """Sweep the single obligation three late days past its deadline."""
    ctx = fx.setup_results_approved_cycle(
        api, country_overrides=_SMALL_COUNTRY, provider_overrides=_SMALL_PROVIDER
    )
    fx.set_clock(api, "2026-09-13T12:00:00Z")
    swept = fx.sweep_filings(api, ctx["cycle_id"])
    filing = a.find_by(swept, "filing_type", FILING_TYPE_INCOME_TAX_WITHHOLDING)
    return ctx, filing


def test_funding_conversion_rounds_each_component_before_summing(api):
    """The three components are converted and rounded one at a time, and the
    subtotal is the sum of those already-rounded amounts.

    PRD 3.6: "Then each of those three components is converted on its own: divide
    `net_minor` by the `fx_rate` and round the quotient half up to a whole
    funding-currency minor unit; do the same for `employer_cost_minor`; do the same
    for `provider_fee_minor`."

    Design: Difficulty/combinatorial_formula/funding_conversion_rounds_each_component_before_summing
    """
    ctx = fx.setup_drafted_funding(api)
    funding = ctx["funding"]

    a.assert_minor_amount(
        funding["requested_local_minor"], 8650000, "requested_local_minor"
    )
    components = funding["component_source_minor"]
    a.assert_minor_amount(components["net"], _NET_SOURCE, "component net")
    a.assert_minor_amount(
        components["employer_cost"], _EMPLOYER_COST_SOURCE, "component employer_cost"
    )
    a.assert_minor_amount(
        components["provider_fee"], _PROVIDER_FEE_SOURCE, "component provider_fee"
    )
    assert (
        components["net"] + components["employer_cost"] + components["provider_fee"]
        == _SUBTOTAL_SOURCE
    ), f"expected a subtotal of {_SUBTOTAL_SOURCE}, got {components}"


def test_funding_buffer_is_taken_on_the_sum_of_the_rounded_components(api):
    """The 1.50 percent buffer is applied to the summed rounded components, which
    lands a whole minor unit away from the convert-the-aggregate-once answer.

    PRD 3.6: "Converting the aggregate once instead of converting each component
    separately is wrong and can differ from the required answer by a minor unit;
    the buffer is likewise computed on the sum of the rounded components rather
    than on any unrounded intermediate."

    Design: Difficulty/combinatorial_formula/funding_conversion_rounds_each_component_before_summing
    """
    ctx = fx.setup_drafted_funding(api)
    funding = ctx["funding"]

    a.assert_minor_amount(
        funding["funded_source_minor"], _FUNDED_SOURCE, "funded_source_minor"
    )
    assert funding["funded_source_minor"] == _SUBTOTAL_SOURCE + _BUFFER_SOURCE, (
        "funded_source_minor must be the subtotal plus the buffer on that subtotal"
    )
    assert funding["funded_source_minor"] != _AGGREGATE_ONCE_SOURCE, (
        "converting the aggregate once would have produced "
        f"{_AGGREGATE_ONCE_SOURCE}, which is not the required answer"
    )
    assert funding["status"] == FUNDING_DRAFT, (
        f"a drafted instruction opens in DRAFT, got {funding['status']}"
    )
    a.assert_null_fields(funding, ["approver_user_id", "releaser_user_id", "recall_reason"])


def test_penalty_tier_is_selected_from_the_uncapped_base(api):
    """A base of 70 000 earns the middle 10.00 percent surcharge even though the
    provider's indemnity cap will later hold its share down to 50 000.

    PRD 3.7: "Note the deliberate sequencing: because the tier is chosen from the
    uncapped base, a provider whose cap bites still bears the surcharge that the
    larger, uncapped base earned."

    Design: Difficulty/combinatorial_formula/penalty_tier_selected_from_uncapped_base_before_indemnity_cap
    """
    _, filing = _capped_provider_late_filing(api)

    a.assert_penalty_assessment(
        filing,
        late_days=3,
        base_penalty_minor=70000,
        surcharge_minor=7000,
        total_penalty_minor=77000,
        provider_share_minor=50000,
        client_share_minor=27000,
        penalty_owner=PENALTY_OWNER_SHARED,
    )
    assert filing["status"] == FILING_LATE, (
        f"the swept obligation is late, got {filing['status']}"
    )
    assert filing["penalty_status"] == PENALTY_ASSESSED, (
        f"the penalty dimension moves to ASSESSED, got {filing['penalty_status']}"
    )


def test_capped_penalty_leaves_the_remainder_with_the_client(api):
    """The share the cap refused becomes the client's, and only the provider's own
    capped share lands on its exposure.

    PRD 3.7: "`client_share_minor` is always `total_penalty_minor` less
    `provider_share_minor`, so the two shares sum exactly to the total with no
    rounding drift."

    Design: Difficulty/combinatorial_formula/penalty_tier_selected_from_uncapped_base_before_indemnity_cap
    """
    ctx, filing = _capped_provider_late_filing(api)

    assert filing["client_share_minor"] == (
        filing["total_penalty_minor"] - filing["provider_share_minor"]
    ), "the client bears exactly the part of the total the provider does not"

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider,
        status=PROVIDER_ACTIVE,
        service_score=100.00,
        open_penalty_minor=50000,
    )

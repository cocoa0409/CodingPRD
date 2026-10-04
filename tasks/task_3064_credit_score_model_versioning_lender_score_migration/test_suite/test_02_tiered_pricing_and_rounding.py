"""Marginal tier arithmetic, the overage surcharge, and the pinned rounding order."""
import pytest

from test_helpers import api_client, validate_success, COMPLIANCE, setup_license_with_postings, setup_cross_bureau_study


def _fee_quote(license_id, prospective_count):
    return validate_success(
        api_client.fee_quote(license_id, prospective_count, COMPLIANCE), 200)


class TestMarginalTierSchedule:

    def test_quote_inside_the_first_band_charges_three_first_band_units(self, api):
        """PRD §3.7: "The tier boundaries are 0, 10,000 and 50,000 units, and the
        rates are 18 cents for units above 0 and at or below 10,000, 14 cents for
        units above 10,000 and at or below 50,000, and 9 cents for units above
        50,000."
        PRD §3.7: "The marginal charge for the posting that carries a licence's
        `cumulative_score_count` from its value before the posting to one greater
        than that value is the cumulative charge at the higher count minus the
        cumulative charge at the lower count"

        Design: Difficulty/combinatorial_formula/combinatorial_formula_tiered_marginal_and_overage_fee
        """
        fixture = setup_license_with_postings(num_postings=2, entitled_count=2,
                                              volume_tier="VOLUME_TIER_3",
                                              lender_code="LEND-SMALL",
                                              consumer_ref="cons-770")
        data = _fee_quote(fixture["license"]["id"], 3)
        assert data["marginal_fee_cents"] == 54
        # "the blended figure is the highest tier reached applied against every
        # unit": at 3 units the highest tier reached is the first band, so the
        # blended rate is 3 * 18 = 54.
        assert data["blended_fee_cents"] == 54

    def test_blended_rate_charges_the_highest_tier_against_every_unit(self, api):
        """PRD §3.7: "A pricing desk may also ask, without mutating anything, what
        the marginal and blended unit fees would be at a prospective cumulative
        count supplied as `prospective_count`; the blended figure is the highest
        tier reached applied against every unit and is reported only as the
        period's effective unit rate, never as a settled amount."

        Design: Difficulty/combinatorial_formula/combinatorial_formula_tiered_marginal_and_overage_fee
        """
        fixture = setup_license_with_postings(num_postings=2, entitled_count=2,
                                              volume_tier="VOLUME_TIER_3",
                                              lender_code="LEND-SMALL",
                                              consumer_ref="cons-770")
        # PRD §3.7: "the blended figure is the highest tier reached applied
        # against every unit". At 10001 units the highest tier reached is the
        # second band (14 cents), so the blended rate is 10001 * 14 = 140014.
        data = _fee_quote(fixture["license"]["id"], 10001)
        assert data["blended_fee_cents"] == 140014
        assert data["blended_fee_cents"] != data["marginal_fee_cents"]

    def test_the_third_unit_crosses_the_tier_schedule_at_the_second_band(self, api):
        """PRD §3.7: "so a posting that crosses a boundary charges the old tier's
        rate on the units below the boundary and the new tier's rate only on the
        units at or above it."

        Design: Difficulty/combinatorial_formula/combinatorial_formula_tiered_marginal_and_overage_fee
        """
        fixture = setup_license_with_postings(num_postings=2, entitled_count=2,
                                              volume_tier="VOLUME_TIER_3",
                                              lender_code="LEND-SMALL",
                                              consumer_ref="cons-770")
        license_id = fixture["license"]["id"]
        assert _fee_quote(license_id, 3)["marginal_fee_cents"] == 54
        assert _fee_quote(license_id, 10001)["marginal_fee_cents"] == 180014
        assert _fee_quote(license_id, 10001)["tier_index"] == 1

    def test_settled_postings_leave_the_licence_counters_exact(self, api):
        """PRD §3.8: "A `MARGINAL_PRICING` entry is appended to the fee ledger — its
        `ledger_description` carrying the audit prose for the accrual, its
        `cumulative_count_before` recording the licence's cumulative count
        immediately before the entry was written — and the licence's
        `cumulative_fee_cents` and `cumulative_score_count` advance by the marginal
        charge and one unit respectively"

        Design: Difficulty/combinatorial_formula/combinatorial_formula_tiered_marginal_and_overage_fee
        """
        fixture = setup_license_with_postings(num_postings=2, entitled_count=2,
                                              volume_tier="VOLUME_TIER_3",
                                              lender_code="LEND-SMALL",
                                              consumer_ref="cons-770")
        license_ = fixture["license"]
        assert license_["cumulative_score_count"] == 2
        assert license_["cumulative_fee_cents"] == 36


class TestRoundingOrders:

    def test_weighted_route_rounds_each_product_before_summing(self, api):
        """PRD §3.4: "The bureau-weighted composite multiplies each posting's
        `effective_score` by its variant weight, rounds each of those products
        half-up to two decimal places *before* summing them, and then rounds the
        resulting sum half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/combinatorial_formula_per_posting_rounding_order
        """
        capture, study = setup_cross_bureau_study(consumer_ref="cons-902",
                                                  sample_ref="XFER-02")
        assert study["weighted_composite"] == pytest.approx(699.91, abs=0.001)

    def test_unweighted_route_truncates_toward_zero_before_rounding(self, api):
        """PRD §3.4: "The unweighted composite deliberately ignores the weights
        entirely: it sums the `effective_score` values, divides by the count of
        postings, multiplies that mean by one hundred, truncates the result toward
        zero to a whole-hundredth increment, divides by one hundred again, and
        finally rounds half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/combinatorial_formula_per_posting_rounding_order
        """
        capture, study = setup_cross_bureau_study(consumer_ref="cons-902",
                                                  sample_ref="XFER-02")
        assert study["unweighted_composite"] == pytest.approx(699.66, abs=0.001)

    def test_reversing_either_order_changes_the_reported_answer(self, api):
        """PRD §3.4: "The bureau-weighted composite multiplies each posting's
        `effective_score` by its variant weight, rounds each of those products
        half-up to two decimal places *before* summing them, and then rounds the
        resulting sum half-up to two decimal places."
        PRD §3.4: "The unweighted composite deliberately ignores the weights
        entirely"

        Design: Difficulty/combinatorial_formula/combinatorial_formula_per_posting_rounding_order
        """
        capture, study = setup_cross_bureau_study(consumer_ref="cons-902",
                                                  sample_ref="XFER-02")
        assert study["weighted_composite"] != study["unweighted_composite"]
        weights = [capture["variants"][i]["aggregate_weight_pct"]
                   for i in ("AUTO", "BANKCARD", "MORTGAGE")]
        assert sum(weights) == pytest.approx(1.00, abs=1e-9)

    def test_member_weights_are_read_from_the_variants_at_evaluation_time(self, api):
        """PRD §3.4: "each contributing posting's weight is its own variant's
        `aggregate_weight_pct`, read at evaluation time."

        Design: Difficulty/combinatorial_formula/combinatorial_formula_per_posting_rounding_order
        """
        capture, study = setup_cross_bureau_study(consumer_ref="cons-902",
                                                  sample_ref="XFER-02")
        scores = {k: v["effective_score"] for k, v in capture["results"].items()}
        weights = {k: v["aggregate_weight_pct"] for k, v in capture["variants"].items()}
        expected = round(sum(round(scores[k] * weights[k], 2) for k in scores), 2)
        assert study["weighted_composite"] == pytest.approx(expected, abs=0.01)
"""Numeric threshold crossings, tested on both sides of the exact boundary."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE,
    setup_released_dual_auto,
    create_and_activate_license,
    create_consumer,
    create_reason_code,
    post_score,
)


def _licensed_auto(consumer_ref):
    bureau, model, variant = setup_released_dual_auto()
    license_ = create_and_activate_license(variant["id"], entitled_count=500)
    consumer = create_consumer(consumer_ref=consumer_ref, age_years=52)
    return bureau, model, variant, license_, consumer


class TestCutoffComparisonBoundary:

    def test_a_score_exactly_on_the_cutoff_is_undecided(self, api):
        """PRD §3.8: "An `effective_score` strictly greater than the cut-off yields
        `APPROVE`, an `effective_score` strictly less than it yields `DECLINE`, and
        an `effective_score` exactly equal to it leaves the posting `UNDECIDED`."

        Design: Difficulty/boundary_precision_check/boundary_cutoff_comparison_on_posted_score
        """
        bureau, model, variant, license_, consumer = _licensed_auto("cons-701")
        posting = post_score(license_["id"], consumer["id"], variant["id"],
                             bureau["id"], 715)
        assert posting["effective_score"] == 700
        assert posting["decision"] == "UNDECIDED"

    def test_one_point_above_the_cutoff_approves(self, api):
        """PRD §3.8: "An `effective_score` strictly greater than the cut-off yields
        `APPROVE`"

        Design: Difficulty/boundary_precision_check/boundary_cutoff_comparison_on_posted_score
        """
        bureau, model, variant, license_, consumer = _licensed_auto("cons-701")
        posting = post_score(license_["id"], consumer["id"], variant["id"],
                             bureau["id"], 716)
        assert posting["effective_score"] == 701
        assert posting["decision"] == "APPROVE"

    def test_one_point_below_the_cutoff_declines(self, api):
        """PRD §3.8: "an `effective_score` strictly less than it yields `DECLINE`"

        Design: Difficulty/boundary_precision_check/boundary_cutoff_comparison_on_posted_score
        """
        bureau, model, variant, license_, consumer = _licensed_auto("cons-701")
        posting = post_score(license_["id"], consumer["id"], variant["id"],
                             bureau["id"], 714)
        assert posting["effective_score"] == 699
        assert posting["decision"] == "DECLINE"

    def test_a_decline_binds_the_lowest_composite_primary_code(self, api):
        """PRD §3.8: "A `DECLINE` binds `decision_reason_code_id` to the `ACTIVE`
        `PRIMARY` reason code on the effective variant carrying the lexicographically
        lowest `composite_code`."

        Design: Difficulty/boundary_precision_check/boundary_cutoff_comparison_on_posted_score
        """
        bureau, model, variant, license_, consumer = _licensed_auto("cons-701")
        create_reason_code(variant["id"], depth_tier="PRIMARY",
                           trigger_feature_code="SEGMENT_ZERO", code_label="rc-b-zero",
                           weight_pct=0.30)
        posting = post_score(license_["id"], consumer["id"], variant["id"],
                             bureau["id"], 714)
        assert posting["decision"] == "DECLINE"
        assert posting["decision_reason_code_id"] is not None


class TestTierBoundaryAtTenThousand:

    def _wide_licence(self):
        _, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"], entitled_count=20000,
                                               volume_tier="VOLUME_TIER_2")
        return license_

    def test_a_quote_at_exactly_ten_thousand_stays_inside_the_first_band(self, api):
        """PRD §3.7: "The tier boundaries are 0, 10,000 and 50,000 units, and the
        rates are 18 cents for units above 0 and at or below 10,000"

        Design: Difficulty/boundary_precision_check/boundary_tier_crossing_at_exactly_ten_thousand
        """
        license_ = self._wide_licence()
        data = validate_success(
            api_client.fee_quote(license_["id"], 10000, COMPLIANCE), 200)
        assert data["marginal_fee_cents"] == 180000
        assert data["tier_index"] == 0

    def test_the_very_next_unit_is_charged_at_the_second_band_rate(self, api):
        """PRD §3.7: "so a posting that crosses a boundary charges the old tier's
        rate on the units below the boundary and the new tier's rate only on the
        units at or above it."

        Design: Difficulty/boundary_precision_check/boundary_tier_crossing_at_exactly_ten_thousand
        """
        license_ = self._wide_licence()
        data = validate_success(
            api_client.fee_quote(license_["id"], 10001, COMPLIANCE), 200)
        assert data["marginal_fee_cents"] == 180014

    def test_one_unit_below_the_boundary_is_priced_wholly_in_the_first_band(self, api):
        """PRD §3.7: "The cumulative charge through any count is the sum, over those
        bands, of the units falling inside the band multiplied by the band's rate."

        Design: Difficulty/boundary_precision_check/boundary_tier_crossing_at_exactly_ten_thousand
        """
        license_ = self._wide_licence()
        data = validate_success(
            api_client.fee_quote(license_["id"], 9999, COMPLIANCE), 200)
        assert data["marginal_fee_cents"] == 179982

    def test_the_what_if_quote_is_read_only(self, api):
        """PRD §3.7: "A pricing desk may also ask, without mutating anything, what
        the marginal and blended unit fees would be at a prospective cumulative
        count supplied as `prospective_count`"

        Design: Difficulty/boundary_precision_check/boundary_tier_crossing_at_exactly_ten_thousand
        """
        license_ = self._wide_licence()
        before = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        api_client.fee_quote(license_["id"], 10000, COMPLIANCE)
        api_client.fee_quote(license_["id"], 10001, COMPLIANCE)
        after = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        assert after["cumulative_score_count"] == 0
        assert after["version"] == before["version"]
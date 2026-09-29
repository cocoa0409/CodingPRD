"""
Retroactive award anchoring and the dependent add-on gate.

Both families run one veteran with two dependents through the whole claim
lifecycle and then read the money the decision produced.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    assert_cents,
    assert_combined_rating,
    create_active_representative,
    create_claim_in_peer_review,
    create_represented_veteran,
    file_claim,
    mark_claim_ready,
    read_claim,
    read_veteran,
    record_decision,
    set_clock,
    set_clock_date,
)

VETERAN_PROFILE = {
    "date_of_birth": "1979-03-04",
    "service_start_date": "2001-09-11",
    "service_end_date": "2005-09-10",
    "household_income_cents": 1500000,
    "net_worth_cents": 2000000,
    "dependent_count": 2,
    "homeless_status": "NOT_HOMELESS",
    "referral_source": "WALK_IN",
}


@pytest.fixture
def two_anchored_claims(api):
    """
    One veteran, two seventy-percent grants decided the same day, differing
    only in whether the claim carries an intent-to-file date.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer, **VETERAN_PROFILE)

    with_intent = create_claim_in_peer_review(
        api, base, reviewer=reviewer, intent_to_file_date="2025-09-15"
    )
    mark_claim_ready(api, with_intent["claim"]["id"], with_intent["reviewer_headers"])
    without_intent = create_claim_in_peer_review(api, base, reviewer=reviewer)
    mark_claim_ready(
        api, without_intent["claim"]["id"], without_intent["reviewer_headers"]
    )

    set_clock_date(api, "2026-08-10", "09:00:00")
    file_claim(api, with_intent["claim"]["id"], base["officer_headers"], "2026-08-10")
    file_claim(api, without_intent["claim"]["id"], base["officer_headers"], "2026-08-10")

    set_clock_date(api, "2026-12-20", "09:00:00")
    itf = record_decision(
        api,
        with_intent["claim"]["id"],
        base["officer_headers"],
        decision_outcome="GRANTED",
        awarded_rating_pct=70,
        decided_on="2026-12-20",
    )
    filed = record_decision(
        api,
        without_intent["claim"]["id"],
        base["officer_headers"],
        decision_outcome="GRANTED",
        awarded_rating_pct=70,
        decided_on="2026-12-20",
    )
    return {"itf": itf, "filed": filed, "base": base}


@pytest.fixture
def low_rated_award(api):
    """A veteran with two dependents granted twenty percent over fifteen months."""
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer, **VETERAN_PROFILE)
    ctx = create_claim_in_peer_review(
        api, base, reviewer=reviewer, intent_to_file_date="2025-09-15"
    )
    mark_claim_ready(api, ctx["claim"]["id"], ctx["reviewer_headers"])

    set_clock_date(api, "2026-08-10", "09:00:00")
    file_claim(api, ctx["claim"]["id"], base["officer_headers"], "2026-08-10")
    set_clock_date(api, "2026-12-20", "09:00:00")
    ctx["claim"] = record_decision(
        api,
        ctx["claim"]["id"],
        base["officer_headers"],
        decision_outcome="GRANTED",
        awarded_rating_pct=20,
        decided_on="2026-12-20",
    )
    return ctx


class TestRetroactiveAwardAnchoring:
    """The anchor chosen at filing time decides how large the award is."""

    def test_intent_to_file_anchor_pays_the_whole_intent_window(
        self, api, two_anchored_claims
    ):
        """
        The PRD fixes the inclusive comparison at the year mark:
        "a gap of exactly 365 days still anchors on the intent to file and a gap of 366 days does not".
        The money it produces "is settled in whole cents with no rounding anywhere, because every constant involved is an integer number of cents".

        Design: Difficulty/dual_variant_calc/retro_award_itf_anchored_versus_filed_anchored_divergence
        """
        claim = two_anchored_claims["itf"]
        assert claim["effective_date_basis"] == "INTENT_TO_FILE_ANCHORED"
        assert claim["effective_date"] == "2025-09-15"
        assert_cents(claim["retro_award_cents"], 2884500)
        assert claim["status"] == "DECIDED"

    def test_filed_date_anchor_confines_the_retroactive_period(
        self, api, two_anchored_claims
    ):
        """
        With no intent to file the basis is the filing date, and
        "anchoring on the filing date confines it to decision-processing time, so identical ratings, dependents and decision dates produce a strictly smaller award".

        Design: Difficulty/dual_variant_calc/retro_award_itf_anchored_versus_filed_anchored_divergence
        """
        claim = two_anchored_claims["filed"]
        assert claim["effective_date_basis"] == "FILED_DATE_ANCHORED"
        assert claim["effective_date"] == "2026-08-10"
        assert_cents(claim["retro_award_cents"], 769200)
        assert claim["status"] == "DECIDED"

    def test_the_two_anchors_diverge_by_eleven_whole_months(
        self, api, two_anchored_claims
    ):
        """
        The two claims share rating, dependents and decision date, so the whole
        difference comes from the anchor and the month count:
        "that final subtraction is what makes the count whole months elapsed rather than a difference of month labels".

        Design: Difficulty/dual_variant_calc/retro_award_itf_anchored_versus_filed_anchored_divergence
        """
        itf = read_claim(
            api, two_anchored_claims["itf"]["id"], two_anchored_claims["base"]["officer_headers"]
        )
        filed = read_claim(
            api, two_anchored_claims["filed"]["id"], two_anchored_claims["base"]["officer_headers"]
        )
        assert_cents(itf["retro_award_cents"] - filed["retro_award_cents"], 2115300)
        assert itf["awarded_rating_pct"] == 70
        assert filed["awarded_rating_pct"] == 70


class TestDependentAddOnGate:
    """The dependent add-on is switched off below the rating floor."""

    def test_award_below_the_rating_floor_omits_the_dependent_add_on(
        self, api, low_rated_award
    ):
        """
        Twenty percent over fifteen whole months pays the bare statutory rate:
        "when the rating is below 30 the add-on is exactly 0 regardless of"
        the household size.

        Design: Difficulty/combinatorial_formula/retro_dependent_add_on_gated_off_below_rating_floor
        """
        claim = low_rated_award["claim"]
        assert claim["effective_date_basis"] == "INTENT_TO_FILE_ANCHORED"
        assert_cents(claim["retro_award_cents"], 519000)
        assert claim["retro_award_cents"] != 765000

    def test_dependents_are_still_on_file_while_the_add_on_is_gated_off(
        self, api, low_rated_award
    ):
        """
        The gate reads the rating alone. The add-on would otherwise be paid
        "for each dependent counted, where the count is the veteran's"
        own tally capped at three.

        Design: Difficulty/combinatorial_formula/retro_dependent_add_on_gated_off_below_rating_floor
        """
        veteran = read_veteran(api, low_rated_award["veteran"]["id"])
        assert veteran["dependent_count"] == 2
        assert low_rated_award["claim"]["awarded_rating_pct"] == 20

    def test_decision_moves_the_veteran_rating_and_priority_group(
        self, api, low_rated_award
    ):
        """
        The decision propagates to the intake row: that rating
        "is recomputed and `priority_group` is re-derived from it".

        Design: Difficulty/combinatorial_formula/retro_dependent_add_on_gated_off_below_rating_floor
        """
        veteran = read_veteran(api, low_rated_award["veteran"]["id"])
        assert_combined_rating(veteran["combined_rating_pct"], 20)
        assert veteran["priority_group"] == "P3"

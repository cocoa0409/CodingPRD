"""
Quarterly outcome reports: the two weighting bases and the empty window.

Both fixtures move the logical clock past the labelled quarter before any
computation runs, because a quarter that has not closed cannot be scored.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    assert_cents,
    assert_exact_whole,
    assert_pct_1dp,
    compute_report_payload,
    conditions,
    create_active_representative,
    create_claim_ready_to_file,
    create_draft_claim,
    create_represented_veteran,
    file_claim,
    load_claim_above_threshold,
    mark_claim_ready,
    open_evidence_development,
    open_outcome_report,
    read_claim,
    record_decision,
    set_clock,
    set_clock_date,
    submit_for_peer_review,
    validate_success,
)

DEPENDENT_PROFILE = {
    "date_of_birth": "1979-03-04",
    "service_start_date": "2001-09-11",
    "service_end_date": "2005-09-10",
    "household_income_cents": 1500000,
    "net_worth_cents": 2000000,
    "dependent_count": 2,
    "homeless_status": "NOT_HOMELESS",
    "referral_source": "WALK_IN",
}


def _two_claims_ready(api):
    """One veteran with two independent claims sitting in READY_TO_FILE."""
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    ctx = create_claim_ready_to_file(
        api,
        create_represented_veteran(api, designee=preparer, **DEPENDENT_PROFILE),
        reviewer=reviewer,
        claimed_conditions=conditions("tinnitus"),
    )
    second = create_draft_claim(
        api,
        ctx["veteran"]["id"],
        ctx["poa"]["id"],
        ctx["officer_headers"],
        claimed_conditions=conditions("lumbar_strain"),
    )
    open_evidence_development(api, second["id"], ctx["officer_headers"])
    load_claim_above_threshold(api, second["id"], ctx["officer_headers"])
    submit_for_peer_review(
        api, second["id"], ctx["reviewer"]["id"], ctx["officer_headers"]
    )
    mark_claim_ready(api, second["id"], ctx["reviewer_headers"])
    ctx["second_claim_id"] = second["id"]
    return ctx


@pytest.fixture
def divergent_quarter(api):
    """
    One veteran, two claims filed inside 2026Q4, one granted and one denied,
    with a report opened once the quarter has closed.
    """
    set_clock(api, CLOCK_START_INSTANT)
    ctx = _two_claims_ready(api)
    set_clock_date(api, "2026-10-05", "09:00:00")
    file_claim(api, ctx["claim"]["id"], ctx["officer_headers"], "2026-10-05")
    file_claim(api, ctx["second_claim_id"], ctx["officer_headers"], "2026-10-05")
    set_clock_date(api, "2026-12-20", "09:00:00")
    granted = record_decision(
        api,
        ctx["claim"]["id"],
        ctx["officer_headers"],
        decision_outcome="GRANTED",
        awarded_rating_pct=70,
        decided_on="2026-12-20",
    )
    denied = record_decision(
        api,
        ctx["second_claim_id"],
        ctx["officer_headers"],
        decision_outcome="DENIED",
        awarded_rating_pct=0,
        decided_on="2026-12-20",
    )
    set_clock_date(api, "2027-01-05", "09:00:00")
    report = open_outcome_report(api, ctx["officer_headers"], "2026Q4")
    return {
        "officer_headers": ctx["officer_headers"],
        "report_id": report["id"],
        "granted": granted,
        "denied": denied,
    }


@pytest.fixture
def april_filed_claim(api):
    """
    A single claim filed on 1 April 2026 and never decided, with reports opened
    for the quarter that ends the day before and for the quarter that holds it.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    ctx = create_claim_ready_to_file(
        api,
        create_represented_veteran(api, designee=preparer),
        reviewer=reviewer,
        claimed_conditions=conditions("tinnitus"),
    )
    filed = file_claim(api, ctx["claim"]["id"], ctx["officer_headers"], "2026-04-01")
    first_quarter = open_outcome_report(api, ctx["officer_headers"], "2026Q1")
    second_quarter = open_outcome_report(api, ctx["officer_headers"], "2026Q2")
    return {
        "officer_headers": ctx["officer_headers"],
        "claim_id": filed["id"],
        "q1_id": first_quarter["id"],
        "q2_id": second_quarter["id"],
    }


class TestWeightingBasisDivergence:
    """The identical row set scores 50.0 one way and 100.0 the other."""

    def test_claim_weighting_counts_each_claim_once(self, api, divergent_quarter):
        """
        "Under `CLAIM_WEIGHTED`, the score is `favorable_claim_count` divided by `filed_claim_count`, multiplied by 100 — every claim counts once, so a veteran with several claims in the window moves the score several times."

        Design: Difficulty/dual_variant_calc/performance_score_claim_weighted_versus_veteran_weighted_divergence
        """
        scored = validate_success(
            api.compute_outcome_report(
                divergent_quarter["report_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                divergent_quarter["officer_headers"],
            ),
            200,
        )
        assert_pct_1dp(scored["performance_score"], 50.0)
        assert_exact_whole(scored["filed_claim_count"], 2, "filed_claim_count")
        assert_exact_whole(scored["favorable_claim_count"], 1, "favorable_claim_count")

    def test_veteran_weighting_counts_the_single_veteran_once(
        self, api, divergent_quarter
    ):
        """
        "Under `VETERAN_WEIGHTED`, count the distinct `veteran_id` values appearing in the favourable subset, divide by the number of distinct `veteran_id` values appearing in the whole window set, and multiply by 100 — each veteran counts once however many claims they filed."
        "The same rows can therefore yield very different scores: a veteran with one granted and one denied claim scores 50.0 under claim weighting and 100.0 under veteran weighting."

        Design: Difficulty/dual_variant_calc/performance_score_claim_weighted_versus_veteran_weighted_divergence
        """
        validate_success(
            api.compute_outcome_report(
                divergent_quarter["report_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                divergent_quarter["officer_headers"],
            ),
            200,
        )
        scored = validate_success(
            api.compute_outcome_report(
                divergent_quarter["report_id"],
                compute_report_payload("VETERAN_WEIGHTED"),
                divergent_quarter["officer_headers"],
            ),
            200,
        )
        assert_pct_1dp(scored["performance_score"], 100.0)
        assert scored["weighting_basis"] == "VETERAN_WEIGHTED"
        assert scored["status"] == "OPEN"
        assert_exact_whole(scored["filed_claim_count"], 2, "filed_claim_count")
        assert_exact_whole(scored["favorable_claim_count"], 1, "favorable_claim_count")

    def test_the_retroactive_dollars_come_from_the_favourable_subset_only(
        self, api, divergent_quarter
    ):
        """
        "`retro_dollars_cents` is the sum of `retro_award_cents` over the favourable subset."
        "A `DENIED` decision carries a rating of 0, so its monthly rate is 0 and its `retro_award_cents` is 0."

        Design: Difficulty/dual_variant_calc/performance_score_claim_weighted_versus_veteran_weighted_divergence
        """
        assert_cents(divergent_quarter["granted"]["retro_award_cents"], 384600)
        assert_cents(divergent_quarter["denied"]["retro_award_cents"], 0)
        scored = validate_success(
            api.compute_outcome_report(
                divergent_quarter["report_id"],
                compute_report_payload("VETERAN_WEIGHTED"),
                divergent_quarter["officer_headers"],
            ),
            200,
        )
        assert_cents(scored["retro_dollars_cents"], 384600)

    def test_an_office_with_no_held_outreach_contacts_nobody(
        self, api, divergent_quarter
    ):
        """
        "`veterans_contacted_total` is the sum of `veterans_contacted` over every outreach event whose `status` is `HELD` and whose `starts_at` date falls inside the same interval"
        — and no event of any status exists here.

        Design: Difficulty/dual_variant_calc/performance_score_claim_weighted_versus_veteran_weighted_divergence
        """
        scored = validate_success(
            api.compute_outcome_report(
                divergent_quarter["report_id"],
                compute_report_payload("VETERAN_WEIGHTED"),
                divergent_quarter["officer_headers"],
            ),
            200,
        )
        assert_exact_whole(
            scored["veterans_contacted_total"], 0, "veterans_contacted_total"
        )


class TestEmptyReportingWindowIsScored:
    """A quarter holding no filed claim scores zero instead of failing."""

    def test_the_empty_window_returns_a_score_rather_than_an_error(
        self, api, april_filed_claim
    ):
        """
        "When `filed_claim_count` is 0 the score is 0.0: an empty reporting window is a scored outcome, not an error."

        Design: Difficulty/boundary_precision_check/quarter_with_no_filed_claims_scores_empty_set_value_not_an_error
        """
        scored = validate_success(
            api.compute_outcome_report(
                april_filed_claim["q1_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                april_filed_claim["officer_headers"],
            ),
            200,
        )
        assert_exact_whole(scored["filed_claim_count"], 0, "filed_claim_count")
        assert_pct_1dp(scored["performance_score"], 0.0)
        assert scored["weighting_basis"] == "CLAIM_WEIGHTED"

    def test_the_empty_window_reports_no_favourable_claims_and_no_dollars(
        self, api, april_filed_claim
    ):
        """
        "The favourable subset is those members whose `status` is `DECIDED` and whose `decision_outcome` is `GRANTED` or `PARTIAL_GRANT`, and `favorable_claim_count` is its size."

        Design: Difficulty/boundary_precision_check/quarter_with_no_filed_claims_scores_empty_set_value_not_an_error
        """
        scored = validate_success(
            api.compute_outcome_report(
                april_filed_claim["q1_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                april_filed_claim["officer_headers"],
            ),
            200,
        )
        assert_exact_whole(scored["favorable_claim_count"], 0, "favorable_claim_count")
        assert_cents(scored["retro_dollars_cents"], 0)

    def test_the_first_of_april_belongs_to_the_second_quarter(
        self, api, april_filed_claim
    ):
        """
        "The label expands to a closed calendar-date interval: a first quarter spans 1 January through 31 March of the labelled year, a second 1 April through 30 June, a third 1 July through 30 September, and a fourth 1 October through 31 December."
        "The claim set for the window is every claim whose `filed_on` falls inside that closed interval."

        Design: Difficulty/boundary_precision_check/quarter_with_no_filed_claims_scores_empty_set_value_not_an_error
        """
        claim = read_claim(api, april_filed_claim["claim_id"])
        assert claim["filed_on"] == "2026-04-01"
        scored = validate_success(
            api.compute_outcome_report(
                april_filed_claim["q2_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                april_filed_claim["officer_headers"],
            ),
            200,
        )
        assert_exact_whole(scored["filed_claim_count"], 1, "filed_claim_count")

    def test_a_claim_awaiting_decision_scores_zero_in_its_own_quarter(
        self, api, april_filed_claim
    ):
        """
        "a claim filed inside the window but still awaiting a decision counts in the denominator only"

        Design: Difficulty/boundary_precision_check/quarter_with_no_filed_claims_scores_empty_set_value_not_an_error
        """
        scored = validate_success(
            api.compute_outcome_report(
                april_filed_claim["q2_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                april_filed_claim["officer_headers"],
            ),
            200,
        )
        assert_pct_1dp(scored["performance_score"], 0.0)
        assert_exact_whole(scored["favorable_claim_count"], 0, "favorable_claim_count")

"""Tenure eligibility boundaries and the rating-distribution report."""

import pytest

from test_helpers import (
    HR_RECOMMENDER_HEADERS,
    HR_RECOMMENDER_ID,
    TEST_USERS,
    create_cycle,
    create_educator,
    get_cycle,
    get_educator,
    setup_finalized_cycle,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]

TENURE_POLICY = {"required_formal_count": 1, "required_informal_count": 0,
                 "tenure_required_years": 3, "tenure_min_consecutive_effective": 1,
                 "evidence_min_artifacts": 2}


class TestTenureServiceYearBoundary:
    """Exactly 1095 days of service is exactly three completed years."""

    @staticmethod
    def _educator_at_exactly_three_years():
        return setup_finalized_cycle(
            clock="2026-08-01T00:00:00Z",
            policy_overrides=dict(TENURE_POLICY),
            educator_overrides={"employee_number": "E-9501",
                                "service_start_date": "2023-08-02"},
            formal_scores=(3, 3, 4, 3), artifacts=2,
            growth_index=3.00, growth_coverage=100,
        )

    def test_educator_at_exactly_the_required_service_years_is_recommended(self, api):
        """PRD §3.9: "An educator is eligible for a tenure recommendation when
        `completed_service_years` is at or above the policy's
        `tenure_required_years`, `consecutive_effective_years` is at or above the
        policy's `tenure_min_consecutive_effective`, and `tenure_track_hold` is
        false. Both numeric comparisons are inclusive, so an educator sitting at
        exactly the required number of years qualifies."
        PRD §3.9: "A `RECOMMEND` moves `tenure_status` from `PROBATIONARY` to
        `RECOMMENDED` and stamps the acting operator's `X-User-ID` onto
        `tenure_recommended_by_user_id`; it is refused with
        `ERR_TENURE_NOT_ELIGIBLE` when any of the three eligibility conditions
        fails — insufficient service years, an insufficient run of effective
        ratings, or a live improvement-plan hold."

        Design: Difficulty/boundary_precision_check/tenure_at_exactly_required_service_years_is_eligible
        """
        ctx = self._educator_at_exactly_three_years()

        recommended = validate_success(
            api.tenure_recommendation(ctx["educator"]["id"],
                                      {"recommendation": "RECOMMEND"},
                                      HR_RECOMMENDER_HEADERS)
        )
        assert recommended["tenure_status"] == "RECOMMENDED"
        assert recommended["tenure_recommended_by_user_id"] == HR_RECOMMENDER_ID

    def test_the_three_eligibility_quantities_are_computed_against_the_clock(self, api):
        """PRD §3.9: "`completed_service_years` is the number of whole days from
        the educator's `service_start_date` to the logical clock's current date,
        divided by 365 and rounded down to a whole number — so an educator who
        started on 2 August 2023, read against a clock at 1 August 2026, has
        accumulated 1095 days and therefore 3 completed service years, while the
        same educator read one day earlier has 1094 days and therefore 2."
        PRD §3.9: "`consecutive_effective_years` is the length of the trailing run
        of that history whose `composite_rating` is `EFFECTIVE` or
        `HIGHLY_EFFECTIVE`, counted backwards from the most recent entry and
        stopping at the first entry that is neither."
        PRD §3.7: "While any plan of an educator sits at `ACTIVE` or `EXTENDED`,
        that educator's `tenure_track_hold` reads true, and tenure progression is
        frozen."

        Design: Difficulty/boundary_precision_check/tenure_at_exactly_required_service_years_is_eligible
        """
        ctx = self._educator_at_exactly_three_years()
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["composite_score"] == pytest.approx(3.20)
        assert cycle["composite_rating"] == "EFFECTIVE"

        educator = get_educator(ctx["educator"]["id"])
        assert educator["completed_service_years"] == 3
        assert educator["consecutive_effective_years"] == 1
        assert educator["tenure_track_hold"] is False
        assert educator["last_composite_rating"] == "EFFECTIVE"


def test_rating_distribution_over_an_empty_population(api):
    """PRD §3.9: "An empty population is reported as `total_count` of 0, four
    percentages of 0.00, and an `outlier_flag` of false rather than as an error."
    PRD §3.9: "The population is every cycle whose `status` is `FINALIZED` or
    `CLOSED` with the requested `school_year`, further restricted to cycles whose
    educator belongs to the named building when one is supplied."

    Design: Corner/calculations/rating_distribution_over_empty_population_returns_zero_percentages
    """
    response = api.get_rating_distribution(HR, params={"school_year": "2030-2031"})
    report = validate_success(response, 200)

    assert report["total_count"] == 0
    assert report["ineffective_count"] == 0
    assert report["developing_count"] == 0
    assert report["effective_count"] == 0
    assert report["highly_effective_count"] == 0
    assert report["ineffective_pct"] == pytest.approx(0.00)
    assert report["developing_pct"] == pytest.approx(0.00)
    assert report["effective_pct"] == pytest.approx(0.00)
    assert report["highly_effective_pct"] == pytest.approx(0.00)
    assert report["outlier_flag"] is False


def test_rating_distribution_counts_only_finalized_cycles(api):
    """PRD §3.9: "The population is every cycle whose `status` is `FINALIZED` or
    `CLOSED` with the requested `school_year`, further restricted to cycles whose
    educator belongs to the named building when one is supplied."
    PRD §3.9: "Cycles still carrying a provisional composite are excluded, so a
    `SUBMITTED` cycle never appears."
    PRD §3.9: "Each percentage is that count multiplied by 100 and divided by
    `total_count`, rounded half-up to two decimal places."
    PRD §3.9: "Otherwise `outlier_flag` is true exactly when
    `highly_effective_pct` is strictly greater than 35.00 — a district flagging
    more than thirty-five percent of its finalized cycles as highly effective is an
    outlier under state guidance, and a figure of exactly 35.00 is not flagged."

    Design: Corner/calculations/rating_distribution_counts_only_finalized_cycles_of_the_requested_year
    """
    ctx = setup_finalized_cycle(
        policy_overrides={"required_formal_count": 1, "required_informal_count": 0,
                          "evidence_min_artifacts": 2},
        educator_overrides={"employee_number": "E-F201", "full_name": "Pia Voss"},
        formal_scores=(3, 3, 4, 3), artifacts=2,
        growth_index=3.00, growth_coverage=100,
    )
    other_educator = create_educator(ctx["school"]["id"], employee_number="E-F202",
                                     full_name="Quin Ade")
    unfinished = create_cycle(other_educator["id"], ctx["policy"]["id"])

    assert ctx["cycle"]["composite_score"] == pytest.approx(3.20)
    assert ctx["cycle"]["composite_rating"] == "EFFECTIVE"
    assert get_cycle(unfinished["id"])["status"] == "SCHEDULING"

    report = validate_success(
        api.get_rating_distribution(HR, params={"school_year": "2026-2027",
                                                "school_id": ctx["school"]["id"]})
    )

    assert report["total_count"] == 1, "the SCHEDULING cycle is not in the population"
    assert report["effective_count"] == 1
    assert report["effective_pct"] == pytest.approx(100.00)
    assert report["highly_effective_count"] == 0
    assert report["highly_effective_pct"] == pytest.approx(0.00)
    assert report["ineffective_pct"] == pytest.approx(0.00)
    assert report["developing_pct"] == pytest.approx(0.00)
    assert report["outlier_flag"] is False

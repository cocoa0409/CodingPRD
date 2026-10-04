"""First-destination outcome reporting: populations, denominators, and the
pinned nested rounding order."""
import pytest

from test_helpers import (
    assert_outcome_report,
    make_career_center_admin_headers,
    setup_eleven_alumni_university,
    validate_success,
)
from test_helpers.fixtures import _add_alumnus


class TestOutcomeReportDenominators:
    def test_counts_alumni_respondents_placed(self, api):
        """PRD §3.9: "The report aggregates over the university's `ALUMNUS` students
        only — `ENROLLED` and `WITHDRAWN` students are excluded — and returns
        `alumni_count`, `respondents_count`, `placed_count`, `placement_rate_cohort`,
        `placement_rate_respondent`, and the per-major breakdown `per_major`."
        PRD §3.9: "The respondents are those alumni whose `outcome_status` is no longer
        `UNREPORTED`. The placed are the respondents whose `outcome_status` is
        `EMPLOYED` or `GRAD_SCHOOL` — the `SEEKING` and `OTHER` outcomes count as
        reported but not placed."

        Design: Difficulty/dual_variant_calc/outcome_rates_respondent_vs_cohort_denominators
        """
        university = setup_eleven_alumni_university()
        report = validate_success(
            api.get_outcome_report(
                university["id"], make_career_center_admin_headers(university["id"])
            ),
            200,
        )
        assert_outcome_report(report)
        # CS x4 (EMPLOYED, SEEKING, OTHER, UNREPORTED); BIO x7 (EMPLOYED x3,
        # GRAD_SCHOOL x2, SEEKING, UNREPORTED).
        assert report["alumni_count"] == 11
        assert report["respondents_count"] == 9
        assert report["placed_count"] == 6

    def test_placement_rates_use_distinct_denominators(self, api):
        """PRD §3.9: "`placement_rate_cohort` is the total placed divided by the total
        alumni — including alumni who never reported — rounded half-up to 4 decimal
        places."
        PRD §3.9: "Because its denominator includes non-respondents while sharing the
        same numerator, the cohort rate is lower than or equal to the respondent rate
        on identical data."

        Design: Difficulty/dual_variant_calc/outcome_rates_respondent_vs_cohort_denominators
        """
        university = setup_eleven_alumni_university()
        report = validate_success(
            api.get_outcome_report(
                university["id"], make_career_center_admin_headers(university["id"])
            ),
            200,
        )
        # Respondent denominator: round_half_up of the pinned nested computation.
        assert report["placement_rate_respondent"] == pytest.approx(0.6666, abs=1e-9)
        # Cohort denominator: round_half_up(6 / 11, 4) = 0.5455.
        assert report["placement_rate_cohort"] == pytest.approx(0.5455, abs=1e-9)
        # Identical underlying data, different denominators -> different rates.
        assert report["placement_rate_respondent"] > report["placement_rate_cohort"]


class TestOutcomeReportRoundingOrder:
    def test_respondent_rate_uses_nested_rounding_order(self, api):
        """PRD §3.9: "first, for each distinct `major` among the respondents (the
        `per_major` entries are sorted by major in ascending order, and a major with
        zero respondents contributes no entry), compute that major's placed count
        divided by its respondent count and round the result half-up to 4 decimal
        places; then take the respondent-weighted mean of those already-rounded
        per-major rates — weighting each rounded rate by its major's respondent count,
        dividing by the total respondents — and round that final result half-up to 4
        decimal places."
        PRD §3.9: "Computing the respondent rate from raw totals and rounding only once
        is the rejected alternative: it yields a different fourth decimal."

        Design: Difficulty/combinatorial_formula/outcome_report_per_major_rounding_order
        """
        university = setup_eleven_alumni_university()
        report = validate_success(
            api.get_outcome_report(
                university["id"], make_career_center_admin_headers(university["id"])
            ),
            200,
        )
        # Pinned order: CS 1/3 -> 0.3333 and BIO 5/6 -> 0.8333 rounded FIRST, then
        # (0.3333*3 + 0.8333*6) / 9 = 5.9997 / 9 -> 0.6666.
        assert report["placement_rate_respondent"] == pytest.approx(0.6666, abs=1e-9)
        # The rejected raw-totals order: round_half_up(6 / 9, 4) = 0.6667.
        assert abs(report["placement_rate_respondent"] - 0.6667) > 1e-6, (
            "raw-totals-then-round yields 0.6667 and is the rejected alternative order"
        )

    def test_per_major_sorted_and_zero_respondent_major_excluded(self, api):
        """PRD §3.9: "the `per_major` entries are sorted by major in ascending order,
        and a major with zero respondents contributes no entry"

        Design: Difficulty/combinatorial_formula/outcome_report_per_major_rounding_order
        """
        university = setup_eleven_alumni_university()
        # A MATH alumnus who never reported: zero respondents -> no per_major entry.
        _add_alumnus(university["id"], "math1@stateu.edu", "Math One", "MATH")
        report = validate_success(
            api.get_outcome_report(
                university["id"], make_career_center_admin_headers(university["id"])
            ),
            200,
        )
        assert report["alumni_count"] == 12
        assert report["respondents_count"] == 9
        assert report["placed_count"] == 6
        # Cohort denominator now includes the UNREPORTED MATH alumnus: 6 / 12 = 0.5.
        assert report["placement_rate_cohort"] == pytest.approx(0.5, abs=1e-9)
        # Respondent rate is unchanged by the zero-respondent major.
        assert report["placement_rate_respondent"] == pytest.approx(0.6666, abs=1e-9)
        assert len(report["per_major"]) == 2, (
            "MATH has zero respondents and must contribute no per_major entry"
        )
        majors = []
        for entry in report["per_major"]:
            hits = [v for v in entry.values()
                    if isinstance(v, str) and v in {"BIO", "CS", "MATH"}]
            assert len(hits) == 1, "each per_major entry must identify its major"
            majors.append(hits[0])
        assert majors == ["BIO", "CS"], "per_major entries must be sorted major ASC"

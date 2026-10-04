"""Difficulty probe — dual_variant_calc: two PRD-sanctioned algorithms over the
same domain data yielding different totals (experience months: cumulative vs
interval-merged; CE standing: calendar-year vs trailing-365-day)."""
from test_helpers import (
    OVERLAPPING_QUALIFYING_SEGMENTS,
    add_reference,
    api_client,
    ce_record_payload,
    compute_ce_credit_totals,
    compute_committee_months,
    compute_provisional_months,
    create_candidate,
    create_experience_submission,
    get_membership,
    review_submission,
    set_logical_clock,
    setup_active_membership,
    submit_submission,
    validate_success,
    verify_reference,
)

CLOCK = "2027-01-05T00:00:00Z"

CE_RECORDS = [
    {"activity_title": "Ethics webinar", "credit_hours": 5, "completed_on": "2026-12-20"},
    {"activity_title": "Fixed income seminar", "credit_hours": 15, "completed_on": "2027-03-10"},
    {"activity_title": "Derivatives workshop", "credit_hours": 6, "completed_on": "2027-08-19"},
]


def _submission_with_verified_references(candidate):
    """DRAFT submission holding the canonical overlapping segment pair, with
    two references already VERIFIED so the APPROVED review path is open."""
    submission = create_experience_submission(
        candidate, segments=OVERLAPPING_QUALIFYING_SEGMENTS
    )
    ref1 = add_reference(
        submission, candidate, referee_name="Ref One", referee_email="ref1@example.com"
    )
    ref2 = add_reference(
        submission, candidate, referee_name="Ref Two", referee_email="ref2@example.com"
    )
    verify_reference(ref1)
    verify_reference(ref2)
    return submission


def _membership_with_ce_records():
    """ACTIVE membership (charterholder, dues 27500, 20 CE credits required)
    observed at clock 2027-08-20, carrying the three canonical CE records."""
    context = setup_active_membership()
    set_logical_clock("2027-08-20T00:00:00Z")
    membership = context["membership"]
    for record in CE_RECORDS:
        resp = api_client.append_ce_record(
            membership["id"], ce_record_payload(**record), context["candidate_headers"]
        )
        validate_success(resp, 200)
    return context


class TestExperienceMonthsVariants:
    def test_experience_provisional_months_double_count_overlaps(self, api):
        """PRD §3.6: "At submission time the system computes
        `provisional_months`, the **cumulative** variant of the experience
        figure: among the qualifying segments — those whose
        `qualifying_activity_pct` is at least 50 — the whole-calendar-month
        length of each segment (per the convention of §2.9) is summed, and
        overlapping periods are deliberately counted twice."
        PRD §3.6: "The first measures twenty-four months and the second
        twenty-three, so `provisional_months` reports forty-seven"

        Design: Difficulty/dual_variant_calc/experience_months_cumulative_vs_contiguous_diverge
        """
        assert compute_provisional_months(OVERLAPPING_QUALIFYING_SEGMENTS) == 47
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        submission = _submission_with_verified_references(candidate)
        submitted = submit_submission(submission, candidate)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["provisional_months"] == 47

    def test_experience_committee_months_merge_overlaps(self, api):
        """PRD §3.6: "On approval or rejection the system computes and stores
        `committee_months`, the **contiguous** variant: the qualifying segments
        are sorted by `start_date` — ties broken by earlier `end_date`, then by
        the segment's order in the array — and merged into runs wherever the
        next segment starts on or before one day after the current run's end, so
        that touching periods count as contiguous; the whole-month lengths of
        the merged runs are then summed, counting every overlap only once."
        PRD §3.6: "interval-merged into a single run from the tenth of January
        2022 to the tenth of June 2025, `committee_months` reports forty-one."

        Design: Difficulty/dual_variant_calc/experience_months_cumulative_vs_contiguous_diverge
        """
        assert compute_committee_months(OVERLAPPING_QUALIFYING_SEGMENTS) == 41
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        submission = _submission_with_verified_references(candidate)
        submitted = submit_submission(submission, candidate)
        approved = review_submission(submitted, decision="APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["committee_months"] == 41
        assert submitted["provisional_months"] - approved["committee_months"] == 6


class TestCeStandingVariants:
    def test_ce_calendar_year_credits_exclude_prior_year(self, api):
        """PRD §3.9: "`calendar_year_credits` sums the `credit_hours` of records
        whose `completed_on` falls within the logical clock's current calendar
        year, first of January through thirty-first of December inclusive."
        PRD §3.9: "The standing flag `ce_standing_met` is true exactly when
        `calendar_year_credits` reaches at least the society's
        `ce_credits_required_per_year`."

        Design: Difficulty/dual_variant_calc/ce_standing_calendar_vs_rolling_diverge
        """
        calendar, _ = compute_ce_credit_totals(CE_RECORDS, "2027-08-20")
        assert calendar == 21
        context = _membership_with_ce_records()
        membership = get_membership(context["membership"]["id"])
        assert membership["calendar_year_credits"] == 21
        assert membership["ce_standing_met"] is True

    def test_ce_rolling_12m_credits_span_year_boundary(self, api):
        """PRD §3.9: "`rolling_12m_credits` sums records whose `completed_on`
        lies strictly after the date 365 days before the current date — the
        trailing 365 days, today included."

        Design: Difficulty/dual_variant_calc/ce_standing_calendar_vs_rolling_diverge
        """
        calendar, rolling = compute_ce_credit_totals(CE_RECORDS, "2027-08-20")
        assert (calendar, rolling) == (21, 26)
        context = _membership_with_ce_records()
        membership = get_membership(context["membership"]["id"])
        assert membership["rolling_12m_credits"] == 26
        assert membership["rolling_12m_credits"] != membership["calendar_year_credits"]

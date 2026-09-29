"""Non-linear paths: a bounded self-loop and a reversal of a terminal-looking state.

The petition may cycle SUBMITTED to RFE_RECEIVED and back, but only twice; a
sustained grievance reverses a finalized non-renewal and drags the appointment
back out of NON_RENEWED.
"""

from test_helpers import (
    ApiErrorId,
    adjudicate,
    api_client,
    assert_award_ledger,
    assert_timestamp_equals,
    file_grievance,
    latest_visa_case,
    read_funding_source,
    read_postdoc,
    resolve_grievance,
    set_clock,
    setup_finalized_non_renewed,
    setup_visa_submitted,
    submit_petition,
    validate_error,
    validate_success,
)

_LOOP_POSTDOC = {
    "full_name": "Devi Iyer",
    "citizenship_country": "IN",
    "phd_award_date": "2026-05-20",
    "prior_external_months_in_rank": 0,
    "j1_two_year_bar_flag": False,
}
_LOOP_MENTOR = {
    "full_name": "T. Nakamura",
    "department": "Immunology",
    "mentor_training_valid_through": "2029-05-31",
    "max_concurrent_postdocs": 3,
}
_LOOP_AWARD = {
    "sponsor_name": "NIH R01 AI-330",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}
_LOOP_TERM = {
    "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _filed_case():
    """A sponsored J1 case that has been filed once, so it sits in SUBMITTED."""
    return setup_visa_submitted(
        appointment_overrides=dict(_LOOP_TERM),
        postdoc_overrides=dict(_LOOP_POSTDOC),
        processing_track="STANDARD",
        filed_at="2026-08-05T09:00:00Z",
        mentor_overrides=dict(_LOOP_MENTOR),
        funding_overrides=dict(_LOOP_AWARD),
    )


def test_the_round_counter_moves_on_the_refiling_not_on_the_evidence_request():
    """`rfe_round_count` is increased by the filing, not by the RFE record.

    PRD 3.4: "A filing that moves it `RFE_RECEIVED` → `SUBMITTED` sets
    `projection_variant` to `POST_RFE_REFILING` and additionally increases
    `rfe_round_count` by 1" while "An `RFE` outcome moves the case `SUBMITTED` →
    `RFE_RECEIVED` and requires `rfe_round_count` to be strictly below 2".

    Design: Difficulty/non_linear_state_machine/visa_rfe_self_loop_bounded_by_rfe_round_limit
    """
    scenario = _filed_case()
    case_id = scenario.visa_case["id"]

    after_rfe = adjudicate(case_id, "RFE", "RFE round 1")
    assert after_rfe["status"] == "RFE_RECEIVED"
    assert after_rfe["rfe_round_count"] == 0, (
        f"Expected the counter to stay at 0 until the response is filed, "
        f"got {after_rfe['rfe_round_count']}"
    )

    refiled = submit_petition(case_id)
    assert refiled["status"] == "SUBMITTED"
    assert refiled["rfe_round_count"] == 1
    assert refiled["projection_variant"] == "POST_RFE_REFILING"


def test_the_evidence_loop_may_be_traversed_twice():
    """Two full SUBMITTED to RFE_RECEIVED to SUBMITTED traversals are permitted.

    PRD 3.4: "the same capability serves both the first filing and every
    re-filing after a request for evidence" and the loop is bounded because a
    re-filing "is permitted only while `rfe_round_count` is strictly below 2".

    Design: Difficulty/non_linear_state_machine/visa_rfe_self_loop_bounded_by_rfe_round_limit
    """
    scenario = _filed_case()
    case_id = scenario.visa_case["id"]

    adjudicate(case_id, "RFE", "RFE round 1")
    submit_petition(case_id)
    second_rfe = adjudicate(case_id, "RFE", "RFE round 2")
    after_second_refiling = submit_petition(case_id)

    assert second_rfe["status"] == "RFE_RECEIVED"
    assert after_second_refiling["status"] == "SUBMITTED"
    assert after_second_refiling["rfe_round_count"] == 2
    assert after_second_refiling["projection_variant"] == "POST_RFE_REFILING"


def test_a_third_request_for_evidence_is_refused_at_the_round_limit():
    """Once the counter reaches two the loop is closed and the case stays put.

    PRD 2.11 rule 18: "Request-for-evidence rounds: `rfe_round_count` must be
    strictly below 2 before another request for evidence may be recorded —
    `ERR_RFE_ROUND_LIMIT_REACHED` (409), on visa adjudication."

    Design: Difficulty/non_linear_state_machine/visa_rfe_self_loop_bounded_by_rfe_round_limit
    """
    scenario = _filed_case()
    case_id = scenario.visa_case["id"]

    adjudicate(case_id, "RFE", "RFE round 1")
    submit_petition(case_id)
    adjudicate(case_id, "RFE", "RFE round 2")
    submit_petition(case_id)

    response = api_client.record_adjudication(
        case_id, {"outcome": "RFE", "decision_note": "RFE round 3 attempt"},
        scenario.advisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_RFE_ROUND_LIMIT_REACHED.value, 409)

    unchanged = latest_visa_case(scenario.appointment_id)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["rfe_round_count"] == 2
    assert unchanged["projection_variant"] == "POST_RFE_REFILING"


# ─── The sustained grievance reverses a finalized non-renewal ───────────────

_REINSTATE_POSTDOC = {
    "full_name": "Ruth Callahan",
    "citizenship_country": "US",
    "requires_sponsorship": False,
    "phd_award_date": "2026-04-15",
    "prior_external_months_in_rank": 0,
}
_REINSTATE_MENTOR = {
    "full_name": "P. Ferreira",
    "department": "Genetics",
    "mentor_training_valid_through": "2029-08-31",
    "max_concurrent_postdocs": 3,
}
_REINSTATE_AWARD = {
    "sponsor_name": "NIH R01 HD-220",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}
_REINSTATE_TERM = {
    "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _non_renewed_appointment():
    """An ACTIVE appointment carried to FINALIZED_NON_RENEWED on 2027-05-01."""
    return setup_finalized_non_renewed(
        appointment_overrides=dict(_REINSTATE_TERM),
        review_clock="2027-05-01T00:00:00Z",
        postdoc_overrides=dict(_REINSTATE_POSTDOC),
        mentor_overrides=dict(_REINSTATE_MENTOR),
        funding_overrides=dict(_REINSTATE_AWARD),
    )


def test_the_non_renewal_branch_publishes_the_notice_entitlement():
    """A timely notice bands at 30 days and opens a 21-day grievance window.

    PRD 3.8: "The notice entitlement `notice_days_required` is banded on
    `service_months_at_review`: 30 days when service is 12 months or fewer, 60
    days when service is more than 12 but 36 months or fewer, and 90 days beyond
    that. `notice_deadline_date` is the appointment's `term_end_date` less
    `notice_days_required` days." "Finally, `grievance_window_end` is computed as
    the calendar date of `notice_issued_at` plus 21 days, clamped to the instant
    `23:59:59.999Z` on that date"

    Design: Difficulty/non_linear_state_machine/sustained_grievance_unterminalizes_non_renewal_and_reactivates_appointment
    """
    scenario = _non_renewed_appointment()
    review = scenario.review

    assert review["service_months_at_review"] == 8, (
        f"Expected service_months_at_review 8, "
        f"got {review['service_months_at_review']}"
    )
    assert review["notice_days_required"] == 30
    assert review["notice_deadline_date"] == "2027-08-31"
    assert review["notice_timely"] is True
    assert_timestamp_equals(review["grievance_window_end"],
                            "2027-05-22T23:59:59.999Z", "grievance_window_end")
    assert review["term_extension_days"] == 0


def test_a_sustained_grievance_returns_the_review_to_renewed(officer_alt_headers):
    """The review leaves a state the pipeline presents as an endpoint.

    PRD 3.8: "A `SUSTAIN` moves the grievance `FILED` → `RESOLVED_SUSTAINED` and
    **undoes the non-renewal**" and "The review advances
    `FINALIZED_NON_RENEWED` → `FINALIZED_RENEWED`, and its `notice_issued_at`,
    `notice_timely` and `grievance_window_end` are all set back to null."

    Design: Difficulty/non_linear_state_machine/sustained_grievance_unterminalizes_non_renewal_and_reactivates_appointment
    """
    scenario = _non_renewed_appointment()
    review_id = scenario.review["id"]

    set_clock("2027-05-20T10:00:00Z", scenario.officer_headers)
    grievance = file_grievance(
        review_id, scenario.postdoc["id"], "PROCEDURAL",
        "The reappointment committee never met.",
    )
    set_clock("2027-05-21T10:00:00Z", scenario.officer_headers)

    resolved = resolve_grievance(
        grievance["id"], "SUSTAIN", officer_alt_headers,
        "Procedural defect confirmed; non-renewal vacated.",
    )
    assert resolved["status"] == "RESOLVED_SUSTAINED"

    review = validate_success(
        api_client.get_reappointment_review(review_id, scenario.officer_headers)
    )
    assert review["status"] == "FINALIZED_RENEWED"
    assert review["notice_issued_at"] is None
    assert review["notice_timely"] is None
    assert review["grievance_window_end"] is None


def test_a_sustained_grievance_reactivates_the_appointment_and_rewinds_the_ledger(
    officer_alt_headers,
):
    """The appointment returns to ACTIVE and the rank ledger returns to its
    pre-notice value.

    PRD 3.8: "The appointment then advances `NON_RENEWED` → `ACTIVE`" and "Step
    one debits the scholar's `total_months_in_rank` by the appointment's
    `term_months` — the exact value that was posted when the appointment became
    `NON_RENEWED`, which is why the debit must happen before the term is
    restored. Step two restores the appointment's `term_end_date` from the
    review's `pre_notice_term_end_date`" and "The appointment's
    `reinstated_count`, which starts at 0, increases by 1"

    Design: Difficulty/non_linear_state_machine/sustained_grievance_unterminalizes_non_renewal_and_reactivates_appointment
    """
    scenario = _non_renewed_appointment()

    set_clock("2027-05-20T10:00:00Z", scenario.officer_headers)
    grievance = file_grievance(
        scenario.review["id"], scenario.postdoc["id"], "PROCEDURAL",
        "The reappointment committee never met.",
    )
    set_clock("2027-05-21T10:00:00Z", scenario.officer_headers)
    resolve_grievance(
        grievance["id"], "SUSTAIN", officer_alt_headers,
        "Procedural defect confirmed; non-renewal vacated.",
    )

    appointment = scenario.refresh_appointment()
    assert appointment["appointment_status"] == "ACTIVE"
    assert appointment["reinstated_count"] == 1
    assert appointment["term_end_date"] == "2027-09-30"

    scholar = read_postdoc(scenario.postdoc["id"], scenario.officer_headers)
    assert scholar["total_months_in_rank"] == 0, (
        f"Expected the realized ledger to return to 0, "
        f"got {scholar['total_months_in_rank']}"
    )

    award = read_funding_source(scenario.funding_source["id"])
    assert_award_ledger(award, 90780.00, 309220.00)

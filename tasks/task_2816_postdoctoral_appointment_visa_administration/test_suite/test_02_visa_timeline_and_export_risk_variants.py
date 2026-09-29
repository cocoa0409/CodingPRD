"""Two calculations that each run in two variants.

The petition projection picks its variant from the state the case was filed
from; the research-security score picks its variant from the screening cycle
depth. In both cases identical inputs produce different published numbers.
"""

from test_helpers import (
    api_client,
    assert_date_equals,
    assert_risk_score,
    decide_screening,
    finalize_review,
    latest_visa_case,
    queued_screening_cycle,
    set_clock,
    setup_active_appointment,
    setup_review_recommended,
    setup_visa_submitted,
    submit_petition_payload,
    validate_success,
)

# The scholar, mentor and award behind the sponsorship projection tests.
_SPONSORED_POSTDOC = {
    "full_name": "Ana Ruiz",
    "citizenship_country": "IN",
    "phd_award_date": "2026-05-15",
    "prior_external_months_in_rank": 0,
    "o1_endorsement_on_file": False,
    "j1_two_year_bar_flag": False,
    "restricted_party_flag": False,
}
_SPONSORED_MENTOR = {
    "full_name": "R. Okafor",
    "department": "Molecular Biology",
    "mentor_training_valid_through": "2028-12-31",
    "max_concurrent_postdocs": 3,
}
_SPONSORED_AWARD = {
    "sponsor_name": "NIH R01 GM-118",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}
_SPONSORED_TERM = {
    "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _filed_standard_j1_case():
    """A sponsored appointment whose J1 petition was filed on 2026-08-05."""
    return setup_visa_submitted(
        appointment_overrides=dict(_SPONSORED_TERM),
        postdoc_overrides=dict(_SPONSORED_POSTDOC),
        processing_track="STANDARD",
        filed_at="2026-08-05T09:00:00Z",
        mentor_overrides=dict(_SPONSORED_MENTOR),
        funding_overrides=dict(_SPONSORED_AWARD),
    )


def test_initial_filing_projects_the_unextended_base_duration():
    """A first filing adds the bare category-and-track base to the filing date.

    PRD 3.4: "On the `STANDARD` track the base is 10 days for `TN`, 21 days for
    `J1_RESEARCH_SCHOLAR`, 120 days for `H1B` and 75 days for `O1`." "Under the
    `INITIAL_FILING` variant, `projected_decision_date` is the calendar date of
    `filed_at` plus that base number of days, with no extension applied." "In
    both variants `earliest_lawful_start_date` is `projected_decision_date` plus
    a further 10 days of activation lead time."

    Design: Difficulty/dual_variant_calc/visa_timeline_initial_filing_versus_post_rfe_refiling
    """
    scenario = _filed_standard_j1_case()
    case = scenario.visa_case

    assert case["visa_category"] == "J1_RESEARCH_SCHOLAR", (
        f"Expected the J1 selection for an Indian-citizen employee on a "
        f"12-month term, got {case['visa_category']}"
    )
    assert case["projection_variant"] == "INITIAL_FILING"
    assert_date_equals(case["projected_decision_date"], "2026-08-26",
                       "projected_decision_date")
    assert_date_equals(case["earliest_lawful_start_date"], "2026-09-05",
                       "earliest_lawful_start_date")
    assert case["status"] == "SUBMITTED"
    assert case["rfe_round_count"] == 0


def test_recording_a_request_for_evidence_leaves_both_projections_untouched():
    """The projections move only when the response is actually filed.

    PRD 3.4: "Recording the request for evidence deliberately leaves
    `projected_decision_date` and `earliest_lawful_start_date` untouched; they
    move only when the response is actually filed."

    Design: Difficulty/dual_variant_calc/visa_timeline_initial_filing_versus_post_rfe_refiling
    """
    scenario = _filed_standard_j1_case()
    filed = scenario.visa_case

    set_clock("2026-08-25T09:00:00Z", scenario.officer_headers)
    after_rfe = validate_success(
        api_client.record_adjudication(
            filed["id"],
            {"outcome": "RFE",
             "decision_note": "Request for evidence: proof of research-scholar status"},
            scenario.advisor_headers,
        )
    )

    assert after_rfe["status"] == "RFE_RECEIVED"
    assert_date_equals(after_rfe["projected_decision_date"], "2026-08-26",
                       "projected_decision_date")
    assert_date_equals(after_rfe["earliest_lawful_start_date"], "2026-09-05",
                       "earliest_lawful_start_date")


def test_post_rfe_refiling_projects_the_extended_duration():
    """The same case, same category and same track projects 32 days on re-filing.

    PRD 3.4: "Under the `POST_RFE_REFILING` variant, the base is first multiplied
    by 1.5 and rounded **up** to a whole number of days, and that extended count
    is added to the calendar date of `filed_at`." "Processing time that already
    elapsed before the request for evidence is **discarded, not credited**: for
    the same category and track the two variants project different dates from an
    identical filing instant"

    Design: Difficulty/dual_variant_calc/visa_timeline_initial_filing_versus_post_rfe_refiling
    """
    scenario = _filed_standard_j1_case()
    case_id = scenario.visa_case["id"]

    validate_success(
        api_client.record_adjudication(
            case_id,
            {"outcome": "RFE",
             "decision_note": "Request for evidence: proof of research-scholar status"},
            scenario.advisor_headers,
        )
    )
    set_clock("2026-08-25T09:00:00Z", scenario.officer_headers)
    refiled = validate_success(
        api_client.submit_petition(
            case_id, scenario.advisor_headers, submit_petition_payload("STANDARD")
        )
    )

    assert refiled["projection_variant"] == "POST_RFE_REFILING"
    assert_date_equals(refiled["projected_decision_date"], "2026-09-26",
                       "projected_decision_date")
    assert_date_equals(refiled["earliest_lawful_start_date"], "2026-10-06",
                       "earliest_lawful_start_date")
    assert refiled["rfe_round_count"] == 1
    assert refiled["status"] == "SUBMITTED"

    reread = latest_visa_case(scenario.appointment_id)
    assert reread["projection_variant"] == "POST_RFE_REFILING"
    assert_date_equals(reread["projected_decision_date"], "2026-09-26",
                       "projected_decision_date on re-read")


# ─── The two screening variants ────────────────────────────────────────────

_SCREENED_POSTDOC = {
    "full_name": "Wei Chen",
    "citizenship_country": "CN",
    "requires_sponsorship": False,
    "phd_award_date": "2026-04-01",
    "prior_external_months_in_rank": 0,
    "o1_endorsement_on_file": False,
    "j1_two_year_bar_flag": False,
    "restricted_party_flag": False,
}
_SCREENED_MENTOR = {
    "full_name": "L. Hartmann",
    "department": "Materials Science",
    "mentor_training_valid_through": "2029-06-30",
    "max_concurrent_postdocs": 3,
}
_SCREENED_AWARD = {
    "sponsor_name": "DOE BES-2211",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2029-12-31",
    "annual_budget_usd": 500000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}
_SCREENED_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2028-09-30",
    "annual_salary_usd": 62000.00,
}


def _appointment_screened_once():
    """An ACTIVE 24-month appointment whose cycle-1 screening attested to
    controlled technology and no restricted-party hit."""
    return setup_active_appointment(
        appointment_overrides=dict(_SCREENED_TERM),
        controlled_technology_flag=True,
        postdoc_overrides=dict(_SCREENED_POSTDOC),
        mentor_overrides=dict(_SCREENED_MENTOR),
        funding_overrides=dict(_SCREENED_AWARD),
    )


def _queued_second_cycle(scenario):
    """Finalize a renewal so the cascade queues a second screening cycle."""
    set_clock("2027-06-01T00:00:00Z", scenario.officer_headers)
    review = setup_review_recommended(scenario, "RENEW")
    scenario.review = finalize_review(
        review["id"], "RENEW", scenario.officer_headers
    )
    return queued_screening_cycle(scenario.appointment_id)


def test_first_screening_cycle_scores_under_the_standard_tier():
    """Cycle 1 with a sub-3.0 country factor stays on the standard variant.

    PRD 3.6: "The tier is `TIER_2_ENHANCED` when any one of three conditions
    holds: the cycle's `cycle_index` is 2 or greater, or `restricted_party_hit`
    is true, or `controlled_technology_flag` is true and the scholar's country
    factor is 3.0 or greater. Otherwise the tier is `TIER_1_STANDARD`." "The
    country component is the country factor multiplied by the tier's country
    weight, 12.5 or 15.0." "Otherwise a `risk_score` of 35.0 or above is
    `CLEARED_WITH_CONDITIONS`."

    Design: Difficulty/dual_variant_calc/export_risk_tier1_standard_versus_tier2_enhanced
    """
    scenario = _appointment_screened_once()
    cycle_one = scenario.screening

    assert cycle_one["screening_tier"] == "TIER_1_STANDARD"
    assert_risk_score(cycle_one["risk_score"], 56.3)
    assert cycle_one["status"] == "CLEARED_WITH_CONDITIONS"
    assert scenario.refresh_appointment()["compliance_status"] == "RESTRICTED"


def test_re_screen_cycle_scores_under_the_enhanced_tier():
    """Byte-identical findings on cycle 2 are scored on the enhanced variant.

    PRD 3.6: "the country component is weighted 12.5 under `TIER_1_STANDARD` and
    15.0 under `TIER_2_ENHANCED`, and the term-duration component is omitted
    entirely under `TIER_1_STANDARD` while it is added under `TIER_2_ENHANCED`."
    "The duration component, present only under `TIER_2_ENHANCED`, is the
    appointment's `term_months` divided by twelve and then multiplied by 3.125"

    Design: Difficulty/dual_variant_calc/export_risk_tier1_standard_versus_tier2_enhanced
    """
    scenario = _appointment_screened_once()
    cycle_two = _queued_second_cycle(scenario)

    assert cycle_two["cycle_index"] == 2, (
        f"Expected the re-screen to be cycle 2, got {cycle_two['cycle_index']}"
    )

    decided = decide_screening(
        cycle_two["id"], restricted_party_hit=False, controlled_technology_flag=True
    )

    assert decided["screening_tier"] == "TIER_2_ENHANCED"
    assert_risk_score(decided["risk_score"], 68.8)
    assert decided["status"] == "DENIED"


def test_the_enhanced_variant_adds_twelve_and_a_half_points_and_flips_the_outcome():
    """The variant switch alone moves the score across the denial threshold.

    PRD 3.6: "For identical reviewer findings the two variants can therefore
    return different scores and even different outcomes." "Otherwise a
    `risk_score` of 60.0 or above is `DENIED`." "It drives `compliance_status`
    `PENDING_REVIEW` → `BLOCKED`" and "if the appointment's `appointment_status`
    is `ACTIVE` at that moment, it advances `ACTIVE` → `TERMINATED`."

    Design: Difficulty/dual_variant_calc/export_risk_tier1_standard_versus_tier2_enhanced
    """
    scenario = _appointment_screened_once()
    first_score = scenario.screening["risk_score"]

    cycle_two = _queued_second_cycle(scenario)
    decided = decide_screening(
        cycle_two["id"], restricted_party_hit=False, controlled_technology_flag=True
    )

    assert round(decided["risk_score"] - first_score, 1) == 12.5, (
        f"Expected the enhanced variant to add 12.5 points, got "
        f"{decided['risk_score']} against {first_score}"
    )
    assert scenario.review["service_months_at_review"] == 9, (
        f"Expected service_months_at_review 9, "
        f"got {scenario.review['service_months_at_review']}"
    )

    appointment = scenario.refresh_appointment()
    assert appointment["compliance_status"] == "BLOCKED"
    assert appointment["appointment_status"] == "TERMINATED"

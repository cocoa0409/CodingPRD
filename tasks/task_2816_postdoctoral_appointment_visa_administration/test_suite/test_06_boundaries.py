"""Two inclusive boundaries, each probed on both sides.

An integer rank ceiling on appointment drafting, and a one-decimal risk score
landing exactly on the conditions threshold.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_money,
    assert_risk_score,
    create_appointment_payload,
    decide_screening,
    draft_appointment,
    issue_offer,
    make_officer_headers,
    queued_screening_cycle,
    read_appointment,
    register_faculty_mentor,
    register_funding_source,
    register_postdoc,
    setup_registries,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── The 60-month rank ceiling on POST /appointments ──────────────────────

_CAP_MENTOR = {
    "full_name": "T. Ferreira",
    "department": "Neuroscience",
    "mentor_training_valid_through": "2029-08-31",
    "max_concurrent_postdocs": 3,
}

_CAP_AWARD = {
    "sponsor_name": "NIH R35-1100",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_CAP_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 70000.00,
}


def _two_scholars_either_side_of_the_ceiling():
    """One scholar carrying 48 prior months in rank and one carrying 49, under a
    shared mentor and a shared VERIFIED award."""
    scenario = setup_registries(
        postdoc_overrides={
            "full_name": "Nadia Petrov",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2022-08-01",
            "prior_external_months_in_rank": 48,
        },
        mentor_overrides=_CAP_MENTOR,
        funding_overrides=_CAP_AWARD,
    )
    scholar_49 = register_postdoc(
        scenario.officer_headers, full_name="Omar Diallo", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2022-07-01",
        prior_external_months_in_rank=49,
    )
    return scenario, scholar_49


def test_a_cumulative_sixty_month_term_is_accepted_at_the_ceiling():
    """48 prior months plus a 12-month term lands on the inclusive ceiling.

    PRD 2.11 rule 15: "Total-years-in-rank ceiling:
    `cumulative_months_in_rank_at_end` must not exceed 60 months; the boundary
    value of exactly 60 is permitted and 61 is not — `ERR_RANK_YEARS_EXCEEDED`
    (422), on appointment drafting and on reappointment finalization."

    Design: Difficulty/boundary_precision_check/total_months_in_rank_cap_accepts_exactly_sixty_and_rejects_sixty_one
    """
    scenario, _ = _two_scholars_either_side_of_the_ceiling()

    response = api_client.create_appointment(
        create_appointment_payload(
            scenario.postdoc["id"], scenario.mentor["id"],
            scenario.funding_source["id"], **_CAP_TERM,
        ),
        scenario.officer_headers,
    )
    appointment = validate_success(response, expected_status=201)

    assert appointment["months_in_rank_at_start"] == 48, (
        "months_in_rank_at_start is the imported external count when no "
        f"predecessor exists, got {appointment['months_in_rank_at_start']}"
    )
    assert appointment["term_months"] == 12, (
        f"Expected term_months 12, got {appointment['term_months']}"
    )
    assert appointment["cumulative_months_in_rank_at_end"] == 60, (
        f"Expected cumulative_months_in_rank_at_end 60, "
        f"got {appointment['cumulative_months_in_rank_at_end']}"
    )
    assert_money(appointment["salary_floor_usd"], 67284.00, "salary_floor_usd")
    assert appointment["appointment_status"] == "DRAFT"


def test_one_month_past_the_ceiling_is_refused():
    """49 prior months plus the identical term reaches 61 and is refused.

    PRD 3.2: "`cumulative_months_in_rank_at_end` may not exceed 60 months — five
    years in rank across all institutions — and the boundary is inclusive, so
    exactly 60 is accepted and 61 is refused with `ERR_RANK_YEARS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/total_months_in_rank_cap_accepts_exactly_sixty_and_rejects_sixty_one
    """
    scenario, scholar_49 = _two_scholars_either_side_of_the_ceiling()

    response = api_client.create_appointment(
        create_appointment_payload(
            scholar_49["id"], scenario.mentor["id"],
            scenario.funding_source["id"], **_CAP_TERM,
        ),
        scenario.officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_RANK_YEARS_EXCEEDED.value, 422)


def test_the_refused_draft_leaves_the_scholar_with_no_appointment():
    """Only the accepted draft is persisted; the refused one leaves nothing.

    PRD 3.2: "`cumulative_months_in_rank_at_end` is `months_in_rank_at_start`
    plus this appointment's own `term_months`."

    Design: Difficulty/boundary_precision_check/total_months_in_rank_cap_accepts_exactly_sixty_and_rejects_sixty_one
    """
    scenario, scholar_49 = _two_scholars_either_side_of_the_ceiling()
    officer = scenario.officer_headers

    draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"],
        scenario.funding_source["id"], officer, **_CAP_TERM,
    )
    api_client.create_appointment(
        create_appointment_payload(
            scholar_49["id"], scenario.mentor["id"],
            scenario.funding_source["id"], **_CAP_TERM,
        ),
        officer,
    )

    _, over_cap_meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scholar_49["id"]})
    )
    assert over_cap_meta["total_count"] == 0, (
        f"Expected no appointment for the refused scholar, "
        f"got {over_cap_meta['total_count']}"
    )

    _, at_cap_meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scenario.postdoc["id"]})
    )
    assert at_cap_meta["total_count"] == 1, (
        f"Expected the accepted draft to persist, got {at_cap_meta['total_count']}"
    )


# ─── The 35.0 conditions threshold on a screening decision ────────────────

_RISK_MENTOR = {
    "full_name": "L. Grimaldi",
    "department": "Astronomy",
    "mentor_training_valid_through": "2029-10-31",
    "max_concurrent_postdocs": 3,
}

_EXTERNAL_AWARD = {
    "sponsor_name": "Banting Fellowship",
    "funding_type": "EXTERNAL_FELLOWSHIP",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_INSTITUTIONAL_AWARD = dict(
    _EXTERNAL_AWARD,
    sponsor_name="Provost Fellowship",
    funding_type="INSTITUTIONAL_FELLOWSHIP",
)

_FELLOWSHIP_TERM = {
    "title_classification": "POSTDOC_FELLOW",
    "employment_class": "FELLOWSHIP",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 60000.00,
}


def _two_queued_canadian_screenings():
    """Two Canadian fellows under one mentor, one on an EXTERNAL_FELLOWSHIP award
    and one on an INSTITUTIONAL_FELLOWSHIP award, each with a QUEUED cycle 1."""
    officer = make_officer_headers()
    mentor = register_faculty_mentor(officer, **_RISK_MENTOR)
    external_award = register_funding_source(headers=officer, **_EXTERNAL_AWARD)
    institutional_award = register_funding_source(headers=officer, **_INSTITUTIONAL_AWARD)

    scholar_one = register_postdoc(
        officer, full_name="Camille Roy", citizenship_country="CA",
        requires_sponsorship=False, phd_award_date="2026-05-01",
        prior_external_months_in_rank=0,
    )
    scholar_two = register_postdoc(
        officer, full_name="Devon Pike", citizenship_country="CA",
        requires_sponsorship=False, phd_award_date="2026-05-02",
        prior_external_months_in_rank=0,
    )

    external_appointment = draft_appointment(
        scholar_one["id"], mentor["id"], external_award["id"], officer,
        **_FELLOWSHIP_TERM,
    )
    issue_offer(external_appointment["id"], officer)
    institutional_appointment = draft_appointment(
        scholar_two["id"], mentor["id"], institutional_award["id"], officer,
        **_FELLOWSHIP_TERM,
    )
    issue_offer(institutional_appointment["id"], officer)

    return {
        "officer": officer,
        "external_appointment": external_appointment,
        "institutional_appointment": institutional_appointment,
        "external_cycle": queued_screening_cycle(external_appointment["id"]),
        "institutional_cycle": queued_screening_cycle(institutional_appointment["id"]),
    }


def test_a_score_landing_exactly_on_the_threshold_clears_with_conditions():
    """6.25 + 18.75 + 10.00 is 35.0, and the inclusive test takes conditions.

    PRD 3.6: "Otherwise a `risk_score` of 35.0 or above is
    `CLEARED_WITH_CONDITIONS`." PRD 3.6: "The funding component is the funding
    factor multiplied by 6.25."

    Design: Difficulty/boundary_precision_check/risk_score_landing_exactly_on_conditions_threshold_clears_with_conditions
    """
    setup = _two_queued_canadian_screenings()
    assert_money(
        setup["external_appointment"]["salary_floor_usd"], 57957.60, "salary_floor_usd"
    )

    decided = decide_screening(
        setup["external_cycle"]["id"], controlled_technology_flag=True
    )

    assert decided["screening_tier"] == "TIER_1_STANDARD", (
        "Cycle 1 with no restricted-party hit and a country factor of 0.5 is "
        f"scored under the standard tier, got {decided['screening_tier']}"
    )
    assert_risk_score(decided["risk_score"], 35.0)
    assert decided["status"] == "CLEARED_WITH_CONDITIONS", (
        f"Expected CLEARED_WITH_CONDITIONS at the threshold, got {decided['status']}"
    )
    assert decided["deemed_export_license_required"] is False, (
        "A country factor of 0.5 is below 3.0, so no deemed-export licence is "
        "determined even with controlled technology present"
    )

    appointment = read_appointment(
        setup["external_appointment"]["id"], setup["officer"]
    )
    assert appointment["compliance_status"] == "RESTRICTED", (
        f"Expected compliance_status RESTRICTED, got {appointment['compliance_status']}"
    )


def test_a_zero_funding_factor_drops_the_same_findings_below_the_threshold():
    """The identical findings on an INSTITUTIONAL_FELLOWSHIP land on 25.0.

    PRD 3.6: "The funding factor is read from the award's `funding_type`, where
    `FEDERAL_GRANT` scores 1.0, `FOUNDATION_GRANT` scores 0.5,
    `EXTERNAL_FELLOWSHIP` scores 1.6 and `INSTITUTIONAL_FELLOWSHIP` scores 0.0."

    Design: Difficulty/boundary_precision_check/risk_score_landing_exactly_on_conditions_threshold_clears_with_conditions
    """
    setup = _two_queued_canadian_screenings()

    decided = decide_screening(
        setup["institutional_cycle"]["id"], controlled_technology_flag=True
    )

    assert decided["screening_tier"] == "TIER_1_STANDARD"
    assert_risk_score(decided["risk_score"], 25.0)
    assert decided["status"] == "CLEARED", (
        f"Expected CLEARED below the threshold, got {decided['status']}"
    )

    appointment = read_appointment(
        setup["institutional_appointment"]["id"], setup["officer"]
    )
    assert appointment["compliance_status"] == "CLEARED", (
        f"Expected compliance_status CLEARED, got {appointment['compliance_status']}"
    )


def test_the_funding_component_is_the_only_difference_across_the_threshold():
    """Ten points of funding weight separate a clearance from a conditional one.

    PRD 3.6: "Five components are computed, **each rounded half up to two decimal
    places on its own**, and only their sum is rounded — half up, to one decimal
    place — to give `risk_score`."

    Design: Difficulty/boundary_precision_check/risk_score_landing_exactly_on_conditions_threshold_clears_with_conditions
    """
    setup = _two_queued_canadian_screenings()

    external = decide_screening(
        setup["external_cycle"]["id"], controlled_technology_flag=True
    )
    institutional = decide_screening(
        setup["institutional_cycle"]["id"], controlled_technology_flag=True
    )

    assert external["screening_tier"] == institutional["screening_tier"] == (
        "TIER_1_STANDARD"
    ), "Both cycles are first cycles with sub-3.0 country factors"
    assert external["deemed_export_license_required"] is False
    assert institutional["deemed_export_license_required"] is False
    assert round(external["risk_score"] - institutional["risk_score"], 1) == 10.0, (
        "A funding factor of 1.6 against 0.0 at a 6.25 weight is a ten-point "
        f"difference, got {external['risk_score']} versus "
        f"{institutional['risk_score']}"
    )
    assert external["status"] != institutional["status"], (
        "Ten points across the 35.0 threshold must change the outcome"
    )

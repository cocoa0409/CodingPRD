"""Qualification screening: the nested education-cap formula, the inclusive
creditable==required boundary, the substitution-disabled branch, and the
screening state gate.
"""
from test_helpers import (
    HR, ApiErrorId,
    api_client, create_assessment_payload, expected_creditable_months,
    expected_required_months, make_sme_headers, register_applicant,
    screen_application, setup_open_announcement, setup_qualified_application,
    submit_application, validate_error,
)

# Default series: base 6 months, 6 per grade step, span 5..12, education
# substitution allowed with a 12-month cap. Default position: factors
# (2,2,3,2) -> 2250 points -> official grade 9, so required = 6 + (9-5)*6 = 30.


def test_qualification_nested_min_grade_dependent_threshold(api):
    """PRD §3.4: "the education credit as the lesser of
    `claimed_education_months` and the series' `education_substitution_cap_months`
    when `allows_education_substitution` holds, and zero otherwise; and
    `creditable_experience_months` as `claimed_experience_months` plus that
    credit. The applicant is qualified when creditable months are at least the
    required months — equality qualifies".

    Design: Difficulty/combinatorial_formula/qualification_nested_min_grade_dependent_threshold
    """
    ctx = setup_open_announcement()
    announcement, series = ctx["announcement"], ctx["series"]

    app_a = submit_application(
        announcement, register_applicant(),
        claimed_experience_months=18, claimed_education_months=20)
    app_b = submit_application(
        announcement, register_applicant(),
        claimed_experience_months=17, claimed_education_months=20)

    screened_a = screen_application(app_a["id"])
    # Education is capped at 12 (not 20): creditable = 18 + min(20, 12) = 30.
    assert screened_a["required_experience_months"] == expected_required_months(series, 9) == 30
    assert screened_a["creditable_experience_months"] == 30
    assert screened_a["status"] == "QUALIFIED"

    screened_b = screen_application(app_b["id"])
    assert screened_b["creditable_experience_months"] == 29
    assert screened_b["status"] == "INELIGIBLE"


def test_qualification_exact_required_months_boundary(api):
    """PRD §3.4: "The applicant is qualified when creditable months are at least
    the required months — equality qualifies — and, when the series demands
    positive education, when `claimed_education_months` is greater than zero;
    any shortfall, or a missing positive-education claim on such a series,
    renders the applicant `INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/qualification_exact_required_months_boundary
    """
    ctx = setup_open_announcement()
    announcement, series = ctx["announcement"], ctx["series"]

    at_boundary = submit_application(
        announcement, register_applicant(),
        claimed_experience_months=30, claimed_education_months=0)
    one_below = submit_application(
        announcement, register_applicant(),
        claimed_experience_months=29, claimed_education_months=0)

    screened_a = screen_application(at_boundary["id"])
    assert screened_a["creditable_experience_months"] == 30
    assert screened_a["required_experience_months"] == expected_required_months(series, 9) == 30
    assert screened_a["status"] == "QUALIFIED", "creditable == required must qualify (>= boundary)"

    screened_b = screen_application(one_below["id"])
    assert screened_b["creditable_experience_months"] == 29
    assert screened_b["status"] == "INELIGIBLE", "one month below the threshold flips the outcome"


def test_education_substitution_disabled_branch(api):
    """PRD §3.4: "the education credit as the lesser of
    `claimed_education_months` and the series' `education_substitution_cap_months`
    when `allows_education_substitution` holds, and zero otherwise".

    Design: Corner/calculations/education_substitution_disabled_branch
    """
    ctx = setup_open_announcement(
        series_overrides={"allows_education_substitution": False})
    announcement, series = ctx["announcement"], ctx["series"]

    application = submit_application(
        announcement, register_applicant(),
        claimed_experience_months=18, claimed_education_months=20)
    screened = screen_application(application["id"])
    # Substitution disallowed: education months are ignored entirely.
    assert screened["creditable_experience_months"] == expected_creditable_months(series, 18, 20) == 18
    assert screened["required_experience_months"] == expected_required_months(series, 9) == 30
    assert screened["status"] == "INELIGIBLE"


def test_rescreen_and_premature_assessment_rejected(api):
    """PRD §3.4: "Screening anything not in `RECEIVED` is rejected with
    `ERR_APPLICATION_WRONG_STATE` (HTTP 409)".
    PRD §3.5: "creating one for an application not yet `QUALIFIED` is
    `ERR_APPLICATION_WRONG_STATE`."

    Design: Corner/validations/rescreen_and_premature_assessment_rejected
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]

    _applicant, qualified = setup_qualified_application(announcement)
    resp = api_client.screen_application(qualified["id"], HR)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WRONG_STATE)

    second_applicant = register_applicant()
    received = submit_application(announcement, second_applicant)
    assert received["status"] == "RECEIVED"
    resp = api_client.create_assessment(
        received["id"], create_assessment_payload(4, 4, 4),
        make_sme_headers("sme-1"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WRONG_STATE)

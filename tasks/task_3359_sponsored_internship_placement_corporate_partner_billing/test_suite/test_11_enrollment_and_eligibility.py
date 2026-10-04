"""Applicant selection, the three eligibility gates, and enrollment."""
from test_helpers import (
    ApiErrorId,
    create_cohort,
    eligibility_decision_payload,
    enrollment_payload,
    read_cohort,
    read_student,
    record_eligibility_decision,
    register_student,
    staff_headers,
    validate_error,
    validate_success,
)


def test_eligibility_decision_after_terminal_returns_already_terminal(api):
    """PRD §3.1: "it moves the student `APPLIED → INELIGIBLE`, which is the student
    machine's only terminal state, and from that point no enrollment, cohort
    assignment or stipend statement may ever be created for that student. Any later
    attempt to act on that student is refused with `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.1: "A `decision` of `INELIGIBLE` requires no gate at all"

    Design: Corner/state_machines/eligibility_decision_after_terminal_returns_already_terminal
    """
    cora = register_student(
        full_name="Cora Pike", email="cora.pike@example.com",
        date_of_birth="2001-10-10", education_status="ASSOCIATE",
        household_income_cents=2_400_000,
    )
    decided = record_eligibility_decision(
        cora["id"], decision="INELIGIBLE", reason="Applicant withdrew before the interview panel"
    )
    assert decided["application_state"] == "INELIGIBLE", decided["application_state"]

    response = api.record_eligibility_decision(
        cora["id"], eligibility_decision_payload(), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert read_student(cora["id"])["application_state"] == "INELIGIBLE"


def test_enrollment_from_applied_state_returns_invalid_state(api):
    """PRD §2.5: "The target row must be in a non-terminal state that admits the
    requested transition; this check reports a row whose current state simply has no
    transition for the requested action. Otherwise `ERR_INVALID_STATE` (409)."
    PRD §3.2: "When everything passes, the student moves `ELIGIBLE → ENROLLED`"

    Design: Corner/state_machines/enrollment_from_applied_state_returns_invalid_state
    """
    cohort = create_cohort()
    ben = register_student(
        full_name="Ben Ortiz", email="ben.ortiz@example.com",
        date_of_birth="2004-02-02", education_status="SOME_COLLEGE",
        household_income_cents=1_800_000,
    )

    response = api.enroll_student(
        ben["id"], enrollment_payload(cohort["id"]), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert read_cohort(cohort["id"])["enrolled_count"] == 0
    assert read_student(ben["id"])["application_state"] == "APPLIED"


def test_income_ceiling_is_inclusive_at_four_million_five_hundred_thousand(api):
    """PRD §2.11: "The income gate requires `household_income_cents` to be at or below
    4,500,000 cents, that is, an annual household income of at most $45,000."
    PRD §3.1: "the request is rejected with that gate's own error —
    `ERR_AGE_INELIGIBLE`, `ERR_EDUCATION_INELIGIBLE` or `ERR_INCOME_INELIGIBLE`, each
    at 422 — and the student stays at `APPLIED`, so the record can be corrected and
    decided again"

    Design: Corner/validations/income_ceiling_boundary_at_exactly_four_million_five_hundred_thousand
    """
    at_ceiling = register_student(
        full_name="Ava Reyes", email="ava.reyes@example.com",
        date_of_birth="2005-04-12", education_status="HS_DIPLOMA",
        household_income_cents=4_500_000,
    )
    over_ceiling = register_student(
        full_name="Ben Ortiz", email="ben.ortiz@example.com",
        date_of_birth="2004-02-02", education_status="SOME_COLLEGE",
        household_income_cents=4_500_001,
    )

    accepted = validate_success(
        api.record_eligibility_decision(
            at_ceiling["id"], eligibility_decision_payload(), staff_headers()
        ),
        200,
    )
    assert accepted["application_state"] == "ELIGIBLE", accepted["application_state"]

    response = api.record_eligibility_decision(
        over_ceiling["id"], eligibility_decision_payload(), staff_headers()
    )
    validate_error(response, ApiErrorId.ERR_INCOME_INELIGIBLE, expected_status=422)

    rejected = read_student(over_ceiling["id"])
    assert rejected["application_state"] == "APPLIED", rejected["application_state"]
    assert rejected["household_income_cents"] == 4_500_001, rejected["household_income_cents"]


def test_bachelor_degree_applicant_returns_education_ineligible(api):
    """PRD §2.11: "The education gate requires the applicant's `education_status` to
    be one of `NO_DIPLOMA`, `HS_DIPLOMA`, `SOME_COLLEGE` or `ASSOCIATE` — a
    `BACHELOR_OR_HIGHER` applicant is refused."

    Design: Corner/validations/bachelor_degree_applicant_returns_education_ineligible
    """
    cora = register_student(
        full_name="Cora Pike", email="cora.pike@example.com",
        date_of_birth="2003-03-03", education_status="BACHELOR_OR_HIGHER",
        household_income_cents=1_200_000,
    )

    response = api.record_eligibility_decision(
        cora["id"], eligibility_decision_payload(), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_EDUCATION_INELIGIBLE, expected_status=422)
    assert read_student(cora["id"])["application_state"] == "APPLIED"


def test_enrollment_effects_are_visible_in_the_same_request(api):
    """PRD §3.2: "When everything passes, the student moves `ELIGIBLE → ENROLLED`,
    `current_phase` becomes `L_AND_D`, the cohort's `enrolled_count` increments by 1,
    and a cohort that was `PLANNED` becomes `ACTIVE`"

    Design: Corner/consistency_model/enrollment_effects_visible_within_the_same_request
    """
    cohort = create_cohort()
    ava = register_student()
    record_eligibility_decision(ava["id"])

    enrolled = validate_success(
        api.enroll_student(ava["id"], enrollment_payload(cohort["id"]), staff_headers()), 200
    )
    assert enrolled["application_state"] == "ENROLLED", enrolled["application_state"]
    assert enrolled["current_phase"] == "L_AND_D", enrolled["current_phase"]

    cohort_now = read_cohort(cohort["id"])
    assert cohort_now["enrolled_count"] == 1, cohort_now["enrolled_count"]
    assert cohort_now["status"] == "ACTIVE", cohort_now["status"]

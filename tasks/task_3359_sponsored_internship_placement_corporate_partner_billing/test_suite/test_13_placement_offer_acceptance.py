"""Matching, offers and acceptance: not-found, state, ownership and window gates."""
from test_helpers import (
    ApiErrorId,
    acceptance_payload,
    advance_student_to_internship,
    create_cohort,
    create_enrolled_student,
    make_student_headers,
    placement_payload,
    register_student,
    schedule_interview_for,
    setup_matched_placement,
    setup_offered_placement,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_AGREEMENT_ID = "0f2c8b41-6d1e-4a77-9f3d-5c2a7e9b1044"


def test_placement_with_unknown_agreement_returns_not_found(api):
    """PRD §2.9: "a `cohort_id`, `partner_id`, `agreement_id`, `student_id` or
    `placement_id` that names no row is a `ERR_NOT_FOUND` (404) and is checked before
    any business rule about the referenced row's state is evaluated"

    Design: Corner/entities/placement_with_unknown_agreement_returns_not_found
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    advance_student_to_internship(student["id"])

    response = api.create_placement(
        placement_payload(UNKNOWN_AGREEMENT_ID, student["id"]), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    placements, meta = validate_paginated(
        api.list_placements(staff_headers(), {"student_id": student["id"]})
    )
    assert meta["total_count"] == 0, placements


def test_offer_before_the_interview_outcome_returns_invalid_state(api):
    """PRD §3.4: "An offer is extended once the placement's latest interview round has
    `outcome` `PASSED` and the sponsoring agreement is still `ACTIVE`."
    PRD §2.5: "The target row must be in a non-terminal state that admits the
    requested transition; this check reports a row whose current state simply has no
    transition for the requested action. Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/validations/offer_before_interview_outcome_returns_invalid_state
    """
    scenario = setup_matched_placement()
    schedule_interview_for(scenario.placement["id"])

    response = api.extend_offer(scenario.placement["id"], staff_headers())

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "INTERVIEW_SCHEDULED", placement["state"]
    assert placement.get("placement_fee_cents") is None, placement.get("placement_fee_cents")


def test_offer_acceptance_by_another_student_returns_not_owner(api):
    """PRD §3.4: "the acting `X-User-ID` must equal the placement's `student_id` or the
    request fails with `ERR_NOT_OWNER` (403)"
    PRD §2.1: "A caller whose role is authorized for the operation but whose
    `X-User-ID` does not match the owning foreign key on the specific row being acted
    upon is rejected with `ERR_NOT_OWNER` at HTTP 403"

    Design: Corner/validations/offer_acceptance_by_another_student_returns_not_owner
    """
    scenario = setup_offered_placement()
    other = register_student(
        full_name="Ben Ortiz", email="ben.ortiz@example.com",
        date_of_birth="2004-02-02", education_status="SOME_COLLEGE",
        household_income_cents=1_800_000,
    )

    response = api.accept_offer(
        scenario.placement["id"], acceptance_payload(), make_student_headers(other["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_OWNER, expected_status=403)
    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "OFFERED", placement["state"]


def test_acceptance_window_outside_the_agreement_is_refused(api):
    """PRD §3.4: "the accepted window must lie inside the agreement's window with
    `hours_per_week` at least 20, a violation of which is
    `ERR_PLACEMENT_WINDOW_INVALID` (409)"

    The requested window satisfies the 28-day minimum, so only the agreement
    boundary rejects it.

    Design: Corner/validations/acceptance_window_outside_agreement_returns_placement_window_invalid
    """
    scenario = setup_offered_placement()

    response = api.accept_offer(
        scenario.placement["id"],
        acceptance_payload(start_date="2027-03-01", end_date="2027-06-30"),
        make_student_headers(scenario.student["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PLACEMENT_WINDOW_INVALID, expected_status=409)
    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "OFFERED", placement["state"]

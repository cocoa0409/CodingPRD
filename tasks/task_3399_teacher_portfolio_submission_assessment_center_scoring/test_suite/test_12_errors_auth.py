"""Error catalogue coverage: the resource-specific 404 sweep across path and
body identifiers, and the role-gate-before-existence-gate ordering."""
from test_helpers import (
    ANON,
    BOARD,
    INCENTIVE_ADMIN,
    NON_EXISTENT_UUID,
    SCORING_ADMIN,
    STANDARD_SLOT_START,
    ApiErrorId,
    create_assessment_center,
    create_booking_payload,
    create_candidate_payload,
    create_eligible_candidate,
    create_open_cycle,
    create_submission,
    cycle_transition_payload,
    make_candidate_headers,
    validate_error,
)


def test_not_found_sweep_returns_resource_specific_404s(api):
    """PRD §2.8: "4. **Existence** (404) — path identifiers resolve to existing
    resources, validated strictly left-to-right along the URL; body-supplied
    identifiers such as `center_id`, `cycle_id`, `submission_id`, `benchmark_id`,
    and `assessor_id` resolve as well, each mapping to its own not-found error."
    PRD §3.4: "the candidate must hold an `IN_PROGRESS` attempt of the
    `ASSESSMENT` component in that cycle — with no such open attempt the booking
    fails with `ERR_SUBMISSION_NOT_FOUND` (HTTP 404)".

    Every resource-specific 404 in the catalogue is exercised: unknown path ids,
    unknown body ids, and the booking-without-open-ASSESSMENT-attempt case.

    Design: Corner/errors/not_found_sweep_returns_resource_specific_404s
    """
    cycle = create_open_cycle()
    center = create_assessment_center()
    # Candidate A: ELIGIBLE but holds no ASSESSMENT attempt.
    cand_a = create_eligible_candidate()
    # Candidate B: ELIGIBLE with an IN_PROGRESS CKA attempt.
    cand_b = create_eligible_candidate()
    create_submission(cycle["id"], cand_b, "CKA")
    headers_b = make_candidate_headers(cand_b["id"])

    path_cases = [
        ("cycle", api.get_cycle(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_CYCLE_NOT_FOUND),
        ("candidate", api.get_candidate(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_CANDIDATE_NOT_FOUND),
        ("submission", api.get_submission(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
        ("center", api.get_assessment_center(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("booking", api.get_booking(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_BOOKING_NOT_FOUND),
        ("assessor", api.get_assessor(NON_EXISTENT_UUID, SCORING_ADMIN), ApiErrorId.ERR_ASSESSOR_NOT_FOUND),
        ("assignment", api.get_assignment(NON_EXISTENT_UUID, SCORING_ADMIN), ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        ("certification", api.get_certification(NON_EXISTENT_UUID, BOARD), ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (
            "renewal",
            api.review_renewal(NON_EXISTENT_UUID, {"decision": "APPROVE"}, BOARD),
            ApiErrorId.ERR_RENEWAL_NOT_FOUND,
        ),
        ("program", api.get_incentive_program(NON_EXISTENT_UUID, INCENTIVE_ADMIN), ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (
            "stipend",
            api.transition_stipend(NON_EXISTENT_UUID, {"to": "APPROVED"}, INCENTIVE_ADMIN),
            ApiErrorId.ERR_STIPEND_NOT_FOUND,
        ),
    ]
    for label, response, error_id in path_cases:
        validate_error(response, error_id)
        assert response.status_code == 404, f"{label}: expected 404, got {response.status_code}"

    body_cases = [
        (
            "benchmark_id in assignment create",
            api.create_assignment({"benchmark_id": NON_EXISTENT_UUID}, SCORING_ADMIN),
            ApiErrorId.ERR_BENCHMARK_NOT_FOUND,
        ),
        (
            "center_id in booking create",
            api.create_booking(
                create_booking_payload(NON_EXISTENT_UUID, cycle["id"], STANDARD_SLOT_START),
                headers_b,
            ),
            ApiErrorId.ERR_CENTER_NOT_FOUND,
        ),
        (
            "cycle_id in booking create",
            api.create_booking(
                create_booking_payload(center["id"], NON_EXISTENT_UUID, STANDARD_SLOT_START),
                headers_b,
            ),
            ApiErrorId.ERR_CYCLE_NOT_FOUND,
        ),
    ]
    for label, response, error_id in body_cases:
        validate_error(response, error_id)
        assert response.status_code == 404, f"{label}: expected 404, got {response.status_code}"

    no_open_attempt = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], STANDARD_SLOT_START),
        make_candidate_headers(cand_a["id"]),
    )
    validate_error(no_open_attempt, ApiErrorId.ERR_SUBMISSION_NOT_FOUND)
    assert no_open_attempt.status_code == 404


def test_role_denial_precedes_existence_check(api):
    """PRD §2.8: "When several checks could reject the same request, the server
    evaluates them in a fixed order so callers always see the same error. The ten
    gates, in order:"
    PRD §2.8: "2. **Role authorization** (`ERR_INSUFFICIENT_PERMISSIONS`, 403) —
    the presented role must be in the endpoint's role list."
    PRD §2.8: "4. **Existence** (404) — path identifiers resolve to existing
    resources, validated strictly left-to-right along the URL; body-supplied
    identifiers such as `center_id`, `cycle_id`, `submission_id`, `benchmark_id`,
    and `assessor_id` resolve as well, each mapping to its own not-found error."

    A Candidate driving the BoardAdministrator-only cycle transition against a
    non-existent cycle id must meet the 403 role gate, never a 404.

    Design: Corner/validations/role_denial_precedes_existence_check
    """
    candidate = api.create_candidate(create_candidate_payload(), ANON)
    assert candidate.status_code == 201

    response = api.transition_cycle(
        NON_EXISTENT_UUID,
        cycle_transition_payload("OPEN"),
        make_candidate_headers(candidate.json()["data"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert response.status_code == 403

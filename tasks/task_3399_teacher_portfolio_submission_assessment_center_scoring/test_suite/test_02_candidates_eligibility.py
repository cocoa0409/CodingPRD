"""Candidate registration, the eligibility review loop, and the ELIGIBLE gate
on component-attempt creation."""
from test_helpers import (
    ANON,
    BOARD,
    DEFAULT_FTE_FRACTION,
    INCENTIVE_ADMIN,
    STANDARD_WORK_CLOCK,
    ApiErrorId,
    CandidateStatus,
    SubmissionStatus,
    assert_candidate,
    create_candidate_payload,
    create_eligible_candidate,
    create_open_cycle,
    eligibility_evidence_payload,
    make_candidate_headers,
    set_logical_clock,
    validate_created,
    validate_error,
    validate_success,
    verify_eligibility_payload,
)


def test_candidate_create_roundtrip_defaults_and_status_input_ignored(api):
    """PRD §3.2: "Open registration creates a candidate record in `REGISTERED`
    status carrying `full_name`, a unique `email`, `license_number`, the two-letter
    `license_state` that issued the license, the employing `district_code`,
    `years_experience` as completed years of classroom teaching, and an optional
    `fte_fraction` teaching-load fraction which defaults to 1.0 and must lie
    between 0.5 and 1.0 inclusive."

    A client-supplied status field has no effect: registration always lands in
    REGISTERED.

    Design: Corner/entities/candidate_create_roundtrip_defaults_and_status_input_ignored
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    payload = create_candidate_payload()
    payload["status"] = "ELIGIBLE"  # client-supplied system field — must be ignored

    candidate = validate_created(api.create_candidate(payload, ANON))

    assert_candidate(candidate)
    assert candidate["status"] == CandidateStatus.REGISTERED.value
    assert candidate["fte_fraction"] == DEFAULT_FTE_FRACTION == 1.0


def test_verify_eligibility_on_registered_candidate_rejected(api):
    """PRD §3.2: "The decision is only legal from `ELIGIBILITY_REVIEW` — otherwise
    `ERR_CANDIDATE_NOT_IN_REVIEW` (HTTP 409)."

    Design: Corner/state_machines/verify_eligibility_on_registered_candidate_rejected
    """
    candidate = validate_created(api.create_candidate(create_candidate_payload(), ANON))
    assert candidate["status"] == CandidateStatus.REGISTERED.value

    response = api.verify_eligibility(
        candidate["id"], verify_eligibility_payload("APPROVE"), BOARD
    )

    validate_error(response, ApiErrorId.ERR_CANDIDATE_NOT_IN_REVIEW)
    reread = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert reread["status"] == CandidateStatus.REGISTERED.value


def test_verify_eligibility_twice_rejected(api):
    """PRD §3.2: "The decision is only legal from `ELIGIBILITY_REVIEW` — otherwise
    `ERR_CANDIDATE_NOT_IN_REVIEW` (HTTP 409)."

    The ELIGIBILITY_REVIEW -> ELIGIBLE edge is consumed exactly once; repeating
    the APPROVE on the now-ELIGIBLE candidate fails.

    Design: Corner/state_machines/verify_eligibility_twice_rejected
    """
    candidate = create_eligible_candidate()
    assert candidate["status"] == CandidateStatus.ELIGIBLE.value

    response = api.verify_eligibility(
        candidate["id"], verify_eligibility_payload("APPROVE"), BOARD
    )

    validate_error(response, ApiErrorId.ERR_CANDIDATE_NOT_IN_REVIEW)
    reread = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert reread["status"] == CandidateStatus.ELIGIBLE.value


def test_submit_eligibility_when_already_eligible_rejected(api):
    """PRD §3.2: "The candidate must be in `REGISTERED` or `ELIGIBILITY_DENIED`;
    from anywhere else the request is `ERR_CANDIDATE_NOT_SUBMITTABLE` (HTTP 409)."

    Design: Corner/state_machines/submit_eligibility_when_already_eligible_rejected
    """
    candidate = create_eligible_candidate()

    response = api.submit_eligibility(
        candidate["id"],
        eligibility_evidence_payload("lic-2.pdf", "emp-2.pdf"),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CANDIDATE_NOT_SUBMITTABLE)
    reread = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert reread["status"] == CandidateStatus.ELIGIBLE.value


def test_eligibility_approve_with_two_years_rejected_three_passes(api):
    """PRD §3.2: "APPROVE carries a hard floor: `years_experience` must be at least
    3, the minimum teaching-experience requirement; approving a candidate below
    three years fails with `ERR_EXPERIENCE_REQUIREMENT_NOT_MET` (HTTP 422)."

    Boundary: 2 years fails, exactly 3 years passes.

    Design: Corner/state_machines/eligibility_approve_with_two_years_rejected_three_passes
    """
    cand_two = validate_created(
        api.create_candidate(create_candidate_payload(years_experience=2), ANON)
    )
    api.submit_eligibility(
        cand_two["id"], eligibility_evidence_payload(), make_candidate_headers(cand_two["id"])
    )
    cand_three = validate_created(
        api.create_candidate(create_candidate_payload(years_experience=3), ANON)
    )
    api.submit_eligibility(
        cand_three["id"],
        eligibility_evidence_payload(),
        make_candidate_headers(cand_three["id"]),
    )

    response_two = api.verify_eligibility(
        cand_two["id"], verify_eligibility_payload("APPROVE"), BOARD
    )
    validate_error(response_two, ApiErrorId.ERR_EXPERIENCE_REQUIREMENT_NOT_MET)
    reread_two = validate_success(api.get_candidate(cand_two["id"], BOARD))
    assert reread_two["status"] == CandidateStatus.ELIGIBILITY_REVIEW.value

    response_three = api.verify_eligibility(
        cand_three["id"], verify_eligibility_payload("APPROVE"), BOARD
    )
    approved = validate_success(response_three)
    assert approved["status"] == CandidateStatus.ELIGIBLE.value


def test_eligibility_denied_resubmission_loop(api):
    """PRD §3.2: "Approval lands the candidate in `ELIGIBLE`; rejection lands them
    in `ELIGIBILITY_DENIED`."
    PRD §3.2: "A denied candidate may resubmit through the same loop, replacing the
    stored references."

    Design: Corner/state_machines/eligibility_denied_resubmission_loop
    """
    candidate = validate_created(api.create_candidate(create_candidate_payload(), ANON))
    headers = make_candidate_headers(candidate["id"])
    validate_success(api.submit_eligibility(candidate["id"], eligibility_evidence_payload(), headers))

    denied = validate_success(
        api.verify_eligibility(
            candidate["id"],
            verify_eligibility_payload("REJECT", note="license document illegible"),
            BOARD,
        )
    )
    assert denied["status"] == CandidateStatus.ELIGIBILITY_DENIED.value

    resubmitted = validate_success(
        api.submit_eligibility(
            candidate["id"],
            eligibility_evidence_payload("lic-a2.pdf", "emp-a2.pdf"),
            headers,
        )
    )
    assert resubmitted["status"] == CandidateStatus.ELIGIBILITY_REVIEW.value

    approved = validate_success(
        api.verify_eligibility(candidate["id"], verify_eligibility_payload("APPROVE"), BOARD)
    )
    assert approved["status"] == CandidateStatus.ELIGIBLE.value


def test_incentive_admin_cannot_verify_eligibility(api):
    """PRD §2.1: "Segregation of duties applies: an `IncentiveAdministrator` cannot
    verify eligibility, review renewals, or score, and the scoring and board roles
    cannot move stipend money."
    PRD §2.1: "If the presented role is not in the endpoint's authorized role list,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/incentive_admin_cannot_verify_eligibility
    """
    candidate = validate_created(api.create_candidate(create_candidate_payload(), ANON))
    validate_success(
        api.submit_eligibility(
            candidate["id"],
            eligibility_evidence_payload(),
            make_candidate_headers(candidate["id"]),
        )
    )

    response = api.verify_eligibility(
        candidate["id"], verify_eligibility_payload("APPROVE"), INCENTIVE_ADMIN
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    reread = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert reread["status"] == CandidateStatus.ELIGIBILITY_REVIEW.value


def test_submission_create_rejected_until_candidate_eligible(api):
    """PRD §3.2: "Only an `ELIGIBLE` candidate may begin component attempts or book
    an assessment session — the gate everywhere is `ERR_CANDIDATE_NOT_ELIGIBLE`
    (HTTP 409)."

    The gate is closed in REGISTERED and stays closed in ELIGIBILITY_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/submission_creation_blocked_until_candidate_eligible
    """
    cycle = create_open_cycle()
    candidate = validate_created(api.create_candidate(create_candidate_payload(), ANON))
    headers = make_candidate_headers(candidate["id"])

    response_registered = api.create_submission(
        cycle["id"], {"component_code": "P1"}, headers
    )
    validate_error(response_registered, ApiErrorId.ERR_CANDIDATE_NOT_ELIGIBLE)

    validate_success(
        api.submit_eligibility(candidate["id"], eligibility_evidence_payload(), headers)
    )
    in_review = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert in_review["status"] == CandidateStatus.ELIGIBILITY_REVIEW.value

    response_in_review = api.create_submission(
        cycle["id"], {"component_code": "P1"}, headers
    )
    validate_error(response_in_review, ApiErrorId.ERR_CANDIDATE_NOT_ELIGIBLE)


def test_submission_create_opens_once_candidate_eligible(api):
    """PRD §3.2: "Only an `ELIGIBLE` candidate may begin component attempts or book
    an assessment session — the gate everywhere is `ERR_CANDIDATE_NOT_ELIGIBLE`
    (HTTP 409)."
    PRD §3.3: "The new attempt starts `IN_PROGRESS` with `attempt_number` 1 and a
    null `prior_submission_id`; its `kind` — `ASSESSMENT` or `PORTFOLIO` — is
    copied from the cycle's component definition at creation and never changes."

    After the board's APPROVE the same create call succeeds.

    Design: Difficulty/cross_entity_state_dependency/submission_creation_blocked_until_candidate_eligible
    """
    cycle = create_open_cycle()
    candidate = validate_created(api.create_candidate(create_candidate_payload(), ANON))
    headers = make_candidate_headers(candidate["id"])
    validate_success(
        api.submit_eligibility(candidate["id"], eligibility_evidence_payload(), headers)
    )
    validate_success(
        api.verify_eligibility(candidate["id"], verify_eligibility_payload("APPROVE"), BOARD)
    )

    submission = validate_created(
        api.create_submission(cycle["id"], {"component_code": "P1"}, headers)
    )

    assert submission["status"] == SubmissionStatus.IN_PROGRESS.value
    assert submission["attempt_number"] == 1
    assert submission["prior_submission_id"] is None
    assert submission["kind"] == "PORTFOLIO"
    reread = validate_success(api.get_candidate(candidate["id"], BOARD))
    assert reread["status"] == CandidateStatus.ELIGIBLE.value

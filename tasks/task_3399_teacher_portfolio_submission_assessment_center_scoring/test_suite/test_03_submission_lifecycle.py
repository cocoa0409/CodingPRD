"""Component-submission lifecycle: creation gates, submit/tech-review revision
loop, retakes, window and expiry rules, and ownership around submissions."""
from test_helpers import (
    ANON,
    BOARD,
    SCORING_ADMIN,
    STANDARD_RETAKE_CLOSE,
    ApiErrorId,
    CycleStatus,
    SubmissionStatus,
    assert_submission,
    create_active_assessors,
    create_cycle_payload,
    create_default_benchmark,
    create_eligible_candidate,
    create_open_cycle,
    create_portfolio_submission_in_state,
    create_submission,
    cycle_transition_payload,
    make_candidate_headers,
    retake_submission,
    score_portfolio_with_agreeing_reads,
    set_logical_clock,
    submit_submission,
    tech_review,
    upload_minimal_portfolio_artifacts,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
)

PAST_WINDOW_CLOSE = "2027-03-02T00:00:00Z"  # one day past the standard close 2027-03-01


def test_submissions_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the page size: it defaults to 10, accepts a minimum
    of 1, and is capped at a maximum of 100. `offset` sets how many records to skip
    and defaults to 0. Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside `meta`, so a caller can page deterministically through the
    full result set."
    PRD §4: "List endpoints accept the `limit` and `offset` pagination parameters
    of §2.3 plus the filter fields surfaced in §3 — `candidate_id`, `cycle_id`,
    `prior_submission_id`, `center_id`, `assessor_id`, `submission_id`,
    `benchmark_id`, and `status` as applicable per row."

    Design: Corner/entities/submissions_list_paginates_with_total_count_and_has_more
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    sub_p1 = create_submission(cycle["id"], candidate, "P1")
    sub_p2 = create_submission(cycle["id"], candidate, "P2")

    page1, meta1 = validate_paginated(
        api.list_submissions(
            BOARD, params={"candidate_id": candidate["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_submissions(
            BOARD, params={"candidate_id": candidate["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    seen = {row["id"] for page in (page1, page2) for row in page}
    assert seen == {sub_p1["id"], sub_p2["id"]}
    for row in page1 + page2:
        assert row["candidate_id"] == candidate["id"]


def test_tech_review_on_in_progress_submission_rejected(api):
    """PRD §3.3: "A `ScoringAdministrator` then performs technical review, again
    supplying a `decision` and an optional `note`, on an attempt in `SUBMITTED` —
    anything else is `ERR_SUBMISSION_NOT_REVIEWABLE` (HTTP 409)."

    Design: Corner/state_machines/tech_review_on_in_progress_submission_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="IN_PROGRESS"
    )

    response = api.tech_review_submission(submission["id"], {"decision": "ACCEPT"}, SCORING_ADMIN)

    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_REVIEWABLE)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.IN_PROGRESS.value


def test_expired_submission_terminal_lockdown(api):
    """PRD §3.1: "That advance sweeps every component submission of the cycle still
    sitting in `IN_PROGRESS`, `SUBMITTED`, or `RETURNED` into `EXPIRED`."
    PRD §3.1: "`EXPIRED` is terminal for a submission: expired attempts never score
    and never count."
    PRD §3.3: "The state gate fires first: an attempt not in `IN_PROGRESS` or
    `RETURNED` is `ERR_SUBMISSION_NOT_SUBMITTABLE` (HTTP 409)."

    Design: Corner/state_machines/expired_submission_terminal_lockdown
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")

    set_logical_clock(PAST_WINDOW_CLOSE)
    advanced = validate_success(
        api.transition_cycle(cycle["id"], cycle_transition_payload("SCORING"), BOARD)
    )
    assert advanced["status"] == CycleStatus.SCORING.value

    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.EXPIRED.value

    response = api.submit_submission(submission["id"], make_candidate_headers(candidate["id"]))
    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTABLE)


def test_cycle_close_expires_scoring_submissions(api):
    """PRD §3.1: "The later advance from `SCORING` to `CLOSED` sweeps submissions
    still in `SCORING` or `ADJUDICATION_REQUIRED` into `EXPIRED`."

    Design: Corner/state_machines/cycle_close_expires_scoring_submissions
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )

    set_logical_clock(PAST_WINDOW_CLOSE)
    validate_success(api.transition_cycle(cycle["id"], cycle_transition_payload("SCORING"), BOARD))
    mid = validate_success(api.get_submission(submission["id"], BOARD))
    assert mid["status"] == SubmissionStatus.SCORING.value, (
        "OPEN -> SCORING must not sweep an attempt already in SCORING"
    )

    closed = validate_success(
        api.transition_cycle(cycle["id"], cycle_transition_payload("CLOSED"), BOARD)
    )
    assert closed["status"] == CycleStatus.CLOSED.value

    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.EXPIRED.value

    response = api.submit_submission(submission["id"], make_candidate_headers(candidate["id"]))
    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTABLE)


def test_submission_create_on_draft_cycle_rejected(api):
    """PRD §3.3: "The code must exist in that cycle's `components` array, else
    `ERR_COMPONENT_NOT_IN_CYCLE` (HTTP 422), and the cycle must be `OPEN`, else
    `ERR_CYCLE_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/submission_create_on_draft_cycle_rejected
    """
    set_logical_clock("2027-01-10T00:00:00Z")
    cycle = validate_created(api.create_cycle(create_cycle_payload(), BOARD))
    assert cycle["status"] == CycleStatus.DRAFT.value
    candidate = create_eligible_candidate()

    response = api.create_submission(
        cycle["id"], {"component_code": "P1"}, make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_OPEN)


def test_submission_create_unknown_component_rejected(api):
    """PRD §3.3: "The code must exist in that cycle's `components` array, else
    `ERR_COMPONENT_NOT_IN_CYCLE` (HTTP 422), and the cycle must be `OPEN`, else
    `ERR_CYCLE_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/submission_create_unknown_component_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()

    response = api.create_submission(
        cycle["id"], {"component_code": "ZZ"}, make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_COMPONENT_NOT_IN_CYCLE)


def test_submission_create_second_active_attempt_rejected(api):
    """PRD §3.3: "While any earlier attempt of the same candidate, cycle, and
    component still sits in `IN_PROGRESS`, `SUBMITTED`, `RETURNED`, `SCORING`, or
    `ADJUDICATION_REQUIRED`, creating another is refused with
    `ERR_ACTIVE_ATTEMPT_EXISTS` (HTTP 409): only one open attempt per component
    triple may exist."

    Design: Corner/validations/submission_create_second_active_attempt_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    create_submission(cycle["id"], candidate, "P1")

    response = api.create_submission(
        cycle["id"], {"component_code": "P1"}, make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_ACTIVE_ATTEMPT_EXISTS)


def test_submit_after_window_close_returns_window_closed(api):
    """PRD §3.3: "Then the cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), and the
    logical clock must fall within the half-open submission window, else
    `ERR_SUBMISSION_WINDOW_CLOSED` (HTTP 422)."
    PRD §2.4: "Component submissions are deliberately never expired by the clock —
    they expire only when their parent cycle leaves `OPEN` or leaves `SCORING` — so
    the submission-window temporal gate stays reachable regardless of how far the
    clock is advanced."

    Design: Corner/validations/submit_after_window_close_returns_window_closed
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    upload_minimal_portfolio_artifacts(submission["id"], candidate)
    set_logical_clock(PAST_WINDOW_CLOSE)  # cycle remains OPEN; no sweep on the clock

    response = api.submit_submission(submission["id"], make_candidate_headers(candidate["id"]))

    validate_error(response, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.IN_PROGRESS.value


def test_retake_on_unscored_attempt_rejected(api):
    """PRD §3.3: "The candidate opens the next attempt from an attempt whose status
    is `SCORED`; from any other status the request is
    `ERR_SUBMISSION_NOT_RETAKEABLE` (HTTP 409)."

    Design: Corner/validations/retake_on_unscored_attempt_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")

    response = api.retake_submission(
        submission["id"], make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_RETAKEABLE)


def test_retake_window_closed_rejected(api):
    """PRD §3.3: "Retakes also close with the cycle: a retake requested at or after
    `retake_window_close` is `ERR_RETAKE_WINDOW_CLOSED` (HTTP 422)."
    PRD §2.7: "A cycle's `retake_window_close` must be at or after its own
    `submission_window_close`, and the retake boundary is exclusive — a retake
    requested exactly at `retake_window_close` is already too late."

    Design: Corner/validations/retake_window_closed_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    scored = score_portfolio_with_agreeing_reads(
        submission["id"], assessors[0], assessors[1], 2.00
    )
    assert scored["status"] == SubmissionStatus.SCORED.value

    set_logical_clock(STANDARD_RETAKE_CLOSE)  # exactly the exclusive boundary
    response = api.retake_submission(
        submission["id"], make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_RETAKE_WINDOW_CLOSED)


def test_retake_limit_reached_after_max_attempts(api):
    """PRD §3.3: "The new attempt links back to its source through
    `prior_submission_id`, takes `attempt_number` one higher than the count of prior
    attempts for the same candidate, cycle, and component, and may not push
    `attempt_number` beyond the cycle's `max_attempts_per_component` — breaching
    that cap is `ERR_RETAKE_LIMIT_REACHED` (HTTP 422)."
    PRD §3.3: "Once any attempt of the triple reaches `SCORED`, each attempt row of
    the triple carries the same `counted_score`: the maximum `final_score` across
    the triple's `SCORED` attempts, excluding anything `EXPIRED`, `RETURNED`, or
    still in flight."

    With the default cap of 2, attempts 1 and 2 score; the third retake is refused.

    Design: Corner/validations/retake_limit_reached_after_max_attempts
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)

    attempt1 = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    score_portfolio_with_agreeing_reads(attempt1["id"], assessors[0], assessors[1], 1.50)

    attempt2 = retake_submission(attempt1["id"], candidate)
    assert attempt2["attempt_number"] == 2
    upload_minimal_portfolio_artifacts(attempt2["id"], candidate)
    submit_submission(attempt2["id"], candidate)
    tech_review(attempt2["id"], "ACCEPT")
    score_portfolio_with_agreeing_reads(attempt2["id"], assessors[0], assessors[1], 2.00)

    response = api.retake_submission(attempt2["id"], make_candidate_headers(candidate["id"]))
    validate_error(response, ApiErrorId.ERR_RETAKE_LIMIT_REACHED)

    reread1 = validate_success(api.get_submission(attempt1["id"], BOARD))
    reread2 = validate_success(api.get_submission(attempt2["id"], BOARD))
    assert reread1["counted_score"] == 2.00
    assert reread2["counted_score"] == 2.00


def test_candidate_cannot_tech_review_own_submission(api):
    """PRD §2.1: "If the presented role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: the technical-review row authorizes `ScoringAdministrator` only.

    Ownership does not rescue the call: the endpoint is ScoringAdministrator-only.

    Design: Corner/rbac/candidate_cannot_tech_review_own_submission
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SUBMITTED"
    )

    response = api.tech_review_submission(
        submission["id"], {"decision": "ACCEPT"}, make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.SUBMITTED.value


def test_candidate_b_cannot_submit_candidate_a_submission(api):
    """PRD §2.1: "A third auth gate guards ownership: when an entity-backed caller
    touches a resource owned by someone else, the request fails with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the
    acting `Candidate` record; ownership checks on any candidate-scoped resource
    compare the resource's `candidate_id` field to `X-User-ID`."

    Design: Corner/rbac/candidate_b_cannot_submit_candidate_a_submission
    """
    cycle = create_open_cycle()
    candidate_a = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate_a, "P1")
    upload_minimal_portfolio_artifacts(submission["id"], candidate_a)
    candidate_b = validate_created(api.create_candidate(
        {"full_name": "Candidate B", "email": "b-ownership@example.com",
         "license_number": "LIC-B-OWN", "license_state": "NM",
         "district_code": "D-100", "years_experience": 5}, ANON
    ))

    response = api.submit_submission(
        submission["id"], make_candidate_headers(candidate_b["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.IN_PROGRESS.value


def test_revision_loop_walks_submitted_returned_scoring_scored(api):
    """PRD §3.3: "Submitting an attempt — from `IN_PROGRESS`, or resubmitting from
    `RETURNED` in the revision loop — runs its gates in the fixed order of §2.8."
    PRD §3.3: "ACCEPT advances the attempt to `SCORING`; RETURN sends it back to
    `RETURNED` so the candidate can revise and resubmit."
    PRD §3.6: "If the reads sit within 0.50 of each other — the boundary is
    inclusive — the attempt's `final_score` is the mean of the two reads rounded
    half up to 2 decimal places, both read assignments transition to `FINALIZED`,
    and the attempt becomes `SCORED`."

    One row walks IN_PROGRESS -> SUBMITTED -> RETURNED -> SUBMITTED -> SCORING ->
    SCORED.

    Design: Difficulty/non_linear_state_machine/component_submission_return_resubmit_retake_cycle
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)

    submission = create_submission(cycle["id"], candidate, "P1")
    upload_minimal_portfolio_artifacts(submission["id"], candidate)

    step1 = submit_submission(submission["id"], candidate)
    assert step1["status"] == SubmissionStatus.SUBMITTED.value

    step2 = tech_review(submission["id"], "RETURN", note="video audio inaudible")
    assert step2["status"] == SubmissionStatus.RETURNED.value

    step3 = submit_submission(submission["id"], candidate)
    assert step3["status"] == SubmissionStatus.SUBMITTED.value

    step4 = tech_review(submission["id"], "ACCEPT")
    assert step4["status"] == SubmissionStatus.SCORING.value

    scored = score_portfolio_with_agreeing_reads(
        submission["id"], assessors[0], assessors[1], 2.00
    )
    assert scored["status"] == SubmissionStatus.SCORED.value
    assert scored["final_score"] == 2.00


def test_retake_chain_links_prior_attempt_and_supersedes(api):
    """PRD §3.3: "The new attempt links back to its source through
    `prior_submission_id`, takes `attempt_number` one higher than the count of prior
    attempts for the same candidate, cycle, and component, and may not push
    `attempt_number` beyond the cycle's `max_attempts_per_component` — breaching
    that cap is `ERR_RETAKE_LIMIT_REACHED` (HTTP 422)."
    PRD §3.3: "When the new attempt lands, every earlier attempt of the same
    component triple flips its `superseded` flag to true — only the
    highest-`attempt_number` row carries false — and if the candidate's
    certification for that cycle was `DENIED`, the decision reopens: the
    certification returns to `PENDING` with `weighted_total_final` cleared to null."

    Design: Difficulty/non_linear_state_machine/component_submission_return_resubmit_retake_cycle
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)

    attempt1 = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    scored1 = score_portfolio_with_agreeing_reads(
        attempt1["id"], assessors[0], assessors[1], 2.00
    )
    assert scored1["status"] == SubmissionStatus.SCORED.value

    attempt2 = retake_submission(attempt1["id"], candidate)

    assert_submission(attempt2)
    assert attempt2["attempt_number"] == 2
    assert attempt2["prior_submission_id"] == attempt1["id"]
    assert attempt2["status"] == SubmissionStatus.IN_PROGRESS.value

    reread1 = validate_success(api.get_submission(attempt1["id"], BOARD))
    assert reread1["superseded"] is True
    assert attempt2["superseded"] is False


def test_submit_state_gate_precedes_window_gate(api):
    """PRD §2.8: "A submission-submit request checks the state gate
    (`ERR_SUBMISSION_NOT_SUBMITTABLE`) **before** any temporal rule, and among the
    composition gates the required-artifact check (`ERR_REQUIRED_ARTIFACT_MISSING`)
    fires **before** the release-form check (`ERR_RELEASE_FORM_MISSING`)."

    The attempt is in SCORING (state gate fails) AND the clock is past the window
    close (temporal gate would also fail): the response must be the 409 state
    error, never the 422 temporal error.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_gate_precedes_window_gate
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    set_logical_clock(PAST_WINDOW_CLOSE)

    response = api.submit_submission(
        submission["id"], make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTABLE)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.SCORING.value


def test_submit_window_gate_fires_when_state_gate_passes(api):
    """PRD §2.8: "A submission-submit request checks the state gate
    (`ERR_SUBMISSION_NOT_SUBMITTABLE`) **before** any temporal rule, and among the
    composition gates the required-artifact check (`ERR_REQUIRED_ARTIFACT_MISSING`)
    fires **before** the release-form check (`ERR_RELEASE_FORM_MISSING`)."
    PRD §3.3: "Then the cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), and the logical
    clock must fall within the half-open submission window, else
    `ERR_SUBMISSION_WINDOW_CLOSED` (HTTP 422)."

    Unshadowed control for the ordering claim: with the state gate satisfied
    (IN_PROGRESS), the closed window surfaces as the 422 temporal error.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_gate_precedes_window_gate
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    upload_minimal_portfolio_artifacts(submission["id"], candidate)
    set_logical_clock(PAST_WINDOW_CLOSE)

    response = api.submit_submission(
        submission["id"], make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)
    reread = validate_success(api.get_submission(submission["id"], BOARD))
    assert reread["status"] == SubmissionStatus.IN_PROGRESS.value

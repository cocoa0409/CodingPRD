"""Scoring assignments: target-shape and eligibility gates, conflict-of-interest
and read-segregation bars, the agreement/adjudication rule, the assessor selector
policy, and the suspension cascade."""
import pytest

from test_helpers import (
    BOARD,
    SCORING_ADMIN,
    ApiErrorId,
    AssessorStatus,
    AssignmentStatus,
    SubmissionStatus,
    assert_assignment,
    create_active_assessor,
    create_active_assessors,
    create_assignment_payload,
    create_default_benchmark,
    create_eligible_candidate,
    create_live_assignment,
    create_open_cycle,
    create_portfolio_submission_in_state,
    make_assessor_headers,
    set_logical_clock,
    submit_assignment_score,
    transition_assessor,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_CALIBRATION_CLOCK = "2027-01-11T00:00:00Z"


def _scoring_stage(api, num_assessors=2):
    """OPEN cycle + ELIGIBLE candidate (district D-100) + benchmark + ACTIVE
    assessors + one P1 attempt in SCORING. Returns dict of the pieces."""
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=num_assessors)
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    return {
        "cycle": cycle,
        "candidate": candidate,
        "benchmark": benchmark,
        "assessors": assessors,
        "submission": submission,
    }


def test_assignment_on_in_progress_submission_rejected(api):
    """PRD §3.6: "A live target submission must be in `SCORING` or
    `ADJUDICATION_REQUIRED`; anything else — including a request for a third read
    after reads 1 and 2 already agreed and finalized the attempt — is
    `ERR_SUBMISSION_NOT_SCORABLE` (HTTP 409)."

    Design: Corner/validations/assignment_on_in_progress_submission_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessor = create_active_assessor(benchmark["id"], home_district_code="D-900")
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="IN_PROGRESS"
    )

    response = api.create_assignment(
        create_assignment_payload(
            submission_id=submission["id"], assessor_id=assessor["id"]
        ),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_SCORABLE)


def test_conflict_of_interest_blocks_same_district_assessor(api):
    """PRD §3.6: "Two integrity bars then guard live assignments, each rejecting
    with HTTP 403. An assessor whose `home_district_code` equals the candidate's
    `district_code` may never hold a live assignment on that candidate's submission
    — that is `ERR_CONFLICT_OF_INTEREST`."

    The candidate's district_code is D-100; the assessor's home district matches.

    Design: Corner/validations/conflict_of_interest_blocks_same_district_assessor
    """
    stage = _scoring_stage(api)
    conflicted = create_active_assessor(
        stage["benchmark"]["id"], home_district_code="D-100"
    )

    response = api.create_assignment(
        create_assignment_payload(
            submission_id=stage["submission"]["id"], assessor_id=conflicted["id"]
        ),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_CONFLICT_OF_INTEREST)


def test_read_segregation_blocks_repeat_reader(api):
    """PRD §3.6: "And reads are segregated: the second read of a submission may not
    go to the assessor who took the first, and an adjudication read may not go to
    either earlier reader — a breach is `ERR_READ_SEGREGATION_VIOLATION`."

    Design: Corner/validations/read_segregation_blocks_repeat_reader
    """
    stage = _scoring_stage(api)
    r1, _r2 = stage["assessors"]
    first = create_live_assignment(stage["submission"]["id"], r1)
    submit_assignment_score(first["id"], r1, 2.50)

    response = api.create_assignment(
        create_assignment_payload(
            submission_id=stage["submission"]["id"], assessor_id=r1["id"]
        ),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_READ_SEGREGATION_VIOLATION)


def test_submit_score_off_grid_or_out_of_range_rejected(api):
    """PRD §2.6: "Every score in the system lives on a quarter-point grid within a
    fixed range: a valid score is at least 0.00, at most 4.00, and an exact
    multiple of 0.25. A score outside that range or off that grid is rejected with
    `ERR_SCORE_INVALID` (HTTP 422) wherever scores enter the system — booking
    completion, assignment score submission, and benchmark publication alike."

    2.13 is off the grid; 4.25 is above the range ceiling; the assignment is
    untouched by either rejection.

    Design: Corner/validations/submit_score_off_grid_or_out_of_range_rejected
    """
    stage = _scoring_stage(api, num_assessors=1)
    assessor = stage["assessors"][0]
    assignment = create_live_assignment(stage["submission"]["id"], assessor)
    headers = make_assessor_headers(assessor["id"])

    response_off_grid = api.submit_score(assignment["id"], {"score": 2.13}, headers)
    validate_error(response_off_grid, ApiErrorId.ERR_SCORE_INVALID)

    response_out_of_range = api.submit_score(assignment["id"], {"score": 4.25}, headers)
    validate_error(response_out_of_range, ApiErrorId.ERR_SCORE_INVALID)

    reread = validate_success(api.get_assignment(assignment["id"], SCORING_ADMIN))
    assert reread["status"] == AssignmentStatus.ASSIGNED.value
    assert reread["score"] is None


def test_assessor_cannot_submit_score_for_others_assignment(api):
    """PRD §3.6: "Scoring is the assessor's own act: they submit a `score` against
    their own assignment. The assignment must be `ASSIGNED`, else
    `ERR_ASSIGNMENT_NOT_SUBMITTABLE` (HTTP 409); the caller must be the
    assignment's assessor, else `ERR_NOT_RESOURCE_OWNER`; and the score must sit
    on the 0.25 grid within [0.00, 4.00], else `ERR_SCORE_INVALID`."

    Design: Corner/rbac/assessor_cannot_submit_score_for_others_assignment
    """
    stage = _scoring_stage(api)
    r1, r2 = stage["assessors"]
    assignment = create_live_assignment(stage["submission"]["id"], r1)

    response = api.submit_score(
        assignment["id"], {"score": 2.50}, make_assessor_headers(r2["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    reread = validate_success(api.get_assignment(assignment["id"], SCORING_ADMIN))
    assert reread["status"] == AssignmentStatus.ASSIGNED.value
    assert reread["score"] is None


def test_read_divergence_exactly_at_tolerance_averages(api):
    """PRD §3.6: "When the second read of a submission lands, the two scores are
    compared against a divergence tolerance of 0.50. If the reads sit within 0.50
    of each other — the boundary is inclusive — the attempt's `final_score` is the
    mean of the two reads rounded half up to 2 decimal places, both read
    assignments transition to `FINALIZED`, and the attempt becomes `SCORED`."

    |3.00 - 3.50| == 0.50 exactly: agreement path, final 3.25.

    Design: Corner/calculations/read_divergence_exactly_at_tolerance_averages
    """
    stage = _scoring_stage(api)
    r1, r2 = stage["assessors"]
    submission = stage["submission"]

    first = create_live_assignment(submission["id"], r1)
    submit_assignment_score(first["id"], r1, 3.00)
    second = create_live_assignment(submission["id"], r2)
    submit_assignment_score(second["id"], r2, 3.50)

    reread1 = validate_success(api.get_assignment(first["id"], SCORING_ADMIN))
    reread2 = validate_success(api.get_assignment(second["id"], SCORING_ADMIN))
    assert reread1["status"] == AssignmentStatus.FINALIZED.value
    assert reread2["status"] == AssignmentStatus.FINALIZED.value

    scored = validate_success(api.get_submission(submission["id"], BOARD))
    assert scored["status"] == SubmissionStatus.SCORED.value
    assert scored["final_score"] == pytest.approx(3.25)


def test_read_divergence_beyond_tolerance_requires_adjudication(api):
    """PRD §3.6: "If the reads differ by more than 0.50, the attempt instead moves
    to `ADJUDICATION_REQUIRED`, reads 1 and 2 remain `SCORE_SUBMITTED`, and the
    read-3 assignment becomes creatable. When the adjudication read lands, the
    attempt takes the adjudicator's score as its `final_score` — no averaging —
    and all three reads transition to `FINALIZED`."

    |3.00 - 3.75| == 0.75 > 0.50: a third assessor adjudicates at 3.25.

    Design: Corner/calculations/read_divergence_beyond_tolerance_requires_adjudication
    """
    stage = _scoring_stage(api, num_assessors=3)
    r1, r2, r3 = stage["assessors"]
    submission = stage["submission"]

    first = create_live_assignment(submission["id"], r1)
    submit_assignment_score(first["id"], r1, 3.00)
    second = create_live_assignment(submission["id"], r2)
    submit_assignment_score(second["id"], r2, 3.75)

    flagged = validate_success(api.get_submission(submission["id"], BOARD))
    assert flagged["status"] == SubmissionStatus.ADJUDICATION_REQUIRED.value

    adjudication = validate_created(
        api.create_assignment(
            create_assignment_payload(
                submission_id=submission["id"], assessor_id=r3["id"]
            ),
            SCORING_ADMIN,
        )
    )
    assert_assignment(adjudication)
    assert adjudication["read_number"] == 3

    submit_assignment_score(adjudication["id"], r3, 3.25)

    scored = validate_success(api.get_submission(submission["id"], BOARD))
    assert scored["status"] == SubmissionStatus.SCORED.value
    assert scored["final_score"] == pytest.approx(3.25)

    for assignment in (first, second, adjudication):
        reread = validate_success(api.get_assignment(assignment["id"], SCORING_ADMIN))
        assert reread["status"] == AssignmentStatus.FINALIZED.value


def test_selector_least_loaded_then_earliest_calibrated(api):
    """PRD §3.6: "Survivors rank by `open_assignment_count` ascending; ties break
    toward the earlier `calibrated_at`, and any remaining tie breaks toward the
    earlier `created_at` — a total, deterministic order in which random ids never
    participate."

    RA (calibrated 2027-01-10) is pre-loaded with one open read on P1; RB is
    calibrated a day later. The P2 auto-assignment picks the less-loaded RB
    (0 < 1); the P3 auto-assignment then ties 1-1 and breaks toward RA's earlier
    calibrated_at.

    Design: Corner/cross-cutting complexity layers/selector_least_loaded_then_earliest_calibrated
    """
    cycle = create_open_cycle()  # work clock 2027-01-10
    benchmark = create_default_benchmark()
    ra = create_active_assessor(benchmark["id"], home_district_code="D-900")
    set_logical_clock(SECOND_CALIBRATION_CLOCK)
    rb = create_active_assessor(benchmark["id"], home_district_code="D-901")

    ra_record = validate_success(api.get_assessor(ra["id"], SCORING_ADMIN))
    rb_record = validate_success(api.get_assessor(rb["id"], SCORING_ADMIN))
    assert ra_record["calibrated_at"] is not None
    assert rb_record["calibrated_at"] is not None

    candidate = create_eligible_candidate()
    sub_p1 = create_portfolio_submission_in_state(cycle["id"], candidate, "P1", state="SCORING")
    sub_p2 = create_portfolio_submission_in_state(cycle["id"], candidate, "P2", state="SCORING")
    sub_p3 = create_portfolio_submission_in_state(cycle["id"], candidate, "P3", state="SCORING")

    # Pre-load RA with one open assignment on P1.
    loaded = create_live_assignment(sub_p1["id"], ra)
    assert loaded["status"] == AssignmentStatus.ASSIGNED.value

    auto_p2 = validate_created(
        api.create_assignment(
            create_assignment_payload(submission_id=sub_p2["id"]), SCORING_ADMIN
        )
    )
    assert auto_p2["assessor_id"] == rb["id"], (
        "open_assignment_count 0 must beat 1 in selector ranking"
    )
    assert auto_p2["read_number"] == 1
    assert auto_p2["status"] == AssignmentStatus.ASSIGNED.value

    auto_p3 = validate_created(
        api.create_assignment(
            create_assignment_payload(submission_id=sub_p3["id"]), SCORING_ADMIN
        )
    )
    assert auto_p3["assessor_id"] == ra["id"], (
        "at 1-1 the earlier calibrated_at (RA, a day before RB) wins the tie"
    )
    assert auto_p3["read_number"] == 1
    assert auto_p3["status"] == AssignmentStatus.ASSIGNED.value


def test_selector_empty_pool_returns_no_eligible_assessor(api):
    """PRD §3.6: "The eligibility filter requires every one of: the assessor is
    `ACTIVE`; their `home_district_code` differs from the submission candidate's
    `district_code`; and they hold no existing assignment on this submission in
    `ASSIGNED`, `SCORE_SUBMITTED`, or `FINALIZED` status."
    PRD §3.6: "An empty eligible pool fails creation with
    `ERR_NO_ELIGIBLE_ASSESSOR` (HTTP 409)."

    The only ACTIVE assessor shares the candidate's district, so the pool is empty.

    Design: Corner/cross-cutting complexity layers/selector_empty_pool_returns_no_eligible_assessor
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()  # district D-100
    benchmark = create_default_benchmark()
    create_active_assessor(benchmark["id"], home_district_code="D-100")
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )

    response = api.create_assignment(
        create_assignment_payload(submission_id=submission["id"]), SCORING_ADMIN
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ASSESSOR)


def test_assignment_target_ambiguous_shadows_conflict(api):
    """PRD §2.8: "An assignment-creation request checks target ambiguity
    (`ERR_ASSIGNMENT_TARGET_AMBIGUOUS`) **before** conflict-of-interest."
    PRD §3.6: "Exactly one of the two may be non-null — supplying neither or both
    is `ERR_ASSIGNMENT_TARGET_AMBIGUOUS` (HTTP 422), and per §2.8 this ambiguity
    check runs before any conflict-of-interest test."

    The request carries BOTH targets for an assessor who would also trip the
    same-district bar; the 422 ambiguity error must answer, and no assignment row
    may be created.

    Design: Difficulty/priority_pair_validation_conflict/assignment_target_constraint_precedes_conflict_safety
    """
    stage = _scoring_stage(api)
    conflicted = create_active_assessor(
        stage["benchmark"]["id"], home_district_code="D-100"
    )

    response = api.create_assignment(
        create_assignment_payload(
            submission_id=stage["submission"]["id"],
            benchmark_id=stage["benchmark"]["id"],
            assessor_id=conflicted["id"],
        ),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_TARGET_AMBIGUOUS)
    _rows, meta = validate_paginated(
        api.list_assignments(
            BOARD, params={"submission_id": stage["submission"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_conflict_of_interest_fires_when_target_unambiguous(api):
    """PRD §2.8: "An assignment-creation request checks target ambiguity
    (`ERR_ASSIGNMENT_TARGET_AMBIGUOUS`) **before** conflict-of-interest."
    PRD §3.6: "An assessor whose `home_district_code` equals the candidate's
    `district_code` may never hold a live assignment on that candidate's submission
    — that is `ERR_CONFLICT_OF_INTEREST`."

    Unshadowed control for the ordering claim: with a well-formed single target,
    the same-district bar surfaces as the 403 safety error.

    Design: Difficulty/priority_pair_validation_conflict/assignment_target_constraint_precedes_conflict_safety
    """
    stage = _scoring_stage(api)
    conflicted = create_active_assessor(
        stage["benchmark"]["id"], home_district_code="D-100"
    )

    response = api.create_assignment(
        create_assignment_payload(
            submission_id=stage["submission"]["id"], assessor_id=conflicted["id"]
        ),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_CONFLICT_OF_INTEREST)


def test_suspension_reassigns_open_assignments(api):
    """PRD §3.5: "Suspension cascades, whatever its cause. Every scoring
    assignment the assessor still holds in `ASSIGNED` status flips to `REASSIGNED`;
    for each affected submission the missing reads become re-assignable, and the
    assessor's `open_assignment_count` — the count of their assignments in
    `ASSIGNED` or `SCORE_SUBMITTED`, and the selector's primary ranking key (§3.6)
    — refreshes accordingly."
    PRD §3.5: "An administrator may also suspend an `ACTIVE` assessor directly
    through the ladder."

    R1 holds open read-1 assignments on two submissions; the suspension flips
    both and zeroes his open count.

    Design: Difficulty/transitive_cascade/assessor_suspension_cascades_to_reassignment
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    r1, _r2 = create_active_assessors(benchmark["id"], count=2)

    sub_p1 = create_portfolio_submission_in_state(cycle["id"], candidate, "P1", state="SCORING")
    sub_p2 = create_portfolio_submission_in_state(cycle["id"], candidate, "P2", state="SCORING")
    asg_p1 = create_live_assignment(sub_p1["id"], r1)
    asg_p2 = create_live_assignment(sub_p2["id"], r1)
    before = validate_success(api.get_assessor(r1["id"], SCORING_ADMIN))
    assert before["open_assignment_count"] == 2

    transition_assessor(r1["id"], "SUSPENDED")

    for asg in (asg_p1, asg_p2):
        reread = validate_success(api.get_assignment(asg["id"], SCORING_ADMIN))
        assert reread["status"] == AssignmentStatus.REASSIGNED.value
    after = validate_success(api.get_assessor(r1["id"], SCORING_ADMIN))
    assert after["status"] == AssessorStatus.SUSPENDED.value
    assert after["open_assignment_count"] == 0


def test_reassigned_read_slot_reopens_with_read_number_one(api):
    """PRD §3.5: "Suspension cascades, whatever its cause. Every scoring
    assignment the assessor still holds in `ASSIGNED` status flips to `REASSIGNED`;
    for each affected submission the missing reads become re-assignable, and the
    assessor's `open_assignment_count` — the count of their assignments in
    `ASSIGNED` or `SCORE_SUBMITTED`, and the selector's primary ranking key (§3.6)
    — refreshes accordingly."
    PRD §3.6: "However the assessor is chosen, creation computes `read_number` — 1
    for the first live read of a submission, 2 for the second blind read, 3 for the
    adjudication read which is creatable only while the submission sits in
    `ADJUDICATION_REQUIRED`; calibration reads number sequentially per assessor —
    and increments the assessor's `open_assignment_count`."

    The read slot lost to the suspension is the missing one, so the replacement
    assignment is computed as read 1 again and the submission stays in SCORING.

    Design: Difficulty/transitive_cascade/assessor_suspension_cascades_to_reassignment
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    r1, r2 = create_active_assessors(benchmark["id"], count=2)

    sub_p1 = create_portfolio_submission_in_state(cycle["id"], candidate, "P1", state="SCORING")
    create_live_assignment(sub_p1["id"], r1)
    transition_assessor(r1["id"], "SUSPENDED")

    replacement = validate_created(
        api.create_assignment(
            create_assignment_payload(
                submission_id=sub_p1["id"], assessor_id=r2["id"]
            ),
            SCORING_ADMIN,
        )
    )
    assert_assignment(replacement)
    assert replacement["read_number"] == 1
    assert replacement["status"] == AssignmentStatus.ASSIGNED.value

    submission = validate_success(api.get_submission(sub_p1["id"], BOARD))
    assert submission["status"] == SubmissionStatus.SCORING.value, (
        "reassignment must not regress the submission's state"
    )

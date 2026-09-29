"""Parallel dimensions on a placement, and a bounded loop on an assessment.

A placement carries a clinical lifecycle and a money lifecycle that advance on
different endpoints and must not disturb one another.  An assessment genuinely
revisits `SUBMITTED`, and the only thing that bounds that loop is `attempt_no`,
which submission raises and a return never touches.
"""
from test_helpers import (
    ASSESSMENT_SCORER,
    DEFAULT_CYCLE_PLAN,
    ERR_ASSESSMENT_ATTEMPTS_EXHAUSTED,
    PLACEMENT_COORDINATOR,
    PLACEMENT_COORDINATOR_USER_ID,
    PROGRAM_ADMIN,
    SUBMISSION_CLOCK,
    assert_agreement_ledger,
    assert_caseload,
    assert_instant_equals,
    assert_placement_dimensions,
    assert_stipend,
    complete_cycle,
    factories as f,
    open_assessment,
    read_agreement,
    read_assessment,
    read_placement,
    read_supervisor,
    set_clock,
    setup_active_placement,
    setup_scheduled_cycles,
    submit_assessment,
    validate_error,
    validate_success,
)


def _approved_active_placement(api):
    """An active placement whose money dimension has moved on to APPROVED."""
    scenario = setup_active_placement(api)
    validate_success(api.transition_stipend(
        scenario.placement_id, f.stipend_transition_payload("APPROVED"),
        PROGRAM_ADMIN))
    return scenario


def _assessment_on_its_first_submission(api):
    """An active placement with two of three cycles observed and one submission."""
    scenario = setup_active_placement(api)
    setup_scheduled_cycles(api, scenario)
    for index in (0, 1):
        complete_cycle(api, scenario.cycles[index]["id"], scenario.supervisor_id,
                       DEFAULT_CYCLE_PLAN[index][4], DEFAULT_CYCLE_PLAN[index][5])
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)
    scenario.assessment = submit_assessment(api, scenario.assessment_id,
                                            scenario.candidate_id)
    return scenario


def test_a_removal_request_leaves_the_approved_stipend_exactly_where_it_was(api):
    """The clinical move to REMOVAL_PENDING does not touch the money dimension.

    PRD §2.13: "A `Placement` carries two: `placement_status` is the clinical
    lifecycle and starts at `PROPOSED`, and `stipend_status` is the money
    lifecycle and starts at `NOT_ACCRUED`. They advance on different
    endpoints."  PRD §3.9: "The money dimension is deliberately left alone: an
    `ACCRUED` or `APPROVED` stipend stays exactly where it is until somebody
    decides the case."

    Design: Difficulty/non_linear_state_machine/placement_clinical_and_money_dimensions_advance_independently
    """
    scenario = _approved_active_placement(api)
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "ACTIVE", "APPROVED")

    pended = validate_success(api.request_removal(
        scenario.placement_id, f.removal_request_payload(),
        PLACEMENT_COORDINATOR))

    assert_placement_dimensions(pended, "REMOVAL_PENDING", "APPROVED")
    assert pended["removal_reason"] == "CANDIDATE_PERFORMANCE"
    assert pended["removal_requested_by_user_id"] == PLACEMENT_COORDINATOR_USER_ID
    assert_stipend(pended, variant="PROVISIONAL", weekly_cents=12962,
                   weeks_credited=14, gross_cents=181468)


def test_only_the_clinical_stage_feeds_the_caseload_and_the_seat_ledger(api):
    """REMOVAL_PENDING costs 4 caseload points and still occupies its seat.

    PRD §3.4: "A supervisor based at the grid origin covering a site 20 grid
    miles away therefore carries 2 points for a single proposed placement, 3
    points once it is confirmed, and 4 points while a removal is pending on it
    — a placement gets *more* expensive as it goes wrong".  PRD §2.9:
    "`seats_committed` is the count of those whose `placement_status` is
    `ACTIVE`, `REMOVAL_PENDING` or `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/placement_clinical_and_money_dimensions_advance_independently
    """
    scenario = _approved_active_placement(api)
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 3)

    validate_success(api.request_removal(
        scenario.placement_id, f.removal_request_payload(),
        PLACEMENT_COORDINATOR))

    assert_caseload(read_supervisor(api, scenario.supervisor_id), 4,
                    max_caseload_points=24)
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=181468,
                            capacity_posture="CAP_REACHED")


def test_the_return_loop_revisits_submitted_and_only_submission_counts(api):
    """Two submissions and one return leave attempt_no at 2, not 3.

    PRD §3.8: "A successful submission moves the assessment `OPEN → SUBMITTED`
    on the first pass or `RETURNED → SUBMITTED` on a resubmission, raises
    `attempt_no` by one — from 0 to 1, then from 1 to 2 — and records
    `artifact_reference` and `submitted_at`. It is the *submission* that
    consumes an attempt, never the scoring."

    Design: Difficulty/non_linear_state_machine/assessment_submitted_returned_loop_is_bounded_by_the_attempt_counter
    """
    scenario = _assessment_on_its_first_submission(api)
    assert scenario.assessment["status"] == "SUBMITTED"
    assert scenario.assessment["attempt_no"] == 1

    returned = validate_success(api.score_assessment(
        scenario.assessment_id, f.assessment_return_payload(), ASSESSMENT_SCORER))
    assert returned["status"] == "RETURNED"
    assert returned["attempt_no"] == 1, "a return never consumes an attempt"
    assert returned["submitted_at"] is None
    assert returned["total_score"] == 0
    assert_instant_equals(returned["window_closes_at"], "2026-12-08T00:00:00Z",
                          "window_closes_at")

    resubmitted = submit_assessment(api, scenario.assessment_id,
                                    scenario.candidate_id,
                                    artifact_reference="portfolio-v2")
    assert resubmitted["status"] == "SUBMITTED", "the loop revisited SUBMITTED"
    assert resubmitted["attempt_no"] == 2


def test_the_second_return_is_refused_once_the_attempts_are_exhausted(api):
    """The RETURN edge closes when attempt_no reaches 2.

    PRD §3.8: "A `RETURN` sends the portfolio back for one revision: it
    requires `attempt_no` to be strictly below 2, since on the final attempt a
    weak portfolio must be failed rather than returned, and a `RETURN` issued
    when `attempt_no` already equals 2 is refused with
    `ERR_ASSESSMENT_ATTEMPTS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/assessment_submitted_returned_loop_is_bounded_by_the_attempt_counter
    """
    scenario = _assessment_on_its_first_submission(api)
    validate_success(api.score_assessment(
        scenario.assessment_id, f.assessment_return_payload(), ASSESSMENT_SCORER))
    submit_assessment(api, scenario.assessment_id, scenario.candidate_id,
                      artifact_reference="portfolio-v2")

    validate_error(api.score_assessment(
        scenario.assessment_id,
        f.assessment_return_payload(
            returned_feedback="Still needs more evidence of differentiation."),
        ASSESSMENT_SCORER),
        ERR_ASSESSMENT_ATTEMPTS_EXHAUSTED, 409)

    unchanged = read_assessment(api, scenario.assessment_id)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["attempt_no"] == 2
    assert_instant_equals(unchanged["window_closes_at"], "2026-12-08T00:00:00Z",
                          "window_closes_at")
    assert read_placement(api, scenario.placement_id)["placement_status"] == (
        "ACTIVE"), "a refused assessment transition leaves the placement alone"

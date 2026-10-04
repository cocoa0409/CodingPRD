"""The assessor pipeline: training ladder, calibration counters and tolerance
boundary, retraining reset, and the ACTIVE gate on live scoring."""
from datetime import datetime

from test_helpers import (
    BOARD,
    SCORING_ADMIN,
    STANDARD_WORK_CLOCK,
    ApiErrorId,
    AssessorStatus,
    AssignmentStatus,
    assert_assignment,
    assert_assessor,
    create_assignment_payload,
    create_benchmark_payload,
    create_default_benchmark,
    create_eligible_candidate,
    create_open_cycle,
    create_portfolio_submission_in_state,
    create_recruited_assessor,
    make_assessor_headers,
    set_logical_clock,
    submit_calibration_read,
    transition_assessor,
    validate_created,
    validate_error,
    validate_success,
)

RECALIBRATION_CLOCK = "2027-01-12T00:00:00Z"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _walk_to_calibrating(assessor: dict) -> dict:
    transition_assessor(assessor["id"], "IN_TRAINING")
    return transition_assessor(assessor["id"], "CALIBRATING")


def test_assessor_skip_training_rejected(api):
    """PRD §3.5: "From there the administrator walks the training ladder by naming
    a target `to`: `RECRUITED` to `IN_TRAINING`, `IN_TRAINING` to `CALIBRATING`,
    and — once calibration succeeds — `CALIBRATED` to `ACTIVE`, the only status
    eligible for live scoring."
    PRD §3.5: "Any transition request outside the declared ladder — including
    direct requests for those system-only moves — is rejected with
    `ERR_INVALID_ASSESSOR_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/assessor_skip_training_rejected
    """
    assessor = create_recruited_assessor()

    response = api.transition_assessor(assessor["id"], {"to": "CALIBRATING"}, SCORING_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_ASSESSOR_TRANSITION)
    reread = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert reread["status"] == AssessorStatus.RECRUITED.value


def test_assessor_cannot_create_benchmarks(api):
    """PRD §2.1: "If the presented role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §3.6: "A `ScoringAdministrator` publishes each benchmark with the
    `component_code` it exemplifies, a free-text `content_domain` descriptor, a
    panel-blessed `known_score` on the standard grid (§2.6, else
    `ERR_SCORE_INVALID`), and an optional `tolerance` defaulting to 0.25 — the pass
    band for calibration reads against it."

    Design: Corner/rbac/assessor_cannot_create_benchmarks
    """
    assessor = create_recruited_assessor()

    response = api.create_benchmark(
        create_benchmark_payload(), make_assessor_headers(assessor["id"])
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_board_admin_cannot_transition_assessor(api):
    """PRD §2.1: "If the presented role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: the assessor-transition row authorizes `ScoringAdministrator` only.

    Design: Corner/rbac/board_admin_cannot_transition_assessor
    """
    assessor = create_recruited_assessor()

    response = api.transition_assessor(assessor["id"], {"to": "IN_TRAINING"}, BOARD)

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    reread = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert reread["status"] == AssessorStatus.RECRUITED.value


def test_calibration_tolerance_boundary_inclusive(api):
    """PRD §3.5: "A calibration read passes when its distance from the benchmark's
    `known_score` is within the benchmark's `tolerance` — the boundary is
    inclusive, so a read exactly `tolerance` away from the known score passes — and
    the verdict is recorded as the assignment's `is_within_tolerance`. Each passing
    read increments the assessor's `calibration_passes`, and when that counter
    reaches 2 the assessor auto-transitions from `CALIBRATING` to `CALIBRATED`,
    stamping `calibrated_at` from the logical clock. Each failing read increments
    `calibration_failures`, and when that counter reaches 3 the assessor
    auto-transitions to `SUSPENDED`."

    Known score 3.00, default tolerance 0.25: 3.50 fails (0.50 > 0.25), 3.25 and
    2.75 pass (exactly 0.25 away, inclusive), and the second pass auto-calibrates.

    Design: Corner/calculations/calibration_tolerance_boundary_inclusive
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    benchmark = create_default_benchmark()  # known_score 3.00, tolerance 0.25
    assessor = create_recruited_assessor()
    _walk_to_calibrating(assessor)

    failed_read = submit_calibration_read(benchmark["id"], assessor, 3.50)
    assert failed_read["is_within_tolerance"] is False
    assert failed_read["status"] == AssignmentStatus.FINALIZED.value

    boundary_high = submit_calibration_read(benchmark["id"], assessor, 3.25)
    assert boundary_high["is_within_tolerance"] is True

    boundary_low = submit_calibration_read(benchmark["id"], assessor, 2.75)
    assert boundary_low["is_within_tolerance"] is True

    reread = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert_assessor(reread)
    assert reread["calibration_failures"] == 1
    assert reread["calibration_passes"] == 2
    assert reread["status"] == AssessorStatus.CALIBRATED.value


def test_calibration_fail_stays_calibrating_then_two_passes_calibrate(api):
    """PRD §3.5: "Each passing read increments the assessor's `calibration_passes`,
    and when that counter reaches 2 the assessor auto-transitions from
    `CALIBRATING` to `CALIBRATED`, stamping `calibrated_at` from the logical clock.
    Each failing read increments `calibration_failures`, and when that counter
    reaches 3 the assessor auto-transitions to `SUSPENDED`."

    A single failure (0.00 vs known 3.00) leaves the assessor CALIBRATING; two
    in-tolerance reads then auto-transition to CALIBRATED, stamped from the
    logical clock.

    Design: Difficulty/non_linear_state_machine/assessor_training_calibration_retraining_cycle
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    benchmark = create_default_benchmark()
    assessor = create_recruited_assessor()
    _walk_to_calibrating(assessor)

    failed = submit_calibration_read(benchmark["id"], assessor, 0.00)
    assert failed["is_within_tolerance"] is False
    mid = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert mid["calibration_failures"] == 1
    assert mid["calibration_passes"] == 0
    assert mid["status"] == AssessorStatus.CALIBRATING.value

    submit_calibration_read(benchmark["id"], assessor, 3.00)
    submit_calibration_read(benchmark["id"], assessor, 3.25)

    done = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert done["calibration_passes"] == 2
    assert done["calibration_failures"] == 1
    assert done["status"] == AssessorStatus.CALIBRATED.value
    assert _parse_iso(done["calibrated_at"]) == _parse_iso(STANDARD_WORK_CLOCK)


def test_suspended_retraining_resets_counters_and_recalibrates(api):
    """PRD §3.5: "A `SUSPENDED` assessor may be returned to `IN_TRAINING`, and that
    retraining move resets both `calibration_passes` and `calibration_failures` to
    0."
    PRD §3.5: "Each passing read increments the assessor's `calibration_passes`,
    and when that counter reaches 2 the assessor auto-transitions from
    `CALIBRATING` to `CALIBRATED`, stamping `calibrated_at` from the logical clock."
    PRD §3.5: "An administrator may also suspend an `ACTIVE` assessor directly
    through the ladder."

    The full loop: ACTIVE -> SUSPENDED -> IN_TRAINING (counters reset) ->
    CALIBRATING -> CALIBRATED (calibrated_at refreshed to the new clock) ->
    ACTIVE.

    Design: Difficulty/non_linear_state_machine/assessor_training_calibration_retraining_cycle
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    benchmark = create_default_benchmark()
    assessor = create_recruited_assessor()
    _walk_to_calibrating(assessor)
    submit_calibration_read(benchmark["id"], assessor, 3.00)
    submit_calibration_read(benchmark["id"], assessor, 3.25)
    transition_assessor(assessor["id"], "ACTIVE")
    transition_assessor(assessor["id"], "SUSPENDED")

    retrained = transition_assessor(assessor["id"], "IN_TRAINING")
    assert retrained["calibration_passes"] == 0
    assert retrained["calibration_failures"] == 0

    set_logical_clock(RECALIBRATION_CLOCK)
    transition_assessor(assessor["id"], "CALIBRATING")
    submit_calibration_read(benchmark["id"], assessor, 3.00)
    submit_calibration_read(benchmark["id"], assessor, 3.00)

    recalibrated = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert recalibrated["status"] == AssessorStatus.CALIBRATED.value
    assert _parse_iso(recalibrated["calibrated_at"]) == _parse_iso(RECALIBRATION_CLOCK)

    reactivated = transition_assessor(assessor["id"], "ACTIVE")
    assert reactivated["status"] == AssessorStatus.ACTIVE.value


def test_calibrating_assessor_rejected_for_live_read(api):
    """PRD §3.6: "The assigned assessor must be `ACTIVE` for a live target or
    `CALIBRATING` for a benchmark target, else `ERR_ASSESSOR_NOT_SCORING_ELIGIBLE`
    (HTTP 409)."

    While CALIBRATING the assessor is refused for live scoring but can take
    benchmark calibration reads.

    Design: Difficulty/cross_entity_state_dependency/live_assignment_blocked_until_assessor_active
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    benchmark = create_default_benchmark()
    assessor = create_recruited_assessor()
    _walk_to_calibrating(assessor)

    response = api.create_assignment(
        create_assignment_payload(submission_id=submission["id"], assessor_id=assessor["id"]),
        SCORING_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_ASSESSOR_NOT_SCORING_ELIGIBLE)

    # The same assessor in CALIBRATING may take calibration reads.
    read1 = submit_calibration_read(benchmark["id"], assessor, 3.00)
    read2 = submit_calibration_read(benchmark["id"], assessor, 3.25)
    assert read1["status"] == AssignmentStatus.FINALIZED.value
    assert read2["status"] == AssignmentStatus.FINALIZED.value
    calibrated = validate_success(api.get_assessor(assessor["id"], SCORING_ADMIN))
    assert calibrated["status"] == AssessorStatus.CALIBRATED.value


def test_active_assessor_accepts_live_read_with_read_number_one(api):
    """PRD §3.6: "The assigned assessor must be `ACTIVE` for a live target or
    `CALIBRATING` for a benchmark target, else `ERR_ASSESSOR_NOT_SCORING_ELIGIBLE`
    (HTTP 409)."
    PRD §3.6: "However the assessor is chosen, creation computes `read_number` — 1
    for the first live read of a submission, 2 for the second blind read, 3 for the
    adjudication read which is creatable only while the submission sits in
    `ADJUDICATION_REQUIRED`; calibration reads number sequentially per assessor —
    and increments the assessor's `open_assignment_count`. The new assignment
    starts `ASSIGNED`."

    Once the ladder reaches ACTIVE, the same assessor is admitted to live scoring.

    Design: Difficulty/cross_entity_state_dependency/live_assignment_blocked_until_assessor_active
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_portfolio_submission_in_state(
        cycle["id"], candidate, "P1", state="SCORING"
    )
    benchmark = create_default_benchmark()
    assessor = create_recruited_assessor()
    _walk_to_calibrating(assessor)
    submit_calibration_read(benchmark["id"], assessor, 3.00)
    submit_calibration_read(benchmark["id"], assessor, 3.25)
    transition_assessor(assessor["id"], "ACTIVE")

    assignment = validate_created(
        api.create_assignment(
            create_assignment_payload(
                submission_id=submission["id"], assessor_id=assessor["id"]
            ),
            SCORING_ADMIN,
        )
    )

    assert_assignment(assignment)
    assert assignment["read_number"] == 1
    assert assignment["status"] == AssignmentStatus.ASSIGNED.value
    assert assignment["submission_id"] == submission["id"]

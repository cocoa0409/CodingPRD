"""Non-linear machines: the student's two independent status axes, and the
attempt's revision loop with its fork into adjudication.
"""
from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.factories import dimension_score, rubric_dimension

TWO_EQUAL_DIMENSIONS = [
    rubric_dimension("D1", 0.5000, 100, False),
    rubric_dimension("D2", 0.5000, 100, False),
]


def test_a_failing_checkpoint_dismisses_the_progress_axis_while_enrollment_stays_suspended():
    """Suspension moves only the enrollment axis; a zero-pace checkpoint then
    moves only the progress axis, all the way to its terminal value.

    PRD: "Suspension deliberately leaves `sap_status` untouched."

    Design: Difficulty/non_linear_state_machine/student_parallel_enrollment_and_sap_axes
    """
    ctx = fx.base_chain()

    suspended = fx.suspend_student(ctx["student"]["id"], reason="Cadence non-response")
    assert suspended["enrollment_status"] == "SUSPENDED"
    assert suspended["sap_status"] == "GOOD_STANDING"

    review = fx.create_sap_review(ctx["student"]["id"], ctx["term"]["id"])
    assert review["terms_counted"] == 1
    assert review["expected_units"] == 12
    A.assert_number_equals(review["pace_pct"], 0.00, "pace_pct")
    assert review["pace_band"] == "FAIL"
    assert review["previous_sap_status"] == "GOOD_STANDING"
    assert review["new_sap_status"] == "DISMISSED"

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["enrollment_status"] == "SUSPENDED"
    assert student["sap_status"] == "DISMISSED"


def test_reinstatement_restores_enrollment_and_leaves_the_dismissed_progress_axis_alone():
    """The two axes are genuinely independent: reinstatement walks enrollment back
    to ACTIVE and does not undo the progress dismissal.

    PRD: "Reinstatement moves a suspended student back to `ACTIVE`, but only when
    no integrity case for that student is `OPEN` or `UNDER_INVESTIGATION`; it
    leaves `suspended_at_utc` in place as the historical record and leaves
    `sap_status` exactly where it was, and increments `version`."

    Design: Difficulty/non_linear_state_machine/student_parallel_enrollment_and_sap_axes
    """
    ctx = fx.base_chain()
    fx.suspend_student(ctx["student"]["id"], reason="Cadence non-response")
    fx.create_sap_review(ctx["student"]["id"], ctx["term"]["id"])

    reinstated = fx.reinstate_student(ctx["student"]["id"])
    assert reinstated["enrollment_status"] == "ACTIVE"
    assert reinstated["sap_status"] == "DISMISSED"
    A.assert_instant_present(reinstated["suspended_at_utc"], "suspended_at_utc")


def _capstone_with_three_readers():
    """A submitted capstone attempt on a two-reader rubric, with a third
    independent reader standing by, and reader one's score already on file."""
    ctx = fx.two_reader_scenario(
        competency_overrides={"code": "IT-301", "title": "Capstone Architecture",
                              "unit_value": 4, "level": "CAPSTONE"},
        blueprint_dimensions=TWO_EQUAL_DIMENSIONS,
    )
    ctx["evaluator_three"] = fx.create_evaluator(
        full_name="Reader Three", email="r3@example.edu", certification_level="SENIOR"
    )
    ctx["first_score"] = fx.record_score(
        ctx["attempt"]["id"], ctx["evaluator_one"]["id"],
        [dimension_score("D1", 82), dimension_score("D2", 82)],
    )
    return ctx


def test_the_revision_loop_voids_the_score_and_returns_the_attempt_to_draft():
    """UNDER_REVIEW to REVISION_REQUESTED to DRAFT to UNDER_REVIEW is a genuine
    loop: the score on file is voided, the counters reset, and the lap is visible
    only as revision_count.

    PRD: "Requesting revision on an attempt in `UNDER_REVIEW` or `ADJUDICATION`,
    with a `reason`, moves it to `REVISION_REQUESTED` and has one identical
    side-effect set from either origin: every submitted score on the attempt is
    voided with `voided_reason` `REVISION_REQUESTED`, `scores_received_count`
    resets to 0, `final_score_pct` and `score_variant` reset to null,
    `is_provisional_score` and `critical_fail` reset to false, `revision_count`
    increments by one, and the reliability figures of every affected evaluator are
    recomputed — which can itself lift or lower an evaluator's standing basis,
    since the voided pair leaves the denominator."

    Design: Difficulty/non_linear_state_machine/attempt_revision_cycle_and_adjudication_branch
    """
    ctx = _capstone_with_three_readers()

    sent_back = fx.request_revision(
        ctx["attempt"]["id"], ctx["evaluator_one"]["id"],
        reason="Artifact missing the threat model section",
    )
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["revision_count"] == 1
    assert sent_back["scores_received_count"] == 0
    assert sent_back["final_score_pct"] is None
    assert sent_back["score_variant"] is None
    assert sent_back["is_provisional_score"] is False

    voided = fx.refresh_score(ctx["first_score"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "REVISION_REQUESTED"

    reopened = fx.reopen_attempt(ctx["attempt"]["id"], ctx["student"]["id"])
    assert reopened["status"] == "DRAFT"

    resubmitted = fx.submit_attempt(ctx["attempt"]["id"], ctx["student"]["id"],
                                    artifact_hash="sha256:it301-b")
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["revision_count"] == 1


def test_the_second_lap_forks_into_adjudication_when_the_readers_diverge():
    """After the loop, a twelve-point spread exceeds the five-point tolerance, so
    the provisional figure vanishes and the attempt forks to ADJUDICATION with two
    submitted scores on file.

    PRD: "A difference strictly greater than the tolerance is disagreement, and
    the attempt moves from `UNDER_REVIEW` to `ADJUDICATION`; `final_score_pct` is
    cleared back to null, `is_provisional_score` is set to false, and
    `score_variant` is cleared to null."

    Design: Difficulty/non_linear_state_machine/attempt_revision_cycle_and_adjudication_branch
    """
    ctx = _capstone_with_three_readers()
    fx.request_revision(ctx["attempt"]["id"], ctx["evaluator_one"]["id"],
                        reason="Artifact missing the threat model section")
    fx.reopen_attempt(ctx["attempt"]["id"], ctx["student"]["id"])
    fx.submit_attempt(ctx["attempt"]["id"], ctx["student"]["id"],
                      artifact_hash="sha256:it301-b")

    high = fx.record_score(ctx["attempt"]["id"], ctx["evaluator_two"]["id"],
                           [dimension_score("D1", 88), dimension_score("D2", 88)])
    A.assert_number_equals(high["weighted_score_pct"], 88.00, "weighted_score_pct")
    low = fx.record_score(ctx["attempt"]["id"], ctx["evaluator_three"]["id"],
                          [dimension_score("D1", 76), dimension_score("D2", 76)])
    A.assert_number_equals(low["weighted_score_pct"], 76.00, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "ADJUDICATION"
    assert attempt["final_score_pct"] is None
    assert attempt["is_provisional_score"] is False
    assert attempt["score_variant"] is None
    assert attempt["scores_received_count"] == 2
    assert attempt["revision_count"] == 1

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 0

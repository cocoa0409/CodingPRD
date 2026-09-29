"""State machines that do not run in a straight line: one row carrying two
dimensions that advance independently, and one workflow that loops back on
itself until the loop converts into a terminal decision.
"""
import pytest

from test_helpers import fixtures as fx
from test_helpers.test_users import (
    EVALUATOR_3_USER_ID,
    make_field_evaluator_headers,
)


# ─── Two dimensions on one play grade ──────────────────

@pytest.fixture
def appealed_and_clean_grades():
    """A played game with two posted grades on the same umpire: a clean call and
    a high-impact missed call the umpire has appealed."""
    ctx = fx.played_solo_game()
    game_id = ctx["game"]["id"]
    official_id = ctx["official"]["id"]
    ctx["clean_grade"] = fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q1-P07",
        call_category="HOLDING",
        grade_code="CORRECT",
        impact="LOW",
    )
    ctx["appealed_grade"] = fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q4-P02",
        call_category="ROUGHING_PASSER",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    ctx["appeal"] = fx.file_appeal(
        ctx["appealed_grade"]["id"],
        official_id,
        "camera angle shows contact was legal",
    )
    return ctx


def test_finalization_advances_the_clean_grade_and_leaves_the_appealed_one_posted(
    appealed_and_clean_grades,
):
    """Finalizing the game carries the un-appealed grade to FINAL while the grade
    under a pending appeal stays POSTED.

    PRD §3.9: "Every play grade on that game whose `grade_status` is `POSTED` and
    whose `appeal_state` is not `APPEAL_PENDING` moves `POSTED → FINAL`,
    processed in `created_at` ascending order; a grade under a pending appeal
    stays `POSTED` and simply waits."

    Design: Difficulty/non_linear_state_machine/play_grade_status_and_appeal_state_advance_independently
    """
    finalized = fx.finalize_game(appealed_and_clean_grades["game"]["id"])

    clean = fx.read_grade(appealed_and_clean_grades["clean_grade"]["id"])
    appealed = fx.read_grade(appealed_and_clean_grades["appealed_grade"]["id"])

    assert finalized["status"] == "FINALIZED"
    assert clean["grade_status"] == "FINAL"
    assert clean["appeal_state"] == "NOT_APPEALED"
    assert appealed["grade_status"] == "POSTED"
    assert appealed["appeal_state"] == "APPEAL_PENDING"


def test_deciding_the_appeal_advances_only_the_appeal_dimension(
    appealed_and_clean_grades,
):
    """After the decision the grade reads POSTED with APPEAL_RESOLVED: the game is
    already FINALIZED, so grade_status has no further move to make.

    PRD §3.6: "There is exactly one coupling between the two, and it runs in one
    direction only: a grade may move `POSTED → FINAL` only while its
    `appeal_state` is not `APPEAL_PENDING`."

    Design: Difficulty/non_linear_state_machine/play_grade_status_and_appeal_state_advance_independently
    """
    fx.finalize_game(appealed_and_clean_grades["game"]["id"])
    appeal_id = appealed_and_clean_grades["appeal"]["id"]

    fx.start_appeal_review(appeal_id)
    fx.decide_appeal(appeal_id, "UPHELD", decision_note="grade stands on review")
    appealed = fx.read_grade(appealed_and_clean_grades["appealed_grade"]["id"])

    assert appealed["appeal_state"] == "APPEAL_RESOLVED"
    assert appealed["grade_status"] == "POSTED"


def test_an_upheld_appeal_leaves_the_grade_code_and_error_points_untouched(
    appealed_and_clean_grades,
):
    """The upheld high-impact missed call still reads MISSED_CALL and 2.63.

    PRD §3.7: "**`UPHELD`** leaves `grade_code` and `error_points` exactly as they
    were; the season-record recompute still runs, and simply produces the same
    numbers."

    Design: Difficulty/non_linear_state_machine/play_grade_status_and_appeal_state_advance_independently
    """
    fx.finalize_game(appealed_and_clean_grades["game"]["id"])
    appeal_id = appealed_and_clean_grades["appeal"]["id"]

    fx.start_appeal_review(appeal_id)
    fx.decide_appeal(appeal_id, "UPHELD", decision_note="grade stands on review")
    appealed = fx.read_grade(appealed_and_clean_grades["appealed_grade"]["id"])

    assert appealed["grade_code"] == "MISSED_CALL"
    assert appealed["error_points"] == 2.63


# ─── The committee return loop ─────────────────────────

@pytest.fixture
def application_returned_once():
    """A TIER_1 application under a one-return cap: submitted, returned once,
    re-evidenced with a third report and forwarded again."""
    ctx = fx.application_at_committee(max_application_returns=1)
    application_id = ctx["application"]["id"]
    ctx["first_return"] = fx.return_for_tape(
        application_id, "need two more quarters of tape"
    )
    ctx["third_evaluation"] = fx.add_field_evaluation(
        application_id,
        mechanics_score=84.00,
        rules_score=80.00,
        presence_score=80.00,
        headers=make_field_evaluator_headers(EVALUATOR_3_USER_ID),
    )
    ctx["resubmitted"] = fx.submit_to_committee(application_id)
    return ctx


def test_the_evaluation_average_is_the_mean_of_the_already_rounded_composites(
    application_returned_once,
):
    """Two reports at 76.10 and 81.60 average to 78.85, and the third report
    filed after the return moves the average to 79.77 without being excluded.

    PRD §3.3: "Filing a report also refreshes the parent application's
    `evaluation_average`, which is the mean of the already-rounded
    `composite_score` values of every report on that application, taken in
    `created_at` ascending order and rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/advancement_application_return_loop_then_auto_denial_at_cap
    """
    first, second = application_returned_once["evaluations"]

    assert first["composite_score"] == 76.10
    assert second["composite_score"] == 81.60
    assert application_returned_once["third_evaluation"]["composite_score"] == 81.60
    assert application_returned_once["resubmitted"]["evaluation_average"] == 79.77


def test_a_return_below_the_cap_loops_the_application_back_to_committee_review(
    application_returned_once,
):
    """The first return counts once and parks the application in
    RETURNED_FOR_TAPE, from which the fresh report forwards it straight back to
    COMMITTEE_REVIEW.

    PRD §3.3: "While `return_count` is strictly less than the program's
    `max_application_returns`, the return increments `return_count` by 1, sets
    `decision_note` to the supplied `note`, and moves the application
    `COMMITTEE_REVIEW → RETURNED_FOR_TAPE`; the evaluator may then file the extra
    report the raised bar now demands and forward it again, which is the loop
    `COMMITTEE_REVIEW → RETURNED_FOR_TAPE → COMMITTEE_REVIEW`."

    Design: Difficulty/non_linear_state_machine/advancement_application_return_loop_then_auto_denial_at_cap
    """
    assert application_returned_once["first_return"]["status"] == "RETURNED_FOR_TAPE"
    assert application_returned_once["first_return"]["return_count"] == 1
    assert application_returned_once["resubmitted"]["status"] == "COMMITTEE_REVIEW"
    assert application_returned_once["resubmitted"]["return_count"] == 1


def test_a_return_at_the_cap_denies_the_application_instead_of_counting_again(
    application_returned_once,
):
    """The second return is accepted but terminates the loop: DENIED with
    return_count still 1, and the official's tier unchanged.

    PRD §3.3: "It terminates the loop instead: `return_count` is left unchanged,
    `decision_note` is set from the supplied `note`, and the application moves
    `COMMITTEE_REVIEW → DENIED`."

    Design: Difficulty/non_linear_state_machine/advancement_application_return_loop_then_auto_denial_at_cap
    """
    application_id = application_returned_once["application"]["id"]

    capped = fx.return_for_tape(application_id, "tape still inconclusive")
    official = fx.read_official(application_returned_once["official"]["id"])

    assert capped["status"] == "DENIED"
    assert capped["return_count"] == 1
    assert capped["decision_note"] == "tape still inconclusive"
    assert official["tier"] == "TIER_2"

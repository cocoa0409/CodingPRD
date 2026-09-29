"""Multi-hop cascades where each hop is caused by the hop before it: one appeal
decision that walks accuracy back up and lifts discipline, and one suspension
that empties a crew slot and reprices the crew.
"""
import pytest

from test_helpers import fixtures as fx


# ─── The accuracy-recovery cascade ─────────────────────

@pytest.fixture
def referee_on_performance_probation():
    """Rita Vance with three posted grades — two clean calls and one incorrect
    medium-impact call — a PERFORMANCE warning against her, and her appeal of
    that call already under review."""
    ctx = fx.played_solo_game_with_referee()
    game_id = ctx["game"]["id"]
    official_id = ctx["official"]["id"]
    fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q1-P05",
        call_category="FALSE_START",
        grade_code="CORRECT",
        impact="LOW",
    )
    fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q2-P18",
        call_category="HOLDING",
        grade_code="CORRECT",
        impact="LOW",
    )
    ctx["disputed_grade"] = fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q3-P31",
        call_category="PASS_INTERFERENCE",
        grade_code="INCORRECT_CALL",
        impact="MEDIUM",
    )
    ctx["discipline"] = fx.open_discipline(official_id, "PERFORMANCE", "WARNING")
    appeal = fx.file_appeal(
        ctx["disputed_grade"]["id"],
        official_id,
        "defender played the ball, not the receiver",
    )
    ctx["appeal"] = fx.start_appeal_review(appeal["id"])
    return ctx


def test_a_performance_warning_puts_the_referee_on_probation(
    referee_on_performance_probation,
):
    """Before the appeal is decided the referee sits on 1.20 error points, an
    index of 92.00, ineligible accuracy and PROBATION status.

    PRD §3.8: "A `WARNING` moves an `ACTIVE` official to `PROBATION` **only when
    its `reason_category` is `PERFORMANCE`**; a warning for `CONDUCT` or
    `ATTENDANCE` leaves the official's `status` alone."

    Design: Difficulty/transitive_cascade/overturned_appeal_restores_accuracy_clears_discipline_and_reinstates_official
    """
    official_id = referee_on_performance_probation["official"]["id"]

    record = fx.season_record_for(official_id)
    official = fx.read_official(official_id)

    assert referee_on_performance_probation["disputed_grade"]["error_points"] == 1.20
    assert record["weighted_error_points"] == 1.20
    assert record["accuracy_index"] == 92.00
    assert record["accuracy_eligible"] is False
    assert record["postseason_eligible"] is False
    assert official["status"] == "PROBATION"
    assert referee_on_performance_probation["discipline"]["status"] == "OPENED"


def test_overturning_the_appeal_zeroes_the_grade_and_restores_the_index(
    referee_on_performance_probation,
):
    """The overturned call becomes CORRECT worth 0.00, and the same three plays
    now read an index of 100.00.

    PRD §3.7: "Second, because those error points changed, the graded official's
    season record has its `weighted_error_points` and `accuracy_index` recomputed
    with the provisional variant — the play stays in the denominator, so a referee
    whose three plays previously read 100.00 minus 6.00, or 92.00, on the strength
    of one incorrect medium-impact call worth 1.20 now reads 100.00 with
    `graded_play_count` still 3."

    Design: Difficulty/transitive_cascade/overturned_appeal_restores_accuracy_clears_discipline_and_reinstates_official
    """
    official_id = referee_on_performance_probation["official"]["id"]

    decided = fx.decide_appeal(
        referee_on_performance_probation["appeal"]["id"],
        "OVERTURNED",
        decision_note="call reversed on review",
    )
    grade = fx.read_grade(referee_on_performance_probation["disputed_grade"]["id"])
    record = fx.season_record_for(official_id)

    assert decided["status"] == "OVERTURNED"
    assert grade["grade_code"] == "CORRECT"
    assert grade["error_points"] == 0.00
    assert grade["appeal_state"] == "APPEAL_RESOLVED"
    assert record["weighted_error_points"] == 0.00
    assert record["accuracy_index"] == 100.00
    assert record["graded_play_count"] == 3


def test_the_recovered_accuracy_clears_the_discipline_and_reinstates_the_official(
    referee_on_performance_probation,
):
    """Eligibility flipping true clears the PERFORMANCE action, which returns the
    referee to ACTIVE and her record to postseason eligible.

    PRD §3.7: "Fourth, if and only if `accuracy_eligible` flips from false to
    true, every discipline action against that official whose `reason_category` is
    `PERFORMANCE` and whose status is `OPENED`, `REMEDIATION_ASSIGNED` or
    `REASSESSED` is transitioned to `CLEARED`, in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/overturned_appeal_restores_accuracy_clears_discipline_and_reinstates_official
    """
    official_id = referee_on_performance_probation["official"]["id"]

    fx.decide_appeal(
        referee_on_performance_probation["appeal"]["id"],
        "OVERTURNED",
        decision_note="call reversed on review",
    )
    record = fx.season_record_for(official_id)
    action = fx.read_discipline(referee_on_performance_probation["discipline"]["id"])
    official = fx.read_official(official_id)

    assert record["accuracy_eligible"] is True
    assert action["status"] == "CLEARED"
    assert official["status"] == "ACTIVE"
    assert record["postseason_eligible"] is True


# ─── The suspension void cascade ───────────────────────

@pytest.fixture
def suspended_crew_member():
    """A fully confirmed two-person crew on a still-scheduled game, with a
    conduct suspension opened against the umpire."""
    ctx = fx.crew_game()
    ctx["discipline"] = fx.open_discipline(
        ctx["umpire"]["id"], "CONDUCT", "SUSPENSION", suspension_games=2
    )
    return ctx


def test_a_suspension_voids_the_officials_confirmed_assignment(
    suspended_crew_member,
):
    """The umpire is suspended and his confirmed assignment is voided with a
    stamped release instant, leaving him no open assignments.

    PRD §3.8: "Every assignment of the suspended official whose status is
    `PROPOSED` or `CONFIRMED`, and whose game is still `SCHEDULED` or
    `IN_PROGRESS`, is transitioned to `VOIDED` in `created_at` ascending order
    with `released_at` stamped from the logical clock."

    Design: Difficulty/transitive_cascade/suspension_voids_assignments_and_reprices_game_crew
    """
    umpire = fx.read_official(suspended_crew_member["umpire"]["id"])
    assignment = fx.read_assignment(
        suspended_crew_member["umpire_assignment"]["id"]
    )

    assert suspended_crew_member["discipline"]["status"] == "OPENED"
    assert umpire["status"] == "SUSPENDED"
    assert umpire["open_assignment_count"] == 0
    assert assignment["status"] == "VOIDED"
    assert assignment["released_at"] is not None


def test_the_void_drops_the_confirmed_count_and_reprices_the_crew(
    suspended_crew_member,
):
    """Losing the umpire takes the confirmed count to 1, re-derives posture to
    UNDERSTAFFED on the still-scheduled game, and reprices the projected index to
    6.24 — the referee's 12.48 over the required crew of two. Only the suspended
    official's row is touched.

    PRD §3.8: "Each void of a previously `CONFIRMED` assignment additionally
    decrements its game's `confirmed_crew_count` by 1 and recomputes that game's
    `crew_strength_index` with the `PROJECTED` variant — and `crew_posture` is
    re-derived only while the game is still `SCHEDULED`, falling from `STAFFED` to
    `UNDERSTAFFED` when the count drops below `crew_size_required`."

    Design: Difficulty/transitive_cascade/suspension_voids_assignments_and_reprices_game_crew
    """
    game = fx.read_game(suspended_crew_member["game"]["id"])
    referee_assignment = fx.read_assignment(
        suspended_crew_member["referee_assignment"]["id"]
    )

    assert game["status"] == "SCHEDULED"
    assert game["confirmed_crew_count"] == 1
    assert game["crew_posture"] == "UNDERSTAFFED"
    assert game["crew_strength_index"] == 6.24
    assert game["crew_strength_variant"] == "PROJECTED"
    assert referee_assignment["status"] == "CONFIRMED"

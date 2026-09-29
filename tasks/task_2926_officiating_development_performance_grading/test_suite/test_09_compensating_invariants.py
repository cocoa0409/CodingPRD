"""Quantities the system must conserve: the appeal credit ledger, the
denormalised crew counters, and the season error-point total against the
per-play values it is meant to sum.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import INSTANT_SEASON_START, PROGRAM_DEFAULTS


# ─── The appeal credit ledger ──────────────────────────

@pytest.fixture
def unappealed_posted_grade():
    """A played game with one posted missed call on Dan Ruiz, who has spent no
    appeal credits yet."""
    ctx = fx.posted_grade_for_appeal()
    ctx["official_at_start"] = fx.read_official(ctx["official"]["id"])
    return ctx


def test_filing_an_appeal_debits_exactly_one_credit(unappealed_posted_grade):
    """The ledger falls from three to two while the grade moves to
    APPEAL_PENDING, so two credits plus one consuming appeal still make three.

    PRD §3.7: "A successful filing writes the appeal with `status` `SUBMITTED` and
    `submitted_at` stamped from the logical clock, sets the parent grade's
    `appeal_state` from `NOT_APPEALED` to `APPEAL_PENDING` while bumping the
    grade's `version` by 1 and leaving `grade_status` untouched, and decrements the
    official's `appeal_credits_remaining` by 1 while bumping the official's
    `version` by 1."

    Design: Difficulty/compensating_invariant/appeal_credit_ledger_restored_by_withdrawal
    """
    official_id = unappealed_posted_grade["official"]["id"]

    assert unappealed_posted_grade["official_at_start"][
        "appeal_credits_remaining"
    ] == PROGRAM_DEFAULTS["appeal_credits_per_official"]

    appeal = fx.file_appeal(
        unappealed_posted_grade["grade"]["id"],
        official_id,
        "the runner was already down",
    )
    official = fx.read_official(official_id)
    grade = fx.read_grade(unappealed_posted_grade["grade"]["id"])

    assert appeal["status"] == "SUBMITTED"
    assert official["appeal_credits_remaining"] == 2
    assert grade["appeal_state"] == "APPEAL_PENDING"


def test_withdrawing_the_appeal_refunds_the_credit_exactly(unappealed_posted_grade):
    """The refund is whole: three credits again, the grade back to NOT_APPEALED,
    and its value untouched throughout.

    PRD §3.7: "Withdrawing an appeal credits one back, because a withdrawn appeal
    leaves the consuming set."

    Design: Difficulty/compensating_invariant/appeal_credit_ledger_restored_by_withdrawal
    """
    official_id = unappealed_posted_grade["official"]["id"]
    appeal = fx.file_appeal(
        unappealed_posted_grade["grade"]["id"],
        official_id,
        "the runner was already down",
    )

    withdrawn = fx.withdraw_appeal(appeal["id"], official_id)
    official = fx.read_official(official_id)
    grade = fx.read_grade(unappealed_posted_grade["grade"]["id"])

    assert withdrawn["status"] == "WITHDRAWN"
    assert official["appeal_credits_remaining"] == 3
    assert grade["appeal_state"] == "NOT_APPEALED"
    assert grade["grade_status"] == "POSTED"
    assert grade["error_points"] == 0.75


def test_the_refunded_credit_is_genuinely_reusable(unappealed_posted_grade):
    """The same grade can be appealed again on the returned credit, and the
    ledger lands back on two.

    PRD §3.7: "This is a genuine cycle inside the appeal dimension —
    `NOT_APPEALED → APPEAL_PENDING → NOT_APPEALED` — and it may repeat as long as
    the official still has credits and the appeal window is still open."

    Design: Difficulty/compensating_invariant/appeal_credit_ledger_restored_by_withdrawal
    """
    official_id = unappealed_posted_grade["official"]["id"]
    grade_id = unappealed_posted_grade["grade"]["id"]
    first = fx.file_appeal(grade_id, official_id, "the runner was already down")
    fx.withdraw_appeal(first["id"], official_id)

    refiled = fx.file_appeal(grade_id, official_id, "refiled with the sideline angle")
    official = fx.read_official(official_id)

    assert refiled["status"] == "SUBMITTED"
    assert official["appeal_credits_remaining"] == 2


# ─── The crew counters ─────────────────────────────────

@pytest.fixture
def crew_with_one_proposal_outstanding():
    """A crew of two: Rita confirmed, Dan still merely proposed."""
    ctx = fx.crew_game(confirm_umpire=False)
    ctx["game_at_start"] = fx.read_game(ctx["game"]["id"])
    ctx["umpire_at_start"] = fx.read_official(ctx["umpire"]["id"])
    return ctx


def test_confirming_the_proposal_moves_the_posture_but_not_the_projected_index(
    crew_with_one_proposal_outstanding,
):
    """The projected index already counted the proposed umpire, so confirmation
    changes the count and the posture while leaving 8.64 exactly where it was.

    PRD §3.4: "The `PROJECTED` variant includes assignments in `PROPOSED` or
    `CONFIRMED` status, counting a merely proposed official at full weight on the
    assumption that the slot will hold; it is what every pre-kickoff write
    recomputes."

    Design: Difficulty/compensating_invariant/crew_counters_restored_after_confirm_then_withdraw
    """
    before = crew_with_one_proposal_outstanding["game_at_start"]

    assert before["confirmed_crew_count"] == 1
    assert before["crew_posture"] == "UNDERSTAFFED"
    assert before["crew_strength_index"] == 8.64
    assert crew_with_one_proposal_outstanding["umpire_at_start"][
        "open_assignment_count"
    ] == 1

    confirmed = fx.confirm_assignment(
        crew_with_one_proposal_outstanding["umpire_assignment"]["id"]
    )
    after = fx.read_game(crew_with_one_proposal_outstanding["game"]["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert after["confirmed_crew_count"] == 2
    assert after["crew_posture"] == "STAFFED"
    assert after["crew_strength_index"] == 8.64


def test_withdrawing_it_again_lands_the_counters_back_on_a_recount(
    crew_with_one_proposal_outstanding,
):
    """Confirm-then-withdraw returns the confirmed count to 1 and the index to
    6.24, decrements only the withdrawn official's own counter, and reconciles
    with a listing of the game's confirmed rows.

    PRD §3.4: "In both cases the assignment moves to `WITHDRAWN`, its `released_at`
    is stamped with the logical clock, the official's `open_assignment_count`
    decrements by 1, the game's projected crew strength is recomputed, and the
    game's `version` bumps by 1."

    Design: Difficulty/compensating_invariant/crew_counters_restored_after_confirm_then_withdraw
    """
    game_id = crew_with_one_proposal_outstanding["game"]["id"]
    umpire_assignment_id = crew_with_one_proposal_outstanding["umpire_assignment"]["id"]
    fx.confirm_assignment(umpire_assignment_id)

    withdrawn = fx.withdraw_assignment(umpire_assignment_id, "illness")
    game = fx.read_game(game_id)
    umpire = fx.read_official(crew_with_one_proposal_outstanding["umpire"]["id"])
    referee = fx.read_official(crew_with_one_proposal_outstanding["referee"]["id"])
    listing = api_client.list_crew_assignments(
        fx.SCHEDULER, {"game_id": game_id, "status": "CONFIRMED"}
    )
    confirmed_rows = get_success_data(listing, 200)

    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant_equals(
        withdrawn["released_at"], INSTANT_SEASON_START, "released_at"
    )
    assert game["confirmed_crew_count"] == 1
    assert game["crew_posture"] == "UNDERSTAFFED"
    assert game["crew_strength_index"] == 6.24
    assert umpire["open_assignment_count"] == 0
    assert referee["open_assignment_count"] == 1
    assert [row["id"] for row in confirmed_rows] == [
        crew_with_one_proposal_outstanding["referee_assignment"]["id"]
    ]


# ─── The error-point ledger ────────────────────────────

@pytest.fixture
def appeal_under_review_on_a_high_impact_call():
    """Dan carries one clean call and one high-impact missed call worth 2.63, the
    second of which is under appeal review."""
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
    ctx["heavy_grade"] = fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q4-P11",
        call_category="PASS_INTERFERENCE",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    ctx["record_before"] = fx.season_record_for(official_id)
    appeal = fx.file_appeal(
        ctx["heavy_grade"]["id"],
        official_id,
        "contact was incidental, at most a lesser foul",
    )
    ctx["appeal"] = fx.start_appeal_review(appeal["id"])
    return ctx


def test_the_ledger_starts_as_the_sum_of_the_current_per_play_values(
    appeal_under_review_on_a_high_impact_call,
):
    """Two plays worth 0.00 and 2.63 give a provisional total of 2.63 and an index
    of 73.70.

    PRD §3.6: "Otherwise the index is 100.00 minus the quantity obtained by
    dividing `weighted_error_points` by `graded_play_count` and multiplying the
    quotient by an error scale of 20.00, with the final result rounded half up to
    two decimal places."

    Design: Difficulty/compensating_invariant/error_point_ledger_reconciles_after_modified_appeal
    """
    record = appeal_under_review_on_a_high_impact_call["record_before"]

    assert appeal_under_review_on_a_high_impact_call["heavy_grade"][
        "error_points"
    ] == 2.63
    assert record["graded_play_count"] == 2
    assert record["weighted_error_points"] == 2.63
    assert record["accuracy_index"] == 73.70
    assert record["accuracy_variant"] == "PROVISIONAL"


def test_a_modified_appeal_revalues_the_grade_and_the_ledger_follows_exactly(
    appeal_under_review_on_a_high_impact_call,
):
    """Downgrading the call to an incorrect one reprices it from 2.63 to 1.75, and
    the season total becomes exactly 0.00 plus 1.75 over the same two plays.

    PRD §3.7: "**`MODIFIED`** rewrites `grade_code` to the supplied
    `revised_grade_code` and recomputes `error_points` from the new code, which
    moves the official's `weighted_error_points` and `accuracy_index`."

    Design: Difficulty/compensating_invariant/error_point_ledger_reconciles_after_modified_appeal
    """
    official_id = appeal_under_review_on_a_high_impact_call["official"]["id"]

    decided = fx.decide_appeal(
        appeal_under_review_on_a_high_impact_call["appeal"]["id"],
        "MODIFIED",
        decision_note="downgraded to an incorrect call",
        revised_grade_code="INCORRECT_CALL",
    )
    heavy = fx.read_grade(
        appeal_under_review_on_a_high_impact_call["heavy_grade"]["id"]
    )
    clean = fx.read_grade(
        appeal_under_review_on_a_high_impact_call["clean_grade"]["id"]
    )
    record = fx.season_record_for(official_id)

    assert decided["status"] == "MODIFIED"
    assert heavy["grade_code"] == "INCORRECT_CALL"
    assert heavy["error_points"] == 1.75
    assert heavy["appeal_state"] == "APPEAL_RESOLVED"
    assert clean["error_points"] == 0.00
    assert record["weighted_error_points"] == 1.75
    assert record["graded_play_count"] == 2
    assert record["accuracy_index"] == 82.50
    assert record["accuracy_eligible"] is False

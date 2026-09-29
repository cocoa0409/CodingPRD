"""Requests that break two rules at once. Each one is built so that both
violations are real and only the higher-ranked rule may be reported.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_G1_POSTGAME,
    INSTANT_G2_KICKOFF,
    INSTANT_G4_KICKOFF,
    INSTANT_PAST_APPEAL_DEADLINE,
    PROGRAM_DEFAULTS,
)


# ─── Fatigue safety over the rotation cap ──────────────

@pytest.fixture
def umpire_at_the_rotation_cap():
    """Dan Ruiz holds proposals on two games that both involve MIA, so a third
    MIA game is over the exposure cap — and its occupancy window also overlaps
    the second proposal's window."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    first = fx.schedule_game(program["id"])
    fx.propose_assignment(
        first["id"], official["id"], "UMPIRE", expected_game_version=first["version"]
    )
    second = fx.schedule_game(
        program["id"],
        home_team_code="NYJ",
        away_team_code="MIA",
        venue_market_code="NYJ",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )
    fx.propose_assignment(
        second["id"], official["id"], "UMPIRE", expected_game_version=second["version"]
    )
    third = fx.schedule_game(
        program["id"],
        home_team_code="DAL",
        away_team_code="MIA",
        venue_market_code="DAL",
        kickoff_utc=INSTANT_G4_KICKOFF,
    )
    return {
        "program": program,
        "official": official,
        "first_game": first,
        "second_game": second,
        "third_game": third,
    }


def test_the_occupancy_conflict_is_reported_ahead_of_the_rotation_cap(
    umpire_at_the_rotation_cap,
):
    """The proposal overlaps an existing window and exceeds the MIA exposure cap;
    the response is the window conflict.

    PRD §2.9: "Fatigue safety: the official's occupancy window for the target game
    overlaps none of that official's own proposed, confirmed or completed
    assignment windows, else `ERR_OFFICIAL_WINDOW_CONFLICT` (409). Fatigue safety
    deliberately outranks every rotation, conflict-of-interest and quota rule
    below it."

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_outranks_team_rotation_limit
    """
    third = umpire_at_the_rotation_cap["third_game"]

    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            third["id"],
            umpire_at_the_rotation_cap["official"]["id"],
            "UMPIRE",
            third["version"],
        ),
        fx.SCHEDULER,
    )
    error = validate_error(response, "ERR_OFFICIAL_WINDOW_CONFLICT", 409)

    assert error["error_id"] != "ERR_TEAM_ROTATION_LIMIT"


def test_the_refused_proposal_writes_no_assignment_at_all(
    umpire_at_the_rotation_cap,
):
    """The rejected call leaves the third game uncrewed and the umpire's open
    assignment count at the two proposals he already held.

    PRD §2.9: "When a single request violates more than one rule, the response is
    determined by the violated rule that stands highest in the following
    precedence order, and no lower rule is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_outranks_team_rotation_limit
    """
    third = umpire_at_the_rotation_cap["third_game"]
    official_id = umpire_at_the_rotation_cap["official"]["id"]

    api_client.create_crew_assignment(
        f.crew_assignment_payload(third["id"], official_id, "UMPIRE", third["version"]),
        fx.SCHEDULER,
    )
    listing = api_client.list_crew_assignments(fx.SCHEDULER, {"game_id": third["id"]})
    rows = get_success_data(listing, 200)
    official = fx.read_official(official_id)

    assert rows == []
    assert official["open_assignment_count"] == 2


# ─── The closed window over exhausted credits ──────────

@pytest.fixture
def credit_less_umpire_past_the_deadline():
    """Dan has appealed three of his four posted grades, spending every credit,
    and the clock now stands one second past every appeal deadline."""
    ctx = fx.played_game_with_three_posted_grades()
    ctx["late_grade"] = fx.posted_grade(
        ctx["game"]["id"],
        ctx["official"]["id"],
        play_ref="Q4-P09",
        call_category="ROUGHING_PASSER",
        grade_code="INCORRECT_CALL",
        impact="MEDIUM",
    )
    for index, grade in enumerate(ctx["grades"], start=1):
        fx.file_appeal(grade["id"], ctx["official"]["id"], f"appeal number {index}")
    ctx["official_before"] = fx.read_official(ctx["official"]["id"])
    fx.pin_clock(INSTANT_PAST_APPEAL_DEADLINE)
    return ctx


def test_the_closed_appeal_window_is_reported_ahead_of_the_spent_credits(
    credit_less_umpire_past_the_deadline,
):
    """Filing one second late with no credits left reports the window, not the
    ledger.

    PRD §2.9: "The appealing official has at least one appeal credit remaining,
    else `ERR_APPEAL_CREDITS_EXHAUSTED` (409). This sits below step 26 on purpose:
    an out-of-window appeal by a credit-less official reports the window error."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_closed_outranks_exhausted_appeal_credits
    """
    late_grade = credit_less_umpire_past_the_deadline["late_grade"]
    official_id = credit_less_umpire_past_the_deadline["official"]["id"]

    assert_instant_equals(late_grade["posted_at"], INSTANT_G1_POSTGAME, "posted_at")
    assert (
        credit_less_umpire_past_the_deadline["official_before"][
            "appeal_credits_remaining"
        ]
        == 0
    )

    response = api_client.create_grade_appeal(
        f.grade_appeal_payload(late_grade["id"], "fourth appeal filed one second late"),
        fx.make_official_headers(official_id),
    )
    error = validate_error(response, "ERR_APPEAL_WINDOW_CLOSED", 422)

    assert error["error_id"] != "ERR_APPEAL_CREDITS_EXHAUSTED"


def test_the_late_appeal_leaves_the_grade_unappealed_and_the_ledger_still_empty(
    credit_less_umpire_past_the_deadline,
):
    """The refused filing changes nothing: the grade is still NOT_APPEALED and the
    conserved ledger still reads 0 against three consuming appeals.

    PRD §3.7: "Each official's `appeal_credits_remaining` is seeded at
    registration from the program's `appeal_credits_per_official`, and at every
    instant thereafter the sum of `appeal_credits_remaining` and the number of that
    official's appeals whose status is `SUBMITTED`, `UNDER_REVIEW`, `UPHELD`,
    `OVERTURNED` or `MODIFIED` equals `appeal_credits_per_official` exactly."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_closed_outranks_exhausted_appeal_credits
    """
    late_grade = credit_less_umpire_past_the_deadline["late_grade"]
    official_id = credit_less_umpire_past_the_deadline["official"]["id"]

    api_client.create_grade_appeal(
        f.grade_appeal_payload(late_grade["id"], "fourth appeal filed one second late"),
        fx.make_official_headers(official_id),
    )
    grade = fx.read_grade(late_grade["id"])
    official = fx.read_official(official_id)

    assert grade["appeal_state"] == "NOT_APPEALED"
    assert official["appeal_credits_remaining"] == 0


# ─── Ownership over the grade's own state ──────────────

@pytest.fixture
def draft_grade_and_a_stranger():
    """A DRAFT grade written against Dan Ruiz, plus Rita Vance — cleared, with all
    her appeal credits — who has nothing to do with it."""
    ctx = fx.played_solo_game()
    ctx["stranger"] = fx.register_referee(ctx["program"]["id"])
    ctx["draft_grade"] = fx.grade_play(
        ctx["game"]["id"],
        ctx["official"]["id"],
        play_ref="Q2-P08",
        call_category="HOLDING",
        grade_code="MISSED_CALL",
        impact="MEDIUM",
    )
    return ctx


def test_ownership_is_settled_before_the_grades_own_state_is_examined(
    draft_grade_and_a_stranger,
):
    """A stranger appealing a grade that is still DRAFT is refused for ownership,
    not for the grade's state.

    PRD §2.9: "Grade ownership: an `Official` filing an appeal, or withdrawing
    one, is the official the appealed grade was written against, else
    `ERR_NOT_GRADE_OWNER` (403)."

    Design: Difficulty/priority_pair_validation_conflict/non_owner_appeal_returns_forbidden_before_grade_state_is_examined
    """
    draft_grade = draft_grade_and_a_stranger["draft_grade"]

    assert draft_grade["grade_status"] == "DRAFT"

    response = api_client.create_grade_appeal(
        f.grade_appeal_payload(draft_grade["id"], "not my grade and not even posted"),
        fx.make_official_headers(draft_grade_and_a_stranger["stranger"]["id"]),
    )
    error = validate_error(response, "ERR_NOT_GRADE_OWNER", 403)

    assert error["error_id"] != "ERR_GRADE_STATE_INVALID"


def test_a_rejected_appeal_spends_none_of_the_filers_credits(
    draft_grade_and_a_stranger,
):
    """Rita's ledger is untouched by the refusal, and the grade stays DRAFT and
    unappealed.

    PRD §3.7: "Filing an appeal debits one credit; an official whose
    `appeal_credits_remaining` is already 0 is refused with
    `ERR_APPEAL_CREDITS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/non_owner_appeal_returns_forbidden_before_grade_state_is_examined
    """
    draft_grade = draft_grade_and_a_stranger["draft_grade"]
    stranger_id = draft_grade_and_a_stranger["stranger"]["id"]

    api_client.create_grade_appeal(
        f.grade_appeal_payload(draft_grade["id"], "not my grade and not even posted"),
        fx.make_official_headers(stranger_id),
    )
    stranger = fx.read_official(stranger_id)
    grade = fx.read_grade(draft_grade["id"])

    assert stranger["appeal_credits_remaining"] == (
        PROGRAM_DEFAULTS["appeal_credits_per_official"]
    )
    assert grade["grade_status"] == "DRAFT"
    assert grade["appeal_state"] == "NOT_APPEALED"

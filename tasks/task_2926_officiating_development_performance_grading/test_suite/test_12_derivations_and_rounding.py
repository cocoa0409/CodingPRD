"""Derived numbers and the constants they read: the per-report rounding that
propagates into an average, the per-type pass thresholds, the zero-play accuracy
branch, the eligibility conjunction, the exposure input set, and the inclusive
appeal deadline.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_APPEAL_DEADLINE,
    INSTANT_G1_OCCUPIED_UNTIL,
    INSTANT_G1_POSTGAME,
    INSTANT_G2_KICKOFF,
    INSTANT_G2_OCCUPIED_FROM,
    INSTANT_G2_OCCUPIED_UNTIL,
    INSTANT_G3_KICKOFF,
    INSTANT_PAST_APPEAL_DEADLINE,
    INSTANT_SEASON_START,
)
from test_helpers.test_users import EVALUATOR_USER_ID, make_official_headers


# ─── Rounding per report, then averaging ───────────────

@pytest.fixture
def screened_tier_2_application():
    """Lee Park — a TIER_3 down judge with seven seasons — holds a SCREENED
    application for TIER_2 and carries no evaluation reports yet."""
    program = fx.create_open_program()
    lee = fx.register_official(
        program["id"],
        full_name="Lee Park",
        position="DOWN_JUDGE",
        seasons_experience=7,
        home_market_code="SEA",
    )
    fx.clear_official(
        lee["id"], exam_score=88.00, exam_code="EX-L1",
        physical_score=82.00, physical_code="PT-L1",
    )
    application = fx.create_application(lee["id"], "TIER_2")
    return {
        "program": program,
        "official": lee,
        "application": fx.screen_application(application["id"]),
    }


def test_the_weighted_composite_is_rounded_at_the_report(
    screened_tier_2_application,
):
    """79.00, 76.00 and 70.50 weight to 75.825, which is stored as 75.83, and the
    filer's own user id is recorded as the evaluator.

    PRD §3.3: "The report's `composite_score` is derived as the weighted sum of the
    three — 40 percent of the mechanics score plus 35 percent of the rules score plus
    25 percent of the presence score — rounded half up to two decimal places."

    Design: Corner/calculations/field_evaluation_composite_rounds_before_the_average
    """
    application_id = screened_tier_2_application["application"]["id"]

    first = fx.add_field_evaluation(
        application_id,
        mechanics_score=79.00,
        rules_score=76.00,
        presence_score=70.50,
        headers=fx.EVALUATOR,
    )
    application = fx.read_application(application_id, fx.EVALUATOR)

    assert first["composite_score"] == 75.83
    assert first["evaluator_user_id"] == EVALUATOR_USER_ID
    assert application["evaluation_average"] == 75.83
    assert application["status"] == "SCREENED"


def test_the_average_is_taken_over_the_already_rounded_composites(
    screened_tier_2_application,
):
    """The mean of 75.83 and 81.60 is 78.715, which rounds to 78.72 — averaging the
    unrounded 75.825 would have produced 78.71 — and that average clears the
    committee bar.

    PRD §3.3: "Filing a report also refreshes the parent application's
    `evaluation_average`, which is the mean of the already-rounded `composite_score`
    values of every report on that application, taken in `created_at` ascending order
    and rounded half up to two decimal places."

    Design: Corner/calculations/field_evaluation_composite_rounds_before_the_average
    """
    application_id = screened_tier_2_application["application"]["id"]
    fx.add_field_evaluation(
        application_id,
        mechanics_score=79.00,
        rules_score=76.00,
        presence_score=70.50,
        headers=fx.EVALUATOR,
    )

    second = fx.add_field_evaluation(
        application_id,
        mechanics_score=84.00,
        rules_score=80.00,
        presence_score=80.00,
        headers=fx.EVALUATOR_2,
    )
    application = fx.read_application(application_id, fx.EVALUATOR)
    forwarded = fx.submit_to_committee(application_id)

    assert second["composite_score"] == 81.60
    assert application["evaluation_average"] == 78.72
    assert forwarded["status"] == "COMMITTEE_REVIEW"


# ─── Pass flags read per-type constants ────────────────

@pytest.fixture
def candidate_awaiting_his_first_result():
    """Dan Ruiz, CANDIDATE, in a program carrying the default pass minimums of
    70.00 for the physical test and 80.00 for the exam."""
    program = fx.create_open_program()
    return {"program": program, "official": fx.register_umpire(program["id"], cleared=False)}


def test_a_clinic_always_passes_while_a_physical_below_the_minimum_fails(
    candidate_awaiting_his_first_result,
):
    """The clinic stores a null score and passes on attendance alone; the 69.99
    physical fails against the 70.00 minimum and leaves Dan a CANDIDATE.

    PRD §3.2: "A `RULES_CLINIC` record ignores `score` entirely and always stores
    `passed` true — attendance is the whole point."

    Design: Corner/calculations/training_passed_flags_use_per_type_constants_at_the_boundary
    """
    official_id = candidate_awaiting_his_first_result["official"]["id"]

    clinic = fx.add_training_record(official_id, f.rules_clinic_payload("CL-D1"))
    failed_physical = fx.add_training_record(
        official_id, f.physical_test_payload(69.99, "PT-D0")
    )
    official = fx.read_official(official_id)

    assert clinic["passed"] is True
    assert clinic["score"] is None
    assert failed_physical["passed"] is False
    assert official["preseason_cleared"] is False
    assert official["status"] == "CANDIDATE"


def test_scores_sitting_exactly_on_each_minimum_pass(
    candidate_awaiting_his_first_result,
):
    """An exam of exactly 80.00 passes and activates him without clearing him while
    his only physical has failed; a physical of exactly 70.00 then clears him.

    PRD §3.2: "A `PHYSICAL_TEST` record passes when its `score` is greater than or
    equal to the program's `physical_test_min_score`, and a `RULES_EXAM` record
    passes when its `score` is greater than or equal to the program's
    `exam_min_score`; in both cases a score sitting exactly on the minimum passes."

    Design: Corner/calculations/training_passed_flags_use_per_type_constants_at_the_boundary
    """
    official_id = candidate_awaiting_his_first_result["official"]["id"]
    fx.add_training_record(official_id, f.rules_clinic_payload("CL-D1"))
    fx.add_training_record(official_id, f.physical_test_payload(69.99, "PT-D0"))

    exam = fx.add_training_record(official_id, f.rules_exam_payload(80.00, "EX-D0"))
    after_exam = fx.read_official(official_id)
    physical = fx.add_training_record(
        official_id, f.physical_test_payload(70.00, "PT-D2")
    )
    after_physical = fx.read_official(official_id)

    assert exam["passed"] is True
    assert after_exam["status"] == "ACTIVE"
    assert after_exam["preseason_cleared"] is False
    assert physical["passed"] is True
    assert after_physical["preseason_cleared"] is True


def test_the_passed_filter_lists_the_three_passing_records_in_order(
    candidate_awaiting_his_first_result,
):
    """Filtering his history on the derived flag returns the clinic, the exam and the
    second physical, oldest first, and leaves the failed physical out.

    PRD §3.2: "An official's training history is readable only by listing that
    official's training records, optionally filtered by `record_type` or by
    `passed`."

    Design: Corner/calculations/training_passed_flags_use_per_type_constants_at_the_boundary
    """
    official_id = candidate_awaiting_his_first_result["official"]["id"]
    fx.add_training_record(official_id, f.rules_clinic_payload("CL-D1"))
    fx.add_training_record(official_id, f.physical_test_payload(69.99, "PT-D0"))
    fx.add_training_record(official_id, f.rules_exam_payload(80.00, "EX-D0"))
    fx.add_training_record(official_id, f.physical_test_payload(70.00, "PT-D2"))

    response = api_client.list_training_records(
        official_id, fx.TRAINING, {"passed": "true"}
    )
    rows, meta = validate_paginated(response)

    assert meta["total_count"] == 3
    assert [row["record_type"] for row in rows] == [
        "RULES_CLINIC",
        "RULES_EXAM",
        "PHYSICAL_TEST",
    ]
    assert [row["session_code"] for row in rows] == ["CL-D1", "EX-D0", "PT-D2"]


# ─── The zero-play branch ──────────────────────────────

@pytest.fixture
def official_graded_on_nothing():
    """Dan Ruiz just registered: his season record exists but holds no plays."""
    program = fx.create_open_program()
    return {"program": program, "official": fx.register_umpire(program["id"], cleared=False)}


def test_registration_opens_one_record_reading_a_perfect_index(
    official_graded_on_nothing,
):
    """A single record exists with no plays, no error points and an index of exactly
    100.00, yet the play-count floor of three leaves him ineligible.

    PRD §3.6: "Note also that a zero-play official reading exactly 100.00 is *not*
    accuracy eligible under the defaults, because the play-count floor of 3 fails."

    Design: Corner/calculations/zero_play_official_reads_accuracy_100_but_is_not_eligible
    """
    response = api_client.list_season_records(
        fx.DIRECTOR, {"official_id": official_graded_on_nothing["official"]["id"]}
    )
    rows, meta = validate_paginated(response)

    assert meta["total_count"] == 1
    assert rows[0]["graded_play_count"] == 0
    assert rows[0]["weighted_error_points"] == 0.00
    assert rows[0]["accuracy_index"] == 100.00
    assert rows[0]["accuracy_variant"] == "PROVISIONAL"
    assert rows[0]["accuracy_eligible"] is False
    assert rows[0]["postseason_eligible"] is False


def test_the_untouched_record_carries_its_declared_retention_defaults(
    official_graded_on_nothing,
):
    """Read individually by the official himself, the record still shows the seeded
    availability, retention and recommendation values.

    PRD §3.2: "Registration also opens that official's **season record** in the same
    breath: a row carrying the official's `official_id` and the `season_program_id`,
    with `graded_play_count` 0, `weighted_error_points` 0.00, `accuracy_index`
    100.00, `accuracy_variant` `PROVISIONAL`, `accuracy_eligible` false,
    `postseason_eligible` false, `availability_component` 0.00, `retention_score`
    0.00 and `retention_recommendation` `DEVELOP`."

    Design: Corner/calculations/zero_play_official_reads_accuracy_100_but_is_not_eligible
    """
    official_id = official_graded_on_nothing["official"]["id"]
    record = fx.season_record_for(official_id)

    response = api_client.get_season_record(
        record["id"], make_official_headers(official_id)
    )
    read_back = validate_success(response, 200)

    assert read_back["accuracy_index"] == 100.00
    assert read_back["availability_component"] == 0.00
    assert read_back["retention_score"] == 0.00
    assert read_back["retention_recommendation"] == "DEVELOP"


# ─── One conjunct of postseason eligibility ────────────

@pytest.fixture
def official_with_three_clean_plays():
    """Dan's played game carries three POSTED CORRECT grades, so his index is
    100.00 over three plays and every eligibility conjunct holds."""
    ctx = fx.played_solo_game()
    game_id = ctx["game"]["id"]
    official_id = ctx["official"]["id"]
    ctx["grades"] = [
        fx.posted_grade(
            game_id, official_id, play_ref="Q1-P01",
            call_category="FALSE_START", grade_code="CORRECT", impact="MEDIUM",
        ),
        fx.posted_grade(
            game_id, official_id, play_ref="Q2-P07",
            call_category="HOLDING", grade_code="CORRECT", impact="GAME_CRITICAL",
        ),
        fx.posted_grade(
            game_id, official_id, play_ref="Q4-P31",
            call_category="ROUGHING_PASSER", grade_code="CORRECT", impact="LOW",
        ),
    ]
    ctx["record_clean"] = fx.season_record_for(official_id)
    return ctx


def test_an_attendance_warning_falsifies_only_the_discipline_conjunct(
    official_with_three_clean_plays,
):
    """Three CORRECT plays accrue nothing even at game-critical impact, so accuracy
    stays 100.00 and eligible; the OPENED warning leaves his status ACTIVE and is the
    single reason postseason eligibility turns false.

    PRD §3.6: "It is true when the official is `accuracy_eligible`, *and* the
    official's `status` is `ACTIVE`, *and* the official's `preseason_cleared` is true,
    *and* the official has no discipline action whose status is `OPENED`,
    `REMEDIATION_ASSIGNED`, `REASSESSED` or `ESCALATED`."

    Design: Corner/calculations/open_discipline_action_alone_falsifies_postseason_eligibility
    """
    official_id = official_with_three_clean_plays["official"]["id"]
    clean = official_with_three_clean_plays["record_clean"]

    assert [g["error_points"] for g in official_with_three_clean_plays["grades"]] == [
        0.00,
        0.00,
        0.00,
    ]
    assert clean["graded_play_count"] == 3
    assert clean["accuracy_index"] == 100.00
    assert clean["accuracy_eligible"] is True
    assert clean["postseason_eligible"] is True

    action = fx.open_discipline(official_id, "ATTENDANCE", "WARNING")
    official = fx.read_official(official_id)
    record = fx.season_record_for(official_id)

    assert action["status"] == "OPENED"
    assert official["status"] == "ACTIVE"
    assert record["accuracy_index"] == 100.00
    assert record["accuracy_eligible"] is True
    assert record["postseason_eligible"] is False


def test_clearing_that_action_restores_eligibility_without_touching_accuracy(
    official_with_three_clean_plays,
):
    """Once the action leaves the non-terminal set the conjunction holds again, and
    the accuracy number never moved.

    PRD §3.6: "A single open discipline action is enough to make an otherwise perfect
    official ineligible."

    Design: Corner/calculations/open_discipline_action_alone_falsifies_postseason_eligibility
    """
    official_id = official_with_three_clean_plays["official"]["id"]
    action = fx.open_discipline(official_id, "ATTENDANCE", "WARNING")

    resolved = fx.resolve_discipline(
        action["id"], "CLEARED", note="late arrival explained"
    )
    record = fx.season_record_for(official_id)

    assert resolved["status"] == "CLEARED"
    assert record["postseason_eligible"] is True
    assert record["accuracy_index"] == 100.00


# ─── Which assignments count as exposure ───────────────

@pytest.fixture
def two_buf_assignments_and_a_third_buf_game():
    """Dan holds assignments on two games involving BUF, with a third BUF game
    scheduled far enough out that no occupancy window overlaps."""
    program = fx.solo_program()
    dan = fx.register_umpire(program["id"])
    first_game = fx.schedule_game(program["id"])
    second_game = fx.schedule_game(
        program["id"],
        home_team_code="BUF",
        away_team_code="DEN",
        venue_market_code="BUF",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )
    third_game = fx.schedule_game(
        program["id"],
        home_team_code="SEA",
        away_team_code="BUF",
        venue_market_code="SEA",
        kickoff_utc=INSTANT_G3_KICKOFF,
    )
    first_assignment = fx.propose_assignment(
        first_game["id"], dan["id"], "UMPIRE",
        expected_game_version=first_game["version"],
    )
    second_assignment = fx.propose_assignment(
        second_game["id"], dan["id"], "UMPIRE",
        expected_game_version=second_game["version"],
    )
    return {
        "program": program,
        "official": dan,
        "first_game": first_game,
        "second_game": second_game,
        "third_game": third_game,
        "first_assignment": first_assignment,
        "second_assignment": second_assignment,
    }


def test_the_second_window_is_adjacent_to_the_first_and_then_withdrawn(
    two_buf_assignments_and_a_third_buf_game,
):
    """The 18 September game occupies him from 17 September 21:00 to 23 September
    01:00 — opening exactly where the first window closed — and the withdrawal stamps
    its release instant.

    PRD §3.4: "`occupied_from_utc` is the game's `kickoff_utc` moved earlier by the
    program's `travel_lead_hours` — with the default of 24 hours, a 17:00 kickoff on
    13 September 2026 opens its window at 17:00 on 12 September."

    PRD §3.4: "The windows tested against are those of the same official's
    assignments in `PROPOSED`, `CONFIRMED` or `COMPLETED` status; assignments that
    have been `WITHDRAWN`, `SUPERSEDED` or `VOIDED` release their window immediately
    and are never tested."

    Design: Corner/calculations/withdrawn_assignment_leaves_the_team_exposure_input_set
    """
    second = two_buf_assignments_and_a_third_buf_game["second_assignment"]

    assert_instant_equals(
        second["occupied_from_utc"], INSTANT_G1_OCCUPIED_UNTIL, "occupied_from_utc"
    )
    assert_instant_equals(
        second["occupied_from_utc"], INSTANT_G2_OCCUPIED_FROM, "occupied_from_utc"
    )
    assert_instant_equals(
        second["occupied_until_utc"], INSTANT_G2_OCCUPIED_UNTIL, "occupied_until_utc"
    )

    withdrawn = fx.withdraw_assignment(second["id"], "personal leave")

    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant_equals(
        withdrawn["released_at"], INSTANT_SEASON_START, "released_at"
    )


def test_the_withdrawn_row_drops_out_of_the_exposure_count(
    two_buf_assignments_and_a_third_buf_game,
):
    """With the second BUF assignment withdrawn, prior exposures are back to one, so
    a third BUF game is accepted and only two rows remain proposed.

    PRD §3.4: "For each of the two team codes, the server counts the official's
    assignments in `PROPOSED`, `CONFIRMED` or `COMPLETED` status whose game belongs to
    the same season program and whose game names that team as either home or away
    side."

    Design: Corner/calculations/withdrawn_assignment_leaves_the_team_exposure_input_set
    """
    official_id = two_buf_assignments_and_a_third_buf_game["official"]["id"]
    third_game = two_buf_assignments_and_a_third_buf_game["third_game"]
    fx.withdraw_assignment(
        two_buf_assignments_and_a_third_buf_game["second_assignment"]["id"],
        "personal leave",
    )

    third = fx.propose_assignment(
        third_game["id"], official_id, "UMPIRE",
        expected_game_version=third_game["version"],
    )
    response = api_client.list_crew_assignments(
        fx.SCHEDULER, {"official_id": official_id, "status": "PROPOSED"}
    )
    rows, meta = validate_paginated(response)

    assert third["status"] == "PROPOSED"
    assert_instant_equals(
        third["occupied_from_utc"], INSTANT_G2_OCCUPIED_UNTIL, "occupied_from_utc"
    )
    assert meta["total_count"] == 2
    assert [row["game_id"] for row in rows] == [
        two_buf_assignments_and_a_third_buf_game["first_game"]["id"],
        third_game["id"],
    ]


# ─── The inclusive appeal deadline ─────────────────────

@pytest.fixture
def two_grades_posted_at_the_same_instant():
    """Two POSTED grades on Dan, both stamped at 21:30 on 13 September, so both
    windows close at 21:30 on 16 September."""
    ctx = fx.posted_grade_for_appeal()
    ctx["second_grade"] = fx.posted_grade(
        ctx["game"]["id"],
        ctx["official"]["id"],
        play_ref="Q3-P23",
        call_category="FALSE_START",
        grade_code="INCORRECT_CALL",
        impact="LOW",
    )
    return ctx


def test_an_appeal_filed_on_the_deadline_instant_is_accepted(
    two_grades_posted_at_the_same_instant,
):
    """The second grade prices at 0.50 and both grades posted at the same instant; an
    appeal filed at exactly 72 hours later is accepted and spends one credit.

    PRD §3.7: "The **appeal window** runs from the grade's `posted_at` forward by the
    program's `appeal_window_hours`, and its boundary is inclusive: an appeal filed at
    exactly the deadline instant is accepted, and only an appeal filed strictly after
    it is refused with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/calculations/appeal_filed_at_the_exact_deadline_instant_is_accepted
    """
    official_id = two_grades_posted_at_the_same_instant["official"]["id"]
    second = two_grades_posted_at_the_same_instant["second_grade"]

    assert second["error_points"] == 0.50
    assert_instant_equals(second["posted_at"], INSTANT_G1_POSTGAME, "posted_at")

    fx.pin_clock(INSTANT_APPEAL_DEADLINE)
    appeal = fx.file_appeal(
        two_grades_posted_at_the_same_instant["grade"]["id"],
        official_id,
        "filed on the last legal instant",
    )
    official = fx.read_official(official_id)

    assert appeal["status"] == "SUBMITTED"
    assert_instant_equals(
        appeal["submitted_at"], INSTANT_APPEAL_DEADLINE, "submitted_at"
    )
    assert official["appeal_credits_remaining"] == 2


def test_one_second_later_the_window_is_closed_and_nothing_is_spent(
    two_grades_posted_at_the_same_instant,
):
    """A second filing one second past the deadline is refused, leaves that grade
    unappealed, and burns no credit.

    PRD §3.7: "With the default of 72 hours, a grade posted at noon on Monday may be
    appealed up to and including noon on Thursday."

    Design: Corner/calculations/appeal_filed_at_the_exact_deadline_instant_is_accepted
    """
    official_id = two_grades_posted_at_the_same_instant["official"]["id"]
    second_grade_id = two_grades_posted_at_the_same_instant["second_grade"]["id"]
    fx.pin_clock(INSTANT_APPEAL_DEADLINE)
    fx.file_appeal(
        two_grades_posted_at_the_same_instant["grade"]["id"],
        official_id,
        "filed on the last legal instant",
    )

    fx.pin_clock(INSTANT_PAST_APPEAL_DEADLINE)
    response = api_client.create_grade_appeal(
        f.grade_appeal_payload(second_grade_id, "one second too late"),
        make_official_headers(official_id),
    )
    validate_error(response, "ERR_APPEAL_WINDOW_CLOSED", 422)

    grade = fx.read_grade(second_grade_id)
    official = fx.read_official(official_id)

    assert grade["appeal_state"] == "NOT_APPEALED"
    assert official["appeal_credits_remaining"] == 2

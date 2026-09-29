"""The gates in front of each write: the shape rules, the program-open rule, the
crew safety and integrity checks, the grading integrity rules, the replay gates,
the advancement criteria, and the two gates on publication and the season lock.
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
    INSTANT_G1_KICKOFF,
    INSTANT_G1_OCCUPIED_FROM,
    INSTANT_G1_OCCUPIED_UNTIL,
    INSTANT_G1_POSTGAME,
    INSTANT_G2_KICKOFF,
    INSTANT_SEASON_START,
)


# ─── A proposal that violates nothing ──────────────────

@pytest.fixture
def one_slot_game_and_an_assignable_umpire():
    """A one-official program with a SCHEDULED game and Dan Ruiz — ACTIVE,
    preseason-cleared, unaffiliated and holding no other assignment."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    return {
        "program": program,
        "official": official,
        "game": fx.schedule_game(program["id"]),
    }


def test_the_clean_proposal_is_written_with_its_occupancy_window(
    one_slot_game_and_an_assignable_umpire,
):
    """Nothing about Dan or the game trips a check, so the row is created as
    PROPOSED with an unstamped release, a computed window, a projected index of 4.80
    and a game still short of its crew.

    PRD §3.4: "While the game's `status` is `SCHEDULED`, posture is `STAFFED` when
    `confirmed_crew_count` is greater than or equal to the program's
    `crew_size_required` and `UNDERSTAFFED` otherwise; because the comparison is
    inclusive, an over-confirmed crew stays `STAFFED` rather than erroring."

    Design: Corner/validations/assignment_satisfying_every_safety_rule_succeeds
    """
    game = one_slot_game_and_an_assignable_umpire["game"]
    official_id = one_slot_game_and_an_assignable_umpire["official"]["id"]

    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            game["id"], official_id, "UMPIRE", game["version"]
        ),
        fx.SCHEDULER,
    )
    assignment = validate_success(response, 201)
    after = fx.read_game(game["id"])
    official = fx.read_official(official_id)

    assert assignment["status"] == "PROPOSED"
    assert assignment["released_at"] is None
    assert_instant_equals(
        assignment["occupied_from_utc"], INSTANT_G1_OCCUPIED_FROM, "occupied_from_utc"
    )
    assert_instant_equals(
        assignment["occupied_until_utc"],
        INSTANT_G1_OCCUPIED_UNTIL,
        "occupied_until_utc",
    )
    assert after["crew_strength_index"] == 4.80
    assert after["crew_strength_variant"] == "PROJECTED"
    assert after["confirmed_crew_count"] == 0
    assert after["crew_posture"] == "UNDERSTAFFED"
    assert official["open_assignment_count"] == 1


def test_confirming_it_staffs_the_crew_without_moving_the_index(
    one_slot_game_and_an_assignable_umpire,
):
    """One confirmation meets a required crew of one, so posture flips to STAFFED
    while the projected index — which already counted him — stays at 4.80.

    PRD §3.4: "Confirmation moves the assignment `PROPOSED → CONFIRMED`, increments
    the game's `confirmed_crew_count` by 1, re-derives the game's `crew_posture`,
    recomputes projected crew strength, and bumps the game's `version` by 1."

    Design: Corner/validations/assignment_satisfying_every_safety_rule_succeeds
    """
    game = one_slot_game_and_an_assignable_umpire["game"]
    assignment = fx.propose_assignment(
        game["id"],
        one_slot_game_and_an_assignable_umpire["official"]["id"],
        "UMPIRE",
        expected_game_version=game["version"],
    )

    confirmed = fx.confirm_assignment(assignment["id"])
    after = fx.read_game(game["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert after["confirmed_crew_count"] == 1
    assert after["crew_posture"] == "STAFFED"
    assert after["crew_strength_index"] == 4.80


# ─── Shape rules run before anything else ──────────────

@pytest.fixture
def active_official_and_his_version():
    """Dan is ACTIVE on a passed exam, and his current version is read for the
    concurrency field a discipline action must pin."""
    program = fx.create_open_program()
    official = fx.register_umpire(program["id"], cleared=False)
    fx.add_training_record(official["id"], f.rules_exam_payload(84.00, "EX-D1"))
    return {
        "program": program,
        "official": fx.read_official(official["id"]),
    }


def test_an_out_of_range_score_and_an_unparseable_instant_are_malformed(
    active_official_and_his_version,
):
    """A physical test scored 105.00 and a game whose kickoff is not a real instant
    are both refused on shape.

    PRD §2.9: "The request body is well-formed: every required input field is
    present, no unknown field is honored, every enum-valued field carries a declared
    value, every score lies within the inclusive range 0.00 through 100.00, every
    timestamp parses as an ISO 8601 UTC instant, integers are non-negative, and a
    `MODIFIED` appeal decision carries a `revised_grade_code` that differs from the
    grade's current `grade_code`."

    Design: Corner/validations/malformed_payloads_are_rejected_with_invalid_request
    """
    official_id = active_official_and_his_version["official"]["id"]
    program_id = active_official_and_his_version["program"]["id"]

    validate_error(
        api_client.create_training_record(
            official_id, f.physical_test_payload(105.00, "PT-BAD"), fx.TRAINING
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_game(
            f.game_payload(program_id, kickoff_utc="2026-13-45T99:00:00Z"),
            fx.DIRECTOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    rows, meta = validate_paginated(api_client.list_games(fx.SCHEDULER))
    assert meta["total_count"] == 0


def test_a_suspension_without_a_game_count_is_malformed(
    active_official_and_his_version,
):
    """A SUSPENSION carrying no `suspension_games`, and one carrying zero, are both
    refused on shape, and neither refusal touches the official.

    PRD §3.8: "A `SUSPENSION` submitted without `suspension_games`, or with a value
    below 1, is rejected with `ERR_INVALID_REQUEST`; conversely `suspension_games`
    must be null for a `WARNING` and for a `REMEDIATION`."

    Design: Corner/validations/malformed_payloads_are_rejected_with_invalid_request
    """
    official = active_official_and_his_version["official"]
    pinned = {
        "official_id": official["id"],
        "reason_category": "CONDUCT",
        "severity": "SUSPENSION",
        "expected_official_version": official["version"],
    }

    validate_error(
        api_client.create_discipline_action(dict(pinned), fx.DIRECTOR),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_discipline_action(
            dict(pinned, suspension_games=0), fx.DIRECTOR
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    after = fx.read_official(official["id"])

    assert after["status"] == "ACTIVE"
    assert after["version"] == official["version"]


# ─── Business writes need an open program ──────────────

def test_a_registration_before_the_program_opens_is_refused():
    """While the program is still CONFIGURING the registration is refused, and the
    same call succeeds once the program is opened.

    PRD §2.5: "A business write attempted while the owning program is still
    `CONFIGURING`, or after it has reached `POSTSEASON_LOCKED`, is rejected with
    `ERR_SEASON_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/business_writes_outside_an_open_program_are_rejected
    """
    fx.pin_clock(INSTANT_SEASON_START)
    program = fx.create_program()

    validate_error(
        api_client.create_official(
            f.official_payload(
                program["id"],
                full_name="Too Early",
                position="REFEREE",
                seasons_experience=3,
                home_market_code="PHI",
            ),
            fx.DIRECTOR,
        ),
        "ERR_SEASON_NOT_OPEN",
        409,
    )

    opened = fx.open_program(program["id"])
    accepted = fx.register_official(
        program["id"],
        full_name="Right On Time",
        position="REFEREE",
        seasons_experience=3,
        home_market_code="PHI",
    )

    assert opened["status"] == "OPEN"
    assert accepted["status"] == "CANDIDATE"


def test_after_the_postseason_lock_both_writes_and_reopening_are_refused():
    """The locked program reports zero eligible officials, refuses a new game, and
    refuses to be reopened — the same error at both ends of the lifecycle.

    PRD §2.5: "The same error is returned when the program's own lifecycle
    operations are called from the wrong state — opening a program that is not
    `CONFIGURING`, or locking the postseason on a program that is not `OPEN`."

    Design: Corner/validations/business_writes_outside_an_open_program_are_rejected
    """
    program = fx.create_open_program()
    fx.register_official(
        program["id"],
        full_name="Right On Time",
        position="REFEREE",
        seasons_experience=3,
        home_market_code="PHI",
    )

    locked = fx.lock_postseason(program["id"])

    assert locked["status"] == "POSTSEASON_LOCKED"
    assert locked["eligible_official_count"] == 0

    validate_error(
        api_client.create_game(f.game_payload(program["id"]), fx.DIRECTOR),
        "ERR_SEASON_NOT_OPEN",
        409,
    )
    validate_error(
        api_client.open_season_program(program["id"], fx.DIRECTOR),
        "ERR_SEASON_NOT_OPEN",
        409,
    )


# ─── The conflict-of-interest gate ─────────────────────

def test_an_official_affiliated_with_a_playing_team_cannot_work_that_game():
    """Kim's MIA affiliation matches the home team, so the proposal is refused and
    leaves the game untouched, while the same official is assignable to a game
    between two other teams.

    PRD §3.4: "The official's `affiliated_team_code` must be neither the game's
    `home_team_code` nor its `away_team_code`, else
    `ERR_TEAM_CONFLICT_OF_INTEREST`."

    Design: Corner/validations/assignment_for_affiliated_team_returns_conflict_of_interest
    """
    program = fx.solo_program()
    kim = fx.register_official(
        program["id"],
        full_name="Kim Ortega",
        position="DOWN_JUDGE",
        seasons_experience=9,
        home_market_code="DEN",
        affiliated_team_code="MIA",
    )
    fx.clear_official(
        kim["id"], exam_score=93.00, exam_code="EX-K1",
        physical_score=85.00, physical_code="PT-K1",
    )
    home_game = fx.schedule_game(program["id"])
    neutral_game = fx.schedule_game(
        program["id"],
        home_team_code="BUF",
        away_team_code="DEN",
        venue_market_code="BUF",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                home_game["id"], kim["id"], "DOWN_JUDGE", home_game["version"]
            ),
            fx.SCHEDULER,
        ),
        "ERR_TEAM_CONFLICT_OF_INTEREST",
        409,
    )

    untouched = fx.read_game(home_game["id"])
    accepted = fx.propose_assignment(
        neutral_game["id"], kim["id"], "DOWN_JUDGE",
        expected_game_version=neutral_game["version"],
    )

    assert untouched["crew_strength_index"] == 0.00
    assert untouched["version"] == home_game["version"]
    assert accepted["status"] == "PROPOSED"


# ─── The two assignability conjuncts fail one at a time ──

@pytest.fixture
def a_suspended_official_and_an_uncleared_one():
    """Dan is cleared but suspended for two games; Tom Wells passed only the rules
    exam, so he is ACTIVE and un-cleared. One SCHEDULED game awaits them both."""
    program = fx.solo_program()
    dan = fx.register_umpire(program["id"])
    suspension = fx.open_discipline(
        dan["id"], "CONDUCT", "SUSPENSION", suspension_games=2
    )
    tom = fx.register_official(
        program["id"],
        full_name="Tom Wells",
        position="REFEREE",
        seasons_experience=11,
        home_market_code="SEA",
        tier="TIER_2",
    )
    fx.add_training_record(tom["id"], f.rules_exam_payload(90.00, "EX-T1"))
    return {
        "program": program,
        "dan": dan,
        "tom": tom,
        "suspension": suspension,
        "game": fx.schedule_game(program["id"]),
    }


def test_a_suspended_official_trips_the_active_gate_though_he_is_cleared(
    a_suspended_official_and_an_uncleared_one,
):
    """The suspension carries its game count and leaves clearance intact, so the
    refusal names the status gate and not the clearance gate.

    PRD §3.4: "The official must be `ACTIVE` (`ERR_OFFICIAL_NOT_ACTIVE`) and
    `preseason_cleared` (`ERR_PRESEASON_NOT_CLEARED`)."

    Design: Corner/validations/assignment_of_suspended_or_uncleared_official_is_rejected
    """
    game = a_suspended_official_and_an_uncleared_one["game"]
    dan = fx.read_official(a_suspended_official_and_an_uncleared_one["dan"]["id"])

    assert a_suspended_official_and_an_uncleared_one["suspension"][
        "suspension_games"
    ] == 2
    assert dan["status"] == "SUSPENDED"
    assert dan["preseason_cleared"] is True

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game["id"], dan["id"], "UMPIRE", game["version"]
            ),
            fx.SCHEDULER,
        ),
        "ERR_OFFICIAL_NOT_ACTIVE",
        409,
    )


def test_an_active_but_uncleared_official_trips_the_clearance_gate(
    a_suspended_official_and_an_uncleared_one,
):
    """Tom is ACTIVE on his exam alone, so his refusal names clearance, and neither
    rejected call wrote an assignment row.

    PRD §3.2: "An official who has passed the exam but not yet the physical test is
    therefore `ACTIVE` and still un-cleared, and any attempt to crew them is rejected
    with `ERR_PRESEASON_NOT_CLEARED`."

    Design: Corner/validations/assignment_of_suspended_or_uncleared_official_is_rejected
    """
    game = a_suspended_official_and_an_uncleared_one["game"]
    tom = fx.read_official(a_suspended_official_and_an_uncleared_one["tom"]["id"])

    assert tom["status"] == "ACTIVE"
    assert tom["preseason_cleared"] is False

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game["id"], tom["id"], "REFEREE", game["version"]
            ),
            fx.SCHEDULER,
        ),
        "ERR_PRESEASON_NOT_CLEARED",
        409,
    )
    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game["id"],
                a_suspended_official_and_an_uncleared_one["dan"]["id"],
                "UMPIRE",
                game["version"],
            ),
            fx.SCHEDULER,
        ),
        "ERR_OFFICIAL_NOT_ACTIVE",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_crew_assignments(fx.SCHEDULER, {"game_id": game["id"]})
    )

    assert rows == []
    assert meta["total_count"] == 0


# ─── A confirmed slot is not superseded ────────────────

@pytest.fixture
def game_with_a_confirmed_umpire_slot():
    """A two-slot program whose UMPIRE position is CONFIRMED to Dan, with Rita
    registered, cleared and window-free."""
    program = fx.crew_program()
    dan = fx.register_umpire(program["id"])
    rita = fx.register_referee(program["id"])
    game = fx.schedule_game(program["id"])
    assignment = fx.propose_assignment(
        game["id"], dan["id"], "UMPIRE", expected_game_version=game["version"]
    )
    fx.confirm_assignment(assignment["id"])
    return {
        "program": program,
        "dan": dan,
        "rita": rita,
        "game": game,
        "umpire_assignment": assignment,
    }


def test_a_second_umpire_on_a_confirmed_slot_is_refused(
    game_with_a_confirmed_umpire_slot,
):
    """Because the incumbent is CONFIRMED rather than merely PROPOSED, the incoming
    proposal is refused and the slot still holds exactly one row.

    PRD §3.4: "If a `CONFIRMED` assignment already occupies the requested `position`
    on that game, the proposal is refused with `ERR_POSITION_ALREADY_CONFIRMED`."

    Design: Corner/validations/second_confirmed_assignment_on_a_position_is_rejected
    """
    game_id = game_with_a_confirmed_umpire_slot["game"]["id"]

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game_id,
                game_with_a_confirmed_umpire_slot["rita"]["id"],
                "UMPIRE",
                fx.game_version(game_id),
            ),
            fx.SCHEDULER,
        ),
        "ERR_POSITION_ALREADY_CONFIRMED",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_crew_assignments(
            fx.SCHEDULER, {"game_id": game_id, "position": "UMPIRE"}
        )
    )

    assert meta["total_count"] == 1
    assert rows[0]["id"] == game_with_a_confirmed_umpire_slot["umpire_assignment"]["id"]
    assert rows[0]["status"] == "CONFIRMED"


def test_the_same_official_on_a_free_position_is_accepted(
    game_with_a_confirmed_umpire_slot,
):
    """The rule is scoped to one position on one game, so Rita takes the referee slot
    and the index becomes 17.28 over the required crew of two.

    PRD §3.4: "The game's `crew_strength_index` is then the sum of those
    already-rounded contributions, taken in `created_at` ascending order, divided by
    the program's `crew_size_required`, and rounded half up to two decimal places."

    Design: Corner/validations/second_confirmed_assignment_on_a_position_is_rejected
    """
    game_id = game_with_a_confirmed_umpire_slot["game"]["id"]

    accepted = fx.propose_assignment(
        game_id, game_with_a_confirmed_umpire_slot["rita"]["id"], "REFEREE"
    )
    after = fx.read_game(game_id)

    assert accepted["status"] == "PROPOSED"
    assert after["crew_strength_index"] == 8.64
    assert after["confirmed_crew_count"] == 1
    assert after["crew_posture"] == "UNDERSTAFFED"


# ─── One grade per play per official ───────────────────

@pytest.fixture
def played_crew_game_with_one_draft_grade():
    """A played two-official game — Dan as umpire, Rita as referee — with a DRAFT
    grade already written against Dan on play Q3-P22."""
    ctx = fx.crew_game()
    fx.pin_clock(INSTANT_G1_KICKOFF)
    fx.kickoff(ctx["game"]["id"])
    fx.pin_clock(INSTANT_G1_POSTGAME)
    ctx["game"] = fx.mark_played(ctx["game"]["id"])
    ctx["grade"] = fx.grade_play(
        ctx["game"]["id"],
        ctx["umpire"]["id"],
        play_ref="Q3-P22",
        call_category="HOLDING",
        grade_code="MISSED_CALL",
        impact="LOW",
    )
    return ctx


def test_the_same_play_cannot_be_graded_twice_for_one_official(
    played_crew_game_with_one_draft_grade,
):
    """The second grade on Q3-P22 for Dan is refused, and the existing DRAFT keeps its
    original call category.

    PRD §3.6: "The triple of `game_id`, `official_id` and `play_ref` must be unique: a
    repeat is refused with `ERR_DUPLICATE_PLAY_GRADE`, whatever state the earlier
    grade has since reached."

    Design: Corner/validations/duplicate_play_ref_for_the_same_official_is_rejected
    """
    game_id = played_crew_game_with_one_draft_grade["game"]["id"]
    umpire_id = played_crew_game_with_one_draft_grade["umpire"]["id"]

    validate_error(
        api_client.create_play_grade(
            f.play_grade_payload(
                game_id, umpire_id, "Q3-P22", "PASS_INTERFERENCE", "CORRECT", "LOW"
            ),
            fx.GRADER,
        ),
        "ERR_DUPLICATE_PLAY_GRADE",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_play_grades(
            fx.GRADER, {"game_id": game_id, "official_id": umpire_id}
        )
    )

    assert meta["total_count"] == 1
    assert rows[0]["play_ref"] == "Q3-P22"
    assert rows[0]["grade_status"] == "DRAFT"
    assert rows[0]["call_category"] == "HOLDING"


def test_the_same_play_reference_is_free_for_another_official(
    played_crew_game_with_one_draft_grade,
):
    """Uniqueness is per official, so Rita can be graded on Q3-P22, and her referee
    position factor prices the same missed call at 0.90.

    PRD §3.6: "The three factors are a grade base of 0.00 for `CORRECT`, 1.00 for
    `INCORRECT_CALL`, 1.50 for `MISSED_CALL` and 2.00 for `INADVERTENT_WHISTLE`; an
    impact multiplier of 0.50 for `LOW`, 1.00 for `MEDIUM`, 1.75 for `HIGH` and 2.50
    for `GAME_CRITICAL`; and a position factor of 1.20 for a `REFEREE`, 1.00 for an
    `UMPIRE` and 0.90 for a `DOWN_JUDGE`, read from the graded official's registered
    `position`."

    Design: Corner/validations/duplicate_play_ref_for_the_same_official_is_rejected
    """
    referee_grade = fx.grade_play(
        played_crew_game_with_one_draft_grade["game"]["id"],
        played_crew_game_with_one_draft_grade["referee"]["id"],
        play_ref="Q3-P22",
        call_category="HOLDING",
        grade_code="MISSED_CALL",
        impact="LOW",
    )

    assert referee_grade["grade_status"] == "DRAFT"
    assert referee_grade["error_points"] == 0.90


# ─── Only officials who worked the game are gradeable ──

@pytest.fixture
def played_game_with_a_bystander_and_a_withdrawn_official():
    """Dan worked the game to COMPLETED; Rita was never assigned; Tom's proposal was
    withdrawn before kickoff."""
    program = fx.solo_program()
    dan = fx.register_umpire(program["id"])
    rita = fx.register_referee(program["id"])
    tom = fx.register_official(
        program["id"],
        full_name="Tom Wells",
        position="REFEREE",
        seasons_experience=11,
        home_market_code="SEA",
        tier="TIER_2",
    )
    fx.clear_official(
        tom["id"], exam_score=90.00, exam_code="EX-T1",
        physical_score=77.00, physical_code="PT-T1",
    )
    game = fx.schedule_game(program["id"])
    dan_assignment = fx.propose_assignment(
        game["id"], dan["id"], "UMPIRE", expected_game_version=game["version"]
    )
    fx.confirm_assignment(dan_assignment["id"])
    tom_assignment = fx.propose_assignment(game["id"], tom["id"], "REFEREE")
    withdrawn = fx.withdraw_assignment(
        tom_assignment["id"], "reassigned to another market"
    )
    fx.pin_clock(INSTANT_G1_KICKOFF)
    fx.kickoff(game["id"])
    fx.pin_clock(INSTANT_G1_POSTGAME)
    return {
        "program": program,
        "dan": dan,
        "rita": rita,
        "tom": tom,
        "game": fx.mark_played(game["id"]),
        "withdrawn": withdrawn,
    }


def test_neither_a_bystander_nor_a_withdrawn_official_can_be_graded(
    played_game_with_a_bystander_and_a_withdrawn_official,
):
    """Rita never held an assignment and Tom's was withdrawn, so both grades are
    refused with the same assignment-state error.

    PRD §3.6: "And the graded official must actually have worked the game — they must
    hold an assignment on that game whose status is `CONFIRMED` or `COMPLETED`, else
    the grade is refused with `ERR_ASSIGNMENT_STATE_INVALID`."

    Design: Corner/validations/play_grade_for_an_unassigned_official_is_rejected
    """
    game_id = played_game_with_a_bystander_and_a_withdrawn_official["game"]["id"]

    assert played_game_with_a_bystander_and_a_withdrawn_official["withdrawn"][
        "status"
    ] == "WITHDRAWN"

    validate_error(
        api_client.create_play_grade(
            f.play_grade_payload(
                game_id,
                played_game_with_a_bystander_and_a_withdrawn_official["rita"]["id"],
                "Q1-P03",
                "HOLDING",
                "CORRECT",
                "LOW",
            ),
            fx.GRADER,
        ),
        "ERR_ASSIGNMENT_STATE_INVALID",
        409,
    )
    validate_error(
        api_client.create_play_grade(
            f.play_grade_payload(
                game_id,
                played_game_with_a_bystander_and_a_withdrawn_official["tom"]["id"],
                "Q1-P03",
                "HOLDING",
                "CORRECT",
                "LOW",
            ),
            fx.GRADER,
        ),
        "ERR_ASSIGNMENT_STATE_INVALID",
        409,
    )


def test_the_official_whose_assignment_completed_is_gradeable(
    played_game_with_a_bystander_and_a_withdrawn_official,
):
    """Dan's assignment reached COMPLETED when play ended, which satisfies the rule,
    so his grade is written as a DRAFT.

    PRD §3.6: "A `GradingSupervisor` writes a **play grade** against one official on
    one game, naming the `game_id`, the `official_id` being graded, a `play_ref` of
    between 1 and 40 non-blank characters, a `call_category` of `HOLDING`,
    `PASS_INTERFERENCE`, `FALSE_START`, `ROUGHING_PASSER` or `OTHER`, a `grade_code`
    of `CORRECT`, `INCORRECT_CALL`, `MISSED_CALL` or `INADVERTENT_WHISTLE`, and an
    `impact` of `LOW`, `MEDIUM`, `HIGH` or `GAME_CRITICAL`."

    Design: Corner/validations/play_grade_for_an_unassigned_official_is_rejected
    """
    accepted = fx.grade_play(
        played_game_with_a_bystander_and_a_withdrawn_official["game"]["id"],
        played_game_with_a_bystander_and_a_withdrawn_official["dan"]["id"],
        play_ref="Q1-P03",
        call_category="HOLDING",
        grade_code="CORRECT",
        impact="LOW",
    )

    assert accepted["grade_status"] == "DRAFT"
    assert accepted["error_points"] == 0.00


# ─── Configuration is checked before hardware ──────────

@pytest.fixture
def live_game_with_an_online_and_an_offline_booth():
    """An IN_PROGRESS game, BOOTH-1 ONLINE with capacity 2, and BOOTH-DARK
    OFFLINE."""
    ctx = fx.in_progress_game_with_station(
        station_code="BOOTH-1", concurrent_capacity=2
    )
    ctx["dark_booth"] = fx.register_station(
        station_code="BOOTH-DARK", concurrent_capacity=4, status="OFFLINE"
    )
    return ctx


def test_a_category_the_program_never_enabled_is_refused(
    live_game_with_an_online_and_an_offline_booth,
):
    """GAME_ADMIN is a declared category that this program did not make reviewable, so
    the review is refused even on a healthy booth.

    PRD §3.5: "The requested `category` must appear in the program's
    `reviewable_categories`, else `ERR_CATEGORY_NOT_REVIEWABLE`."

    Design: Corner/validations/replay_review_category_and_station_gates_are_ordered
    """
    validate_error(
        api_client.create_replay_review(
            f.replay_review_payload(
                live_game_with_an_online_and_an_offline_booth["game"]["id"],
                live_game_with_an_online_and_an_offline_booth["station"]["id"],
                play_ref="Q2-P11",
                category="GAME_ADMIN",
            ),
            fx.REPLAY,
        ),
        "ERR_CATEGORY_NOT_REVIEWABLE",
        422,
    )

    assert (
        fx.read_station(
            live_game_with_an_online_and_an_offline_booth["station"]["id"]
        )["active_review_count"]
        == 0
    )


def test_a_reviewable_category_still_needs_an_online_booth(
    live_game_with_an_online_and_an_offline_booth,
):
    """The same TURNOVER review is refused on the dark booth and accepted on the
    online one, and only the accepted review moves a counter.

    PRD §3.5: "The booth's `status` must be `ONLINE`, else
    `ERR_REPLAY_STATION_OFFLINE`."

    Design: Corner/validations/replay_review_category_and_station_gates_are_ordered
    """
    game_id = live_game_with_an_online_and_an_offline_booth["game"]["id"]
    dark_booth = live_game_with_an_online_and_an_offline_booth["dark_booth"]

    assert dark_booth["status"] == "OFFLINE"

    validate_error(
        api_client.create_replay_review(
            f.replay_review_payload(
                game_id, dark_booth["id"], play_ref="Q2-P11", category="TURNOVER"
            ),
            fx.REPLAY,
        ),
        "ERR_REPLAY_STATION_OFFLINE",
        409,
    )

    accepted = fx.open_review(
        game_id,
        live_game_with_an_online_and_an_offline_booth["station"]["id"],
        play_ref="Q2-P11",
        category="TURNOVER",
    )

    assert accepted["status"] == "INITIATED"
    assert (
        fx.read_station(
            live_game_with_an_online_and_an_offline_booth["station"]["id"]
        )["active_review_count"]
        == 1
    )
    assert fx.read_station(dark_booth["id"])["active_review_count"] == 0


# ─── The advancement criteria bite at screening ────────

@pytest.fixture
def two_applicants_one_short_of_the_experience_floor():
    """Dan — TIER_2 with six seasons — has applied for TIER_1, and Lee Park — TIER_3
    with seven — has applied for TIER_2."""
    program = fx.create_open_program()
    dan = fx.register_umpire(program["id"])
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
    return {
        "program": program,
        "dan": dan,
        "lee": lee,
        "dan_application": fx.create_application(dan["id"], "TIER_1"),
        "lee_application": fx.create_application(lee["id"], "TIER_2"),
    }


def test_filing_is_free_but_screening_enforces_the_experience_floor(
    two_applicants_one_short_of_the_experience_floor,
):
    """Dan's application is accepted on filing, then refused at screening on his six
    seasons, and it stays SUBMITTED with no screening stamp.

    PRD §3.3: "Their `seasons_experience` must be at least 5 for a `TIER_2`
    application and at least 8 for a `TIER_1` application; and their season record's
    `accuracy_index` must be at least 90.00."

    Design: Corner/validations/screening_an_underexperienced_applicant_is_rejected
    """
    application = two_applicants_one_short_of_the_experience_floor["dan_application"]

    assert application["status"] == "SUBMITTED"
    assert application["return_count"] == 0

    validate_error(
        api_client.screen_application(application["id"], fx.EVALUATOR),
        "ERR_ADVANCEMENT_CRITERIA_NOT_MET",
        422,
    )

    after = fx.read_application(application["id"], fx.EVALUATOR)

    assert after["status"] == "SUBMITTED"
    assert after["screened_at"] is None


def test_the_adjacent_applicant_over_the_floor_screens_cleanly(
    two_applicants_one_short_of_the_experience_floor,
):
    """Lee's seven seasons clear the TIER_2 floor of five and TIER_3 to TIER_2 is
    adjacent, so his application is screened at the season-start clock.

    PRD §3.3: "Every comparison is inclusive, so an official sitting exactly on a
    floor qualifies, and because an official with no graded plays reads an
    `accuracy_index` of exactly 100.00, a newly cleared official passes the accuracy
    gate on an empty grading history."

    Design: Corner/validations/screening_an_underexperienced_applicant_is_rejected
    """
    screened = fx.screen_application(
        two_applicants_one_short_of_the_experience_floor["lee_application"]["id"]
    )

    assert screened["status"] == "SCREENED"
    assert_instant_equals(
        screened["screened_at"], INSTANT_SEASON_START, "screened_at"
    )


# ─── Two legs of the committee gate ────────────────────

@pytest.fixture
def screened_application_with_one_report():
    """Lee's SCREENED TIER_2 application carrying a single report that composites to
    76.10."""
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
    fx.screen_application(application["id"])
    first = fx.add_field_evaluation(
        application["id"],
        mechanics_score=80.00,
        rules_score=76.00,
        presence_score=70.00,
        headers=fx.EVALUATOR,
    )
    return {
        "program": program,
        "official": lee,
        "application": application,
        "first_report": first,
    }


def test_one_report_is_below_the_minimum_count(screened_application_with_one_report):
    """The single 76.10 report fails the count leg of the gate, so the forward is
    refused.

    PRD §3.3: "The application must carry at least two field evaluation reports plus
    one additional report for each return it has absorbed — that is, the report count
    must be at least 2 plus the current `return_count`, which forces at least one
    fresh observation per return."

    Design: Corner/validations/submit_to_committee_below_the_evaluation_bar_is_rejected
    """
    assert screened_application_with_one_report["first_report"][
        "composite_score"
    ] == 76.10

    validate_error(
        api_client.submit_application_to_committee(
            screened_application_with_one_report["application"]["id"], fx.EVALUATOR
        ),
        "ERR_EVALUATION_REQUIREMENTS_NOT_MET",
        422,
    )


def test_two_reports_averaging_below_the_bar_fail_the_same_gate(
    screened_application_with_one_report,
):
    """A second report at 71.10 satisfies the count but drops the average to 73.60,
    which fails the average leg and leaves the application SCREENED.

    PRD §3.3: "And `evaluation_average` must be at least 75.00."

    Design: Corner/validations/submit_to_committee_below_the_evaluation_bar_is_rejected
    """
    application_id = screened_application_with_one_report["application"]["id"]

    second = fx.add_field_evaluation(
        application_id,
        mechanics_score=74.00,
        rules_score=70.00,
        presence_score=68.00,
        headers=fx.EVALUATOR_2,
    )
    application = fx.read_application(application_id, fx.EVALUATOR)

    assert second["composite_score"] == 71.10
    assert application["evaluation_average"] == 73.60

    validate_error(
        api_client.submit_application_to_committee(application_id, fx.EVALUATOR),
        "ERR_EVALUATION_REQUIREMENTS_NOT_MET",
        422,
    )

    assert fx.read_application(application_id, fx.EVALUATOR)["status"] == "SCREENED"


# ─── The lock will not run over a live game ────────────

def test_the_postseason_cannot_be_locked_while_a_game_is_in_progress():
    """The lock is refused, the program keeps its status and version, and none of the
    recomputes the lock performs has run.

    PRD §3.9: "The season ends when the `OfficiatingDirector` locks the postseason,
    which is legal only from program `status` `OPEN` and is refused with
    `ERR_GAMES_IN_PROGRESS` while any game of the program is still `IN_PROGRESS`."

    Design: Corner/validations/postseason_lock_with_a_game_in_progress_is_rejected
    """
    ctx = fx.in_progress_game_with_station()
    program_id = ctx["program"]["id"]
    before = fx.read_program(program_id)

    assert before["status"] == "OPEN"

    validate_error(
        api_client.lock_postseason(program_id, fx.DIRECTOR),
        "ERR_GAMES_IN_PROGRESS",
        409,
    )

    after = fx.read_program(program_id)
    record = fx.season_record_for(ctx["official"]["id"])

    assert after["status"] == "OPEN"
    assert after["version"] == before["version"]
    assert after["eligible_official_count"] == 0
    assert record["accuracy_variant"] == "PROVISIONAL"
    assert record["retention_score"] == 0.00


# ─── Publication waits for the cited grade to be final ──

@pytest.fixture
def drafted_report_citing_a_posted_grade():
    """A PLAYED game with Dan's POSTED grade and a POOL_REPORT draft citing it."""
    ctx = fx.posted_grade_for_appeal()
    ctx["report"] = fx.draft_pool_report(
        ctx["game"]["id"], ctx["grade"]["id"], report_type="POOL_REPORT"
    )
    return ctx


def test_a_report_citing_a_merely_posted_grade_cannot_be_published(
    drafted_report_citing_a_posted_grade,
):
    """Drafting against a POSTED grade is allowed, but publication is refused while
    that grade is not yet FINAL, and the draft keeps its null stamp.

    PRD §3.9: "Publication is legal only from `DRAFT` — a second attempt is refused
    with `ERR_REPORT_STATE_INVALID` — and only when the cited play grade has
    `grade_status` `FINAL` and an `appeal_state` that is not `APPEAL_PENDING`;
    otherwise the department would be commenting publicly on a call still under
    challenge, and the request is refused with `ERR_CITED_GRADE_NOT_FINAL`."

    Design: Corner/validations/publishing_a_report_citing_a_non_final_grade_is_rejected
    """
    report = drafted_report_citing_a_posted_grade["report"]

    assert report["status"] == "DRAFT"
    assert report["published_at"] is None

    validate_error(
        api_client.publish_pool_report(report["id"], fx.COMMUNICATIONS),
        "ERR_CITED_GRADE_NOT_FINAL",
        409,
    )

    after = fx.read_pool_report(report["id"])

    assert after["status"] == "DRAFT"
    assert after["published_at"] is None


def test_finalizing_the_game_unblocks_the_same_publication(
    drafted_report_citing_a_posted_grade,
):
    """Once the game is finalized the cited grade is FINAL, and the identical publish
    call succeeds and stamps the logical clock.

    PRD §3.9: "Publication moves the report `DRAFT → PUBLISHED` and stamps
    `published_at` from the logical clock."

    Design: Corner/validations/publishing_a_report_citing_a_non_final_grade_is_rejected
    """
    report_id = drafted_report_citing_a_posted_grade["report"]["id"]
    validate_error(
        api_client.publish_pool_report(report_id, fx.COMMUNICATIONS),
        "ERR_CITED_GRADE_NOT_FINAL",
        409,
    )

    fx.finalize_game(drafted_report_citing_a_posted_grade["game"]["id"])
    published = fx.publish_pool_report(report_id)

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(
        published["published_at"], INSTANT_G1_POSTGAME, "published_at"
    )

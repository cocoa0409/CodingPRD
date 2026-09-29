"""Composite setup helpers.

Every test starts against an empty database, so each helper builds the whole
precondition chain from scratch: pin the logical clock, create and open a season
program, register officials and clear them for the preseason, schedule games,
staff crews, and grade plays.

All helpers return the parsed `data` object of the call they made, so a test can
read ids, versions and derived fields straight off the result.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    INSTANT_G1_KICKOFF,
    INSTANT_G1_POSTGAME,
    INSTANT_SEASON_START,
    TEST_DEFAULTS,
)
from .test_users import (
    APPEAL_REVIEWER_USER_ID,
    EVALUATOR_2_USER_ID,
    EVALUATOR_USER_ID,
    GRADER_USER_ID,
    TEST_USERS,
    make_field_evaluator_headers,
    make_grading_supervisor_headers,
    make_official_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
GRADER = make_grading_supervisor_headers(GRADER_USER_ID)
APPEAL_REVIEWER = make_grading_supervisor_headers(APPEAL_REVIEWER_USER_ID)
TRAINING = TEST_USERS["training_coordinator_headers"]
REPLAY = TEST_USERS["replay_official_headers"]
COMMUNICATIONS = TEST_USERS["communications_headers"]
EVALUATOR = make_field_evaluator_headers(EVALUATOR_USER_ID)
EVALUATOR_2 = make_field_evaluator_headers(EVALUATOR_2_USER_ID)


# ─── The logical clock ─────────────────────────────────

def pin_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> None:
    """Move the server-held logical clock to `instant`."""
    response = api_client.set_clock(instant, headers or DIRECTOR)
    assert response.status_code == 200, (
        f"pinning the clock to {instant} failed with HTTP "
        f"{response.status_code}: {response.text}"
    )


# ─── Season programs ───────────────────────────────────

def create_program(
    headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Create a DRAFT season program for the default season year."""
    response = api_client.create_season_program(
        f.season_program_payload(**overrides), headers or DIRECTOR
    )
    return get_success_data(response, 201)


def open_program(
    program_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.open_season_program(program_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def lock_postseason(
    program_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.lock_postseason(program_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def read_program(
    program_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_season_program(program_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def create_open_program(**overrides: Any) -> Dict[str, Any]:
    """Pin the clock to the start of the season, then create and open a program."""
    pin_clock(INSTANT_SEASON_START)
    program = create_program(**overrides)
    open_program(program["id"])
    return program


def solo_program(**overrides: Any) -> Dict[str, Any]:
    """An OPEN program whose crews are a single official, so one confirmation
    staffs a game."""
    overrides.setdefault("crew_size_required", 1)
    return create_open_program(**overrides)


def crew_program(**overrides: Any) -> Dict[str, Any]:
    """An OPEN program that leaves `crew_size_required` at its default of two."""
    return create_open_program(**overrides)


# ─── Officials and their training records ──────────────

def register_official(
    program_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    response = api_client.create_official(
        f.official_payload(program_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(response, 201)


def add_training_record(
    official_id: str, payload: dict, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.create_training_record(
        official_id, payload, headers or TRAINING
    )
    return get_success_data(response, 201)


def clear_official(
    official_id: str,
    *,
    exam_score: float = 84.00,
    exam_code: str = "EX-U1",
    physical_score: float = 79.00,
    physical_code: str = "PT-U1",
) -> None:
    """File the passing rules exam and physical test that together make an
    official preseason-cleared."""
    add_training_record(official_id, f.rules_exam_payload(exam_score, exam_code))
    add_training_record(
        official_id, f.physical_test_payload(physical_score, physical_code)
    )


def register_umpire(
    program_id: str, *, cleared: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Dan Ruiz — a TIER_2 umpire with six seasons of experience."""
    overrides.setdefault("full_name", "Dan Ruiz")
    overrides.setdefault("position", "UMPIRE")
    overrides.setdefault("seasons_experience", 6)
    overrides.setdefault("home_market_code", "MIA")
    overrides.setdefault("tier", "TIER_2")
    official = register_official(program_id, **overrides)
    if cleared:
        clear_official(
            official["id"],
            exam_score=84.00,
            exam_code="EX-U1",
            physical_score=79.00,
            physical_code="PT-U1",
        )
    return official


def register_referee(
    program_id: str, *, cleared: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Rita Vance — a TIER_2 referee with fourteen seasons of experience, above
    the experience cap the crew-strength formula applies."""
    overrides.setdefault("full_name", "Rita Vance")
    overrides.setdefault("position", "REFEREE")
    overrides.setdefault("seasons_experience", 14)
    overrides.setdefault("home_market_code", "BUF")
    overrides.setdefault("tier", "TIER_2")
    official = register_official(program_id, **overrides)
    if cleared:
        clear_official(
            official["id"],
            exam_score=91.00,
            exam_code="EX-R1",
            physical_score=88.00,
            physical_code="PT-R1",
        )
    return official


def read_official(
    official_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_official(official_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def official_version(official_id: str) -> int:
    """The official's current `version`, for the optimistic-concurrency field a
    discipline action must carry."""
    return read_official(official_id)["version"]


# ─── Games ─────────────────────────────────────────────

def schedule_game(
    program_id: str,
    *,
    home_team_code: Optional[str] = None,
    away_team_code: Optional[str] = None,
    venue_market_code: Optional[str] = None,
    kickoff_utc: str = INSTANT_G1_KICKOFF,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule a game. The default matchup is BUF at MIA with a 17:00 kickoff on
    13 September 2026."""
    response = api_client.create_game(
        f.game_payload(
            program_id,
            home_team_code=home_team_code,
            away_team_code=away_team_code,
            venue_market_code=venue_market_code,
            kickoff_utc=kickoff_utc,
            **overrides,
        ),
        headers or DIRECTOR,
    )
    return get_success_data(response, 201)


def read_game(
    game_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_game(game_id, headers or SCHEDULER)
    return get_success_data(response, 200)


def game_version(game_id: str) -> int:
    """The game's current `version`, for the optimistic-concurrency field a crew
    assignment must carry."""
    return read_game(game_id)["version"]


def kickoff(game_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    response = api_client.kickoff_game(game_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def mark_played(
    game_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.mark_game_played(game_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def finalize_game(
    game_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.finalize_game(game_id, headers or DIRECTOR)
    return get_success_data(response, 200)


# ─── Crew assignments ──────────────────────────────────

def propose_assignment(
    game_id: str,
    official_id: str,
    position: str,
    *,
    expected_game_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Propose one crew assignment, reading the game's current version first when
    the caller does not pin one."""
    if expected_game_version is None:
        expected_game_version = game_version(game_id)
    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            game_id, official_id, position, expected_game_version
        ),
        headers or SCHEDULER,
    )
    return get_success_data(response, 201)


def confirm_assignment(
    assignment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.confirm_crew_assignment(assignment_id, headers or SCHEDULER)
    return get_success_data(response, 200)


def withdraw_assignment(
    assignment_id: str,
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.withdraw_crew_assignment(
        assignment_id, headers or SCHEDULER, f.withdraw_assignment_payload(reason)
    )
    return get_success_data(response, 200)


def staff_assignment(
    game_id: str,
    official_id: str,
    position: str,
    *,
    expected_game_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Propose and immediately confirm one assignment."""
    assignment = propose_assignment(
        game_id, official_id, position, expected_game_version=expected_game_version
    )
    return confirm_assignment(assignment["id"])


def read_assignment(
    assignment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_crew_assignment(assignment_id, headers or SCHEDULER)
    return get_success_data(response, 200)


# ─── Play grades ───────────────────────────────────────

def grade_play(
    game_id: str,
    official_id: str,
    *,
    play_ref: str = "Q1-P07",
    call_category: str = "HOLDING",
    grade_code: str = "CORRECT",
    impact: str = "LOW",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File one DRAFT play grade."""
    response = api_client.create_play_grade(
        f.play_grade_payload(
            game_id,
            official_id,
            play_ref=play_ref,
            call_category=call_category,
            grade_code=grade_code,
            impact=impact,
            **overrides,
        ),
        headers or GRADER,
    )
    return get_success_data(response, 201)


def post_grade(
    grade_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.post_play_grade(grade_id, headers or GRADER)
    return get_success_data(response, 200)


def posted_grade(game_id: str, official_id: str, **kwargs: Any) -> Dict[str, Any]:
    """File a grade and post it, returning the posted row."""
    headers = kwargs.pop("headers", None) or GRADER
    grade = grade_play(game_id, official_id, headers=headers, **kwargs)
    return post_grade(grade["id"], headers)


def read_grade(
    grade_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_play_grade(grade_id, headers or DIRECTOR)
    return get_success_data(response, 200)


# ─── Grade appeals ─────────────────────────────────────

def file_appeal(
    grade_id: str,
    official_id: str,
    basis_note: Optional[str] = None,
) -> Dict[str, Any]:
    """File an appeal as the graded official, whose `X-User-ID` is his own id."""
    response = api_client.create_grade_appeal(
        f.grade_appeal_payload(grade_id, basis_note),
        make_official_headers(official_id),
    )
    return get_success_data(response, 201)


def start_appeal_review(
    appeal_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.start_appeal_review(appeal_id, headers or APPEAL_REVIEWER)
    return get_success_data(response, 200)


def decide_appeal(
    appeal_id: str,
    outcome: str,
    *,
    decision_note: Optional[str] = "decided on review",
    revised_grade_code: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    if revised_grade_code is not None:
        payload["revised_grade_code"] = revised_grade_code
    response = api_client.decide_grade_appeal(
        appeal_id, payload, headers or APPEAL_REVIEWER
    )
    return get_success_data(response, 200)


def withdraw_appeal(
    appeal_id: str, official_id: str
) -> Dict[str, Any]:
    response = api_client.withdraw_grade_appeal(
        appeal_id, make_official_headers(official_id)
    )
    return get_success_data(response, 200)


def read_appeal(
    appeal_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_grade_appeal(appeal_id, headers or DIRECTOR)
    return get_success_data(response, 200)


# ─── Replay stations and reviews ───────────────────────

def register_station(
    *,
    station_code: Optional[str] = None,
    concurrent_capacity: Any = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.replay_station_payload(station_code=station_code, **overrides)
    if concurrent_capacity is not None:
        payload["concurrent_capacity"] = concurrent_capacity
    response = api_client.create_replay_station(payload, headers or DIRECTOR)
    return get_success_data(response, 201)


def read_station(
    station_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_replay_station(station_id, headers or DIRECTOR)
    return get_success_data(response, 200)


def open_review(
    game_id: str,
    station_id: str,
    *,
    play_ref: str = "Q1-P12",
    category: str = "SCORING_PLAY",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_replay_review(
        f.replay_review_payload(
            game_id, station_id, play_ref=play_ref, category=category
        ),
        headers or REPLAY,
    )
    return get_success_data(response, 201)


def decide_review(
    review_id: str,
    decision: str = "CONFIRMED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.decide_replay_review(
        review_id, f.replay_decision_payload(decision), headers or REPLAY
    )
    return get_success_data(response, 200)


def read_review(
    review_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_replay_review(review_id, headers or REPLAY)
    return get_success_data(response, 200)


# ─── Pool reports ──────────────────────────────────────

def draft_pool_report(
    game_id: str,
    play_grade_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api_client.create_pool_report(
        f.pool_report_payload(game_id, play_grade_id, **overrides),
        headers or COMMUNICATIONS,
    )
    return get_success_data(response, 201)


def publish_pool_report(
    report_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.publish_pool_report(report_id, headers or COMMUNICATIONS)
    return get_success_data(response, 200)


def read_pool_report(
    report_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_pool_report(report_id, headers or COMMUNICATIONS)
    return get_success_data(response, 200)


# ─── Discipline actions ────────────────────────────────

def open_discipline(
    official_id: str,
    reason_category: str,
    severity: str,
    *,
    suspension_games: Any = None,
    expected_official_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a discipline action, reading the official's current version first when
    the caller does not pin one."""
    if expected_official_version is None:
        expected_official_version = official_version(official_id)
    payload: Dict[str, Any] = {
        "official_id": official_id,
        "reason_category": reason_category,
        "severity": severity,
        "expected_official_version": expected_official_version,
    }
    if suspension_games is not None:
        payload["suspension_games"] = suspension_games
    response = api_client.create_discipline_action(payload, headers or DIRECTOR)
    return get_success_data(response, 201)


def assign_remediation(
    action_id: str,
    remediation_plan: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.assign_remediation(
        action_id, f.remediation_payload(remediation_plan), headers or DIRECTOR
    )
    return get_success_data(response, 200)


def resolve_discipline(
    action_id: str,
    outcome: str,
    *,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    response = api_client.resolve_discipline_action(
        action_id, payload, headers or DIRECTOR
    )
    return get_success_data(response, 200)


def read_discipline(
    action_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_discipline_action(action_id, headers or DIRECTOR)
    return get_success_data(response, 200)


# ─── Season records ────────────────────────────────────

def season_record_for(
    official_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """The single season record the program keeps for one official."""
    response = api_client.list_season_records(
        headers or DIRECTOR, {"official_id": official_id}
    )
    rows = get_success_data(response, 200)
    assert isinstance(rows, list) and len(rows) >= 1, (
        f"expected a season record for official {official_id}, got {rows!r}"
    )
    return rows[0]


# ─── Advancement applications ──────────────────────────

def create_application(
    official_id: str,
    target_tier: str = "TIER_1",
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Applications are filed by the applying official himself."""
    response = api_client.create_advancement_application(
        f.advancement_application_payload(official_id, target_tier),
        headers or make_official_headers(official_id),
    )
    return get_success_data(response, 201)


def screen_application(
    application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.screen_application(application_id, headers or EVALUATOR)
    return get_success_data(response, 200)


def add_field_evaluation(
    application_id: str,
    *,
    mechanics_score: float = 80.00,
    rules_score: float = 76.00,
    presence_score: float = 70.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_field_evaluation(
        application_id,
        f.field_evaluation_payload(mechanics_score, rules_score, presence_score),
        headers or EVALUATOR,
    )
    return get_success_data(response, 201)


def submit_to_committee(
    application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.submit_application_to_committee(
        application_id, headers or EVALUATOR
    )
    return get_success_data(response, 200)


def return_for_tape(
    application_id: str,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = (
        f.return_for_tape_payload() if note is None else f.return_for_tape_payload(note)
    )
    response = api_client.return_application_for_tape(
        application_id, payload, headers or DIRECTOR
    )
    return get_success_data(response, 200)


def decide_application(
    application_id: str,
    outcome: str,
    *,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    response = api_client.decide_application(
        application_id, payload, headers or DIRECTOR
    )
    return get_success_data(response, 200)


def read_application(
    application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.get_advancement_application(
        application_id, headers or DIRECTOR
    )
    return get_success_data(response, 200)


# ─── Composite chains ──────────────────────────────────
#
# The keys of the returned context dicts are stable, so a test reads
# `ctx["game"]["id"]` rather than re-running the chain by hand.


def _solo_played_game(
    register, position: str, **program_overrides: Any
) -> Dict[str, Any]:
    program = solo_program(**program_overrides)
    official = register(program["id"])
    game = schedule_game(program["id"])
    assignment = propose_assignment(
        game["id"], official["id"], position, expected_game_version=game["version"]
    )
    confirm_assignment(assignment["id"])
    pin_clock(INSTANT_G1_KICKOFF)
    kickoff(game["id"])
    pin_clock(INSTANT_G1_POSTGAME)
    played = mark_played(game["id"])
    return {
        "program": program,
        "official": official,
        "game": played,
        "assignment": assignment,
    }


def played_solo_game(**program_overrides: Any) -> Dict[str, Any]:
    """A one-official program whose single game has been played: Dan Ruiz's
    UMPIRE assignment is complete and the clock stands at the postgame instant."""
    return _solo_played_game(register_umpire, "UMPIRE", **program_overrides)


def played_solo_game_with_referee(**program_overrides: Any) -> Dict[str, Any]:
    """The same chain staffed by Rita Vance as REFEREE, whose position factor of
    1.20 prices errors differently from an umpire's 1.00."""
    return _solo_played_game(register_referee, "REFEREE", **program_overrides)


def three_posted_grades(game_id: str, official_id: str) -> List[Dict[str, Any]]:
    """Two clean plays and one missed call, all POSTED — the three-play set the
    eligibility minimum is measured against."""
    return [
        posted_grade(
            game_id,
            official_id,
            play_ref="Q1-P07",
            call_category="HOLDING",
            grade_code="CORRECT",
            impact="LOW",
        ),
        posted_grade(
            game_id,
            official_id,
            play_ref="Q2-P14",
            call_category="FALSE_START",
            grade_code="CORRECT",
            impact="LOW",
        ),
        posted_grade(
            game_id,
            official_id,
            play_ref="Q3-P22",
            call_category="HOLDING",
            grade_code="MISSED_CALL",
            impact="LOW",
        ),
    ]


def played_game_with_three_posted_grades(**program_overrides: Any) -> Dict[str, Any]:
    ctx = played_solo_game(**program_overrides)
    ctx["grades"] = three_posted_grades(ctx["game"]["id"], ctx["official"]["id"])
    return ctx


def finalized_game_with_final_grades(**program_overrides: Any) -> Dict[str, Any]:
    """The played game above, finalized, so all three grades are FINAL."""
    ctx = played_game_with_three_posted_grades(**program_overrides)
    ctx["game"] = finalize_game(ctx["game"]["id"])
    return ctx


def posted_grade_for_appeal(**program_overrides: Any) -> Dict[str, Any]:
    """A played game carrying exactly one POSTED missed call on Dan Ruiz, the
    grade an appeal is filed against."""
    ctx = played_solo_game(**program_overrides)
    ctx["grade"] = posted_grade(
        ctx["game"]["id"],
        ctx["official"]["id"],
        play_ref="Q3-P22",
        call_category="HOLDING",
        grade_code="MISSED_CALL",
        impact="LOW",
    )
    return ctx


def appeal_under_review(**program_overrides: Any) -> Dict[str, Any]:
    """That posted grade appealed by its own official and taken under review by a
    second supervisor."""
    ctx = posted_grade_for_appeal(**program_overrides)
    appeal = file_appeal(ctx["grade"]["id"], ctx["official"]["id"])
    ctx["appeal"] = start_appeal_review(appeal["id"])
    return ctx


def crew_game(*, confirm_umpire: bool = True, **program_overrides: Any) -> Dict[str, Any]:
    """A two-official program with a SCHEDULED game holding Rita's REFEREE
    assignment and Dan's UMPIRE assignment. Each proposal bumps the game's
    version, so the second one pins the version the first left behind."""
    program = crew_program(**program_overrides)
    referee = register_referee(program["id"])
    umpire = register_umpire(program["id"])
    game = schedule_game(program["id"])
    referee_assignment = propose_assignment(
        game["id"], referee["id"], "REFEREE", expected_game_version=game["version"]
    )
    umpire_assignment = propose_assignment(
        game["id"], umpire["id"], "UMPIRE", expected_game_version=game_version(game["id"])
    )
    confirm_assignment(referee_assignment["id"])
    if confirm_umpire:
        confirm_assignment(umpire_assignment["id"])
    return {
        "program": program,
        "referee": referee,
        "umpire": umpire,
        "game": game,
        "referee_assignment": referee_assignment,
        "umpire_assignment": umpire_assignment,
    }


def in_progress_game_with_station(
    *,
    station_code: Optional[str] = None,
    concurrent_capacity: Any = None,
    **program_overrides: Any,
) -> Dict[str, Any]:
    """A one-official program whose game is IN_PROGRESS, with one ONLINE replay
    station registered and the clock left at kickoff."""
    program = solo_program(**program_overrides)
    official = register_umpire(program["id"])
    game = schedule_game(program["id"])
    assignment = propose_assignment(
        game["id"], official["id"], "UMPIRE", expected_game_version=game["version"]
    )
    confirm_assignment(assignment["id"])
    pin_clock(INSTANT_G1_KICKOFF)
    live_game = kickoff(game["id"])
    station = register_station(
        station_code=station_code, concurrent_capacity=concurrent_capacity
    )
    return {
        "program": program,
        "official": official,
        "game": live_game,
        "assignment": assignment,
        "station": station,
    }


def application_at_committee(**program_overrides: Any) -> Dict[str, Any]:
    """Rita Vance's TIER_1 application, screened, carrying two field evaluations
    that composite to 76.10 and 81.60, and submitted to the committee."""
    program_overrides.setdefault("crew_size_required", 1)
    program = create_open_program(**program_overrides)
    official = register_referee(program["id"])
    application = create_application(official["id"], "TIER_1")
    screen_application(application["id"])
    first = add_field_evaluation(
        application["id"],
        mechanics_score=80.00,
        rules_score=76.00,
        presence_score=70.00,
        headers=EVALUATOR,
    )
    second = add_field_evaluation(
        application["id"],
        mechanics_score=84.00,
        rules_score=80.00,
        presence_score=80.00,
        headers=EVALUATOR_2,
    )
    submitted = submit_to_committee(application["id"])
    return {
        "program": program,
        "official": official,
        "application": submitted,
        "evaluations": [first, second],
    }

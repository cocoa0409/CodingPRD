"""Season programs -- the departmental write gate (PRD 2.5, 3.1, 3.9)."""

from decimal import Decimal

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, order_rows, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_DIRECTOR, endpoint
from response import object_response
from services import calc, derive

bp = Blueprint("season_programs", __name__)

REVIEWABLE_CHOICES = ["SCORING_PLAY", "TURNOVER", "PLAYER_SAFETY", "GAME_ADMIN"]
DEFAULT_REVIEWABLE = ["SCORING_PLAY", "TURNOVER", "PLAYER_SAFETY"]


@bp.route("/season-programs", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def create_season_program():
    """PRD 3.1: every threshold is an optional input with a league-standard
    default; `season_year` must be an integer between 1900 and 2999 inclusive
    and unique across all season programs."""
    data = v.body()
    season_year = v.req_int(data, "season_year", minimum=1900, maximum=2999)
    for existing in db.season_programs.values():
        if existing["season_year"] == season_year:
            fail(errors.ERR_INVALID_REQUEST,
                 "A season program already governs year %d." % season_year)

    row = base_row()
    row.update({
        "season_year": season_year,
        "status": "CONFIGURING",
        "eligible_official_count": 0,
        # accuracy eligibility
        "accuracy_eligibility_threshold": v.opt_score(
            data, "accuracy_eligibility_threshold", Decimal("95.00")),
        "min_graded_plays_for_eligibility": v.opt_int(
            data, "min_graded_plays_for_eligibility", minimum=0, default=3),
        # appeals
        "appeal_credits_per_official": v.opt_int(
            data, "appeal_credits_per_official", minimum=0, default=3),
        "appeal_window_hours": v.opt_int(
            data, "appeal_window_hours", minimum=1, default=72),
        # replay centre
        "replay_decision_limit_seconds": v.opt_int(
            data, "replay_decision_limit_seconds", minimum=1, default=120),
        "reviewable_categories": v.opt_string_list(
            data, "reviewable_categories", REVIEWABLE_CHOICES,
            list(DEFAULT_REVIEWABLE)),
        # crewing
        "max_team_exposures_per_season": v.opt_int(
            data, "max_team_exposures_per_season", minimum=1, default=2),
        "min_rest_hours_between_games": v.opt_int(
            data, "min_rest_hours_between_games", minimum=0, default=96),
        "travel_lead_hours": v.opt_int(
            data, "travel_lead_hours", minimum=0, default=24),
        "crew_size_required": v.opt_int(
            data, "crew_size_required", minimum=1, default=2),
        # development
        "max_application_returns": v.opt_int(
            data, "max_application_returns", minimum=0, default=2),
        "physical_test_min_score": v.opt_score(
            data, "physical_test_min_score", Decimal("70.00")),
        "exam_min_score": v.opt_score(data, "exam_min_score", Decimal("80.00")),
        "clinic_attendance_required": v.opt_int(
            data, "clinic_attendance_required", minimum=0, default=1),
    })
    db.season_programs[row["id"]] = row
    return object_response(row, 201)


@bp.route("/season-programs/<program_id>/open", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def open_season_program(program_id):
    """"Opening a program is legal only while it is `CONFIGURING`, and it moves
    `CONFIGURING -> OPEN`, bumping the program's `version`.\""""
    program = derive.get_program(program_id)
    if program["status"] != "CONFIGURING":
        fail(errors.ERR_SEASON_NOT_OPEN,
             "A season program may only be opened from CONFIGURING.")
    program["status"] = "OPEN"
    touch(program)
    return object_response(program)


@bp.route("/season-programs/<program_id>/lock-postseason", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def lock_postseason(program_id):
    """PRD 3.9: legal only from `OPEN`, refused with ERR_GAMES_IN_PROGRESS while
    any game of the program is still `IN_PROGRESS`; then walks that program's
    season records in `created_at` ascending order."""
    program = derive.get_program(program_id)
    if program["status"] != "OPEN":
        fail(errors.ERR_SEASON_NOT_OPEN,
             "The postseason may only be locked on an OPEN season program.")
    for game in derive.rows_of(db.games, season_program_id=program_id):
        if game["status"] == "IN_PROGRESS":
            fail(errors.ERR_GAMES_IN_PROGRESS,
                 "Game '%s' is still IN_PROGRESS." % game["id"])

    records = derive.rows_of(db.season_records, season_program_id=program_id)
    for record in records:
        official = db.officials.get(record["official_id"])
        if official is None:
            continue
        # Steps one and two: the FINAL accuracy variant, then the two flags.
        derive.recompute_season_record(official, "FINAL", bump=False)
        # Step three: availability, retention score and recommendation.
        record["availability_component"] = derive.availability_for(official["id"])
        deficiency = derive.training_deficiency_count(official, program)
        record["retention_score"] = calc.retention_score(
            record["accuracy_index"], record["availability_component"], deficiency)
        record["retention_recommendation"] = calc.retention_recommendation(
            record["retention_score"])
        touch(record)
        # Step four: a RELEASE recommendation releases the official.
        if record["retention_recommendation"] == "RELEASE":
            if official["status"] in ("ACTIVE", "PROBATION", "SUSPENDED"):
                official["status"] = "RELEASED"
                derive.void_assignments(official, game_statuses=None)
                touch(official)

    program["eligible_official_count"] = len(
        [r for r in records if r["postseason_eligible"]])
    program["status"] = "POSTSEASON_LOCKED"
    touch(program)
    return object_response(program)


@bp.route("/season-programs/<program_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_season_program(program_id):
    return object_response(derive.get_program(program_id))

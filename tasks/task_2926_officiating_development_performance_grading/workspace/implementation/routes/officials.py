"""Officials, their season records and the training log (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, touch
from errors import fail
from middleware import (ANY_ROLE, ROLE_DIRECTOR, ROLE_TRAINING_COORDINATOR,
                        endpoint)
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("officials", __name__)


def _open_season_record(official):
    """PRD 3.2: "Registration also opens that official's season record in the
    same breath ... That record is not returned by the registration response.\""""
    row = base_row()
    row.update({
        "official_id": official["id"],
        "season_program_id": official["season_program_id"],
        "graded_play_count": 0,
        "weighted_error_points": Decimal("0.00"),
        "accuracy_index": Decimal("100.00"),
        "accuracy_variant": "PROVISIONAL",
        "accuracy_eligible": False,
        "postseason_eligible": False,
        "availability_component": Decimal("0.00"),
        "retention_score": Decimal("0.00"),
        "retention_recommendation": "DEVELOP",
    })
    db.season_records[row["id"]] = row
    return row


@bp.route("/officials", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def register_official():
    data = v.body()
    program_id = v.req_str(data, "season_program_id")
    full_name = v.req_str(data, "full_name", 1, 120)
    position = v.req_enum(data, "position", calc.POSITIONS)
    seasons_experience = v.req_int(data, "seasons_experience", minimum=0)
    home_market_code = v.req_team_code(data, "home_market_code")
    tier = v.opt_enum(data, "tier", calc.TIERS, "TIER_3")
    affiliated_team_code = v.opt_team_code(data, "affiliated_team_code", None)

    program = derive.get_program(program_id)
    derive.require_program_open(program)

    row = base_row()
    row.update({
        "season_program_id": program_id,
        "full_name": full_name,
        "position": position,
        "seasons_experience": seasons_experience,
        "home_market_code": home_market_code,
        "tier": tier,
        "affiliated_team_code": affiliated_team_code,
        "status": "CANDIDATE",
        "preseason_cleared": False,
        "open_assignment_count": 0,
        "appeal_credits_remaining": program["appeal_credits_per_official"],
    })
    db.officials[row["id"]] = row
    _open_season_record(row)
    return object_response(row, 201)


@bp.route("/officials/<official_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_official(official_id):
    return object_response(derive.get_official(official_id))


@bp.route("/officials", methods=["GET"])
@endpoint(ANY_ROLE)
def list_officials():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.officials)
    for name in ("season_program_id", "status", "position", "tier",
                 "affiliated_team_code"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))


@bp.route("/officials/<official_id>/training-records", methods=["POST"])
@endpoint([ROLE_TRAINING_COORDINATOR])
def file_training_record(official_id):
    """PRD 3.2: an immutable training record; a `RULES_CLINIC` carries no score
    and always passes, a `PHYSICAL_TEST` passes at or above
    `physical_test_min_score`, a `RULES_EXAM` at or above `exam_min_score`."""
    data = v.body()
    record_type = v.req_enum(data, "record_type", calc.RECORD_TYPES)
    session_code = v.req_str(data, "session_code", 1, 40)
    if record_type == "RULES_CLINIC":
        if v.present(data, "score"):
            fail(errors.ERR_INVALID_REQUEST,
                 "A RULES_CLINIC record may not carry a score.")
        score = None
    else:
        score = v.req_score(data, "score")

    official = derive.get_official(official_id)
    program = derive.program_of_official(official)
    derive.require_program_open(program)

    if record_type == "RULES_CLINIC":
        passed = True
    elif record_type == "PHYSICAL_TEST":
        passed = score >= program["physical_test_min_score"]
    else:
        passed = score >= program["exam_min_score"]

    row = base_row(with_version=False)
    row.update({
        "official_id": official["id"],
        "record_type": record_type,
        "session_code": session_code,
        "score": score,
        "passed": passed,
    })
    db.training_records[row["id"]] = row

    # "Storing a passed rules exam for an official whose status is CANDIDATE
    # transitions that official CANDIDATE -> ACTIVE and bumps the official's
    # version ... Every filed training record re-derives preseason_cleared."
    before_status = official["status"]
    before_cleared = official["preseason_cleared"]
    if record_type == "RULES_EXAM" and passed and official["status"] == "CANDIDATE":
        official["status"] = "ACTIVE"
    official["preseason_cleared"] = derive.derive_preseason_cleared(official)
    if (official["status"] != before_status
            or official["preseason_cleared"] != before_cleared):
        touch(official)
        derive.refresh_postseason_eligible(official)
    return object_response(row, 201)


@bp.route("/officials/<official_id>/training-records", methods=["GET"])
@endpoint(ANY_ROLE)
def list_training_records(official_id):
    """PRD 2.11: the path is validated strictly left to right, so a request for
    the records of a non-existent official reports ERR_OFFICIAL_NOT_FOUND."""
    limit, offset = v.pagination()
    official = derive.get_official(official_id)
    rows = derive.training_records_of(official["id"])
    record_type = v.query_filter("record_type")
    if record_type is not None:
        rows = [r for r in rows if r["record_type"] == record_type]
    passed = v.query_bool("passed")
    if passed is not None:
        rows = [r for r in rows if r["passed"] is passed]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))


@bp.route("/season-records/<record_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_season_record(record_id):
    return object_response(derive.get_season_record(record_id))


@bp.route("/season-records", methods=["GET"])
@endpoint(ANY_ROLE)
def list_season_records():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.season_records)
    for name in ("official_id", "season_program_id", "accuracy_variant",
                 "retention_recommendation"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    for name in ("accuracy_eligible", "postseason_eligible"):
        wanted = v.query_bool(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) is wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))

"""Divisions (PRD 3.4): immutable rule configuration, no version and no updated_at."""

from flask import Blueprint

import auth
import db
import validation
from errors import fail
from routes import common

bp = Blueprint("divisions", __name__)


@bp.post("/ocr/divisions")
def create_division():
    auth.require(auth.RACE_DIRECTOR)
    payload = validation.body()
    name = validation.field_str(payload, "name", 1, 80)
    division_type = validation.field_enum(payload, "division_type", validation.DIVISION_TYPES)
    bypass_policy = validation.field_enum(payload, "bypass_policy", validation.BYPASS_POLICIES)
    scoring_mode = validation.field_enum(payload, "scoring_mode", validation.SCORING_MODES)
    min_age = validation.field_int(payload, "min_age", minimum=0, maximum=99)
    team_size_min = validation.field_int(payload, "team_size_min", minimum=1)
    team_size_max = validation.field_int(payload, "team_size_max", minimum=1)
    if team_size_max < team_size_min:
        fail("ERR_INVALID_REQUEST", "Field 'team_size_max' must be at least team_size_min.")

    row = db.insert(
        "divisions",
        {
            "name": name,
            "division_type": division_type,
            "bypass_policy": bypass_policy,
            "scoring_mode": scoring_mode,
            "min_age": min_age,
            "team_size_min": team_size_min,
            "team_size_max": team_size_max,
        },
        versioned=False,
    )
    return common.created(row)


@bp.get("/ocr/divisions")
def list_divisions():
    auth.require(*auth.ALL_ROLES)
    division_type = validation.query_enum("division_type", validation.DIVISION_TYPES)
    rows = db.all_rows("divisions")
    if division_type is not None:
        rows = [r for r in rows if r["division_type"] == division_type]
    return common.listing(rows)


@bp.get("/ocr/divisions/<division_id>")
def read_division(division_id):
    auth.require(*auth.ALL_ROLES)
    division = validation.path_division(division_id)
    return common.ok(division)

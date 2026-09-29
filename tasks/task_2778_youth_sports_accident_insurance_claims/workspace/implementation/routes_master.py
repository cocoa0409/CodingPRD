"""Logical clock, leagues and sport classifications."""

from flask import Blueprint, g

import auth
import constants as C
import db
import guards
import response
import services
import util
import validation as v
from errors import ApiError

bp = Blueprint("master", __name__)


# ------------------------------------------------------------- logical clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require_roles(["ProgramAdministrator"])
    body = v.json_body()
    instant = v.req_datetime(body, "to_iso8601")
    db.set_clock(instant)
    services.recompute_all_plan_coverage_states()
    services.eob_sweep_all()
    return response.respond_empty(200)


# -------------------------------------------------------------------- leagues

@bp.post("/leagues")
def create_league():
    auth.require_roles(["ProgramAdministrator"])
    body = v.json_body()
    name = v.req_str(body, "name")
    league_code = v.req_league_code(body, "league_code")
    state_code = v.req_state_code(body, "state_code")
    governing_body_code = v.req_str(body, "governing_body_code")
    contact_email = v.req_str(body, "contact_email")
    for existing in db.all_rows("leagues"):
        if existing["league_code"] == league_code:
            raise ApiError("ERR_DUPLICATE_LEAGUE_CODE")
    row = db.new_row("leagues", {
        "name": name,
        "league_code": league_code,
        "state_code": state_code,
        "governing_body_code": governing_body_code,
        "contact_email": contact_email,
        "sanctioning_status": "SANCTIONED",
        "in_force_policy_count": 0,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/leagues/<league_id>")
def get_league(league_id):
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator"])
    row = guards.resolve("league", league_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/leagues")
def list_leagues():
    auth.require_roles(["ProgramAdministrator"])
    limit, offset = v.pagination()
    state_code = v.query_state_code("state_code")
    sanctioning_status = v.query_enum("sanctioning_status", C.LEAGUE_SANCTIONING_STATUSES)
    rows = db.all_rows("leagues")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if sanctioning_status is not None:
        rows = [r for r in rows if r["sanctioning_status"] == sanctioning_status]
    return response.respond_list(rows, limit, offset)


@bp.post("/leagues/<league_id>/sanctioning-status")
def set_sanctioning_status(league_id):
    auth.require_roles(["ProgramAdministrator"])
    league = guards.resolve("league", league_id)
    body = v.json_body()
    target = v.req_enum(body, "sanctioning_status", C.LEAGUE_SANCTIONING_STATUSES)
    v.req_str(body, "reason")
    if (league["sanctioning_status"], target) not in C.LEGAL_SANCTIONING_EDGES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Sanctioning status cannot move from %s to %s."
            % (league["sanctioning_status"], target),
        )
    services.touch(league, sanctioning_status=target)
    for policy in db.policies_of_league(league["id"]):
        services.recompute_policy(policy)
    return response.respond_obj(league)


# ------------------------------------------------------- sport classifications

@bp.post("/sport-classifications")
def create_sport_classification():
    auth.require_roles(["ProgramAdministrator"])
    body = v.json_body()
    sport_code = v.req_str(body, "sport_code")
    sport_name = v.req_str(body, "sport_name")
    hazard_class = v.req_enum(body, "hazard_class", C.HAZARD_CLASSES)
    base_rate = v.req_int(body, "base_rate_per_participant_cents", minimum=1)
    deductible = v.req_int(body, "deductible_cents", minimum=0)
    per_injury_limit = v.req_int(body, "per_injury_limit_cents", minimum=1)
    cat_attachment = v.req_int(body, "cat_attachment_point_cents", minimum=0)
    aggregate_limit = v.req_int(body, "aggregate_limit_cents", minimum=0)
    cat_lifetime_max = v.req_int(body, "cat_lifetime_max_cents", minimum=0)
    minimum_participants = v.req_int(body, "minimum_participants", minimum=1)
    travel_buffer = v.req_int(body, "travel_buffer_minutes", minimum=0)
    caps = v.req_cap_map(body, "service_category_caps", C.SERVICE_CATEGORIES)
    if cat_attachment < per_injury_limit:
        v.bad("Field 'cat_attachment_point_cents' must be >= per_injury_limit_cents.")
    if aggregate_limit < per_injury_limit:
        v.bad("Field 'aggregate_limit_cents' must be >= per_injury_limit_cents.")
    for existing in db.all_rows("sport_classifications"):
        if existing["sport_code"] == sport_code:
            raise ApiError("ERR_DUPLICATE_SPORT_CODE")
    row = db.new_row("sport_classifications", {
        "sport_code": sport_code,
        "sport_name": sport_name,
        "hazard_class": hazard_class,
        "hazard_load_bps": C.HAZARD_LOAD_BPS[hazard_class],
        "base_rate_per_participant_cents": base_rate,
        "deductible_cents": deductible,
        "per_injury_limit_cents": per_injury_limit,
        "cat_attachment_point_cents": cat_attachment,
        "aggregate_limit_cents": aggregate_limit,
        "cat_lifetime_max_cents": cat_lifetime_max,
        "minimum_participants": minimum_participants,
        "travel_buffer_minutes": travel_buffer,
        "service_category_caps": caps,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/sport-classifications/<sport_classification_id>")
def get_sport_classification(sport_classification_id):
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    row = guards.resolve("sport_classification", sport_classification_id)
    return response.respond_obj(row)


@bp.get("/sport-classifications")
def list_sport_classifications():
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator"])
    limit, offset = v.pagination()
    hazard_class = v.query_enum("hazard_class", C.HAZARD_CLASSES)
    rows = db.all_rows("sport_classifications")
    if hazard_class is not None:
        rows = [r for r in rows if r["hazard_class"] == hazard_class]
    return response.respond_list(rows, limit, offset)

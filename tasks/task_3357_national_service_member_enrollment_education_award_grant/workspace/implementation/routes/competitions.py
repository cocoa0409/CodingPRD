from flask import Blueprint

import auth
import clock
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("competitions", __name__)

READ_ROLES = [
    "CNCSProgramOfficer",
    "ComplianceOfficer",
    "GranteeStaff",
    "TrustAdministrator",
    "Member",
]


@bp.route("/competitions", methods=["POST"])
def create_competition():
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    body = util.body_json()
    title = body.get("title")
    fiscal_year = body.get("fiscal_year")
    open_dt = clock.parse_datetime(body.get("application_open_at"))
    close_dt = clock.parse_datetime(body.get("application_close_at"))
    if not util.is_str(title) or not title.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "title is required")
    if not util.is_int(fiscal_year):
        raise ApiError("ERR_INVALID_REQUEST", 400, "fiscal_year must be an integer")
    if open_dt is None or close_dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "application window timestamps are invalid"
        )
    if not close_dt > open_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "application_close_at must be strictly after application_open_at",
        )
    competition = db.new_entity(
        {
            "id": util.new_id(),
            "title": title,
            "fiscal_year": fiscal_year,
            "application_open_at": clock.iso(open_dt),
            "application_close_at": clock.iso(close_dt),
            "status": "OPEN",
        }
    )
    db.store.competitions[competition["id"]] = competition
    return util.ok(serialize(competition), 201)


@bp.route("/competitions/<competitionId>", methods=["GET"])
def get_competition(competitionId):
    _uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    competition = db.store.competitions.get(competitionId)
    if competition is None:
        raise ApiError("ERR_COMPETITION_NOT_FOUND", 404, "Competition not found")
    return util.ok(serialize(competition), 200)


@bp.route("/competitions/<competitionId>/close", methods=["POST"])
def close_competition(competitionId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    competition = db.store.competitions.get(competitionId)
    if competition is None:
        raise ApiError("ERR_COMPETITION_NOT_FOUND", 404, "Competition not found")
    if competition["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Competition is not OPEN")
    close_dt = clock.parse_datetime(competition["application_close_at"])
    if not clock.now() > close_dt:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "The application window has not ended yet"
        )
    competition["status"] = "CLOSED"
    domain.touch(competition)
    # If every application is already terminal, the bubble-up fires at close.
    domain.competition_bubble(competition)
    return util.ok(serialize(competition), 200)

"""County registration and reads (PRD §3.1). Counties mutate never after
creation; their computed fields derive on read."""
from flask import Blueprint

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import get_event, get_county, require_posture, versioned_record
from serializers import county_json
from store import db
from util import is_int, is_number, nonblank

bp = Blueprint("counties", __name__)

READ_ROLES = (
    "ElectionOpsAdmin", "CoveragePlanner", "StringerCoordinator",
    "TabulationClerk", "DecisionAnalyst", "DecisionDeskChief", "RecountOfficer",
)


@bp.post("/election-events/<rid>/counties")
def create_county(rid):
    require_roles("ElectionOpsAdmin")
    event = get_event(rid)
    require_posture(event, "SETUP")
    data = body()
    for f in ("county_fips", "county_name", "state_code",
              "expected_precincts", "expected_vote_total"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["county_fips"]):
        raise_err("ERR_INVALID_REQUEST", "county_fips must be a non-blank string")
    if not nonblank(data["county_name"]):
        raise_err("ERR_INVALID_REQUEST", "county_name must be a non-blank string")
    if not nonblank(data["state_code"]):
        raise_err("ERR_INVALID_REQUEST", "state_code must be a non-blank string")
    if not is_int(data["expected_precincts"]) or data["expected_precincts"] < 1:
        raise_err("ERR_INVALID_REQUEST", "expected_precincts must be an integer >= 1")
    if not is_int(data["expected_vote_total"]) or data["expected_vote_total"] < 1:
        raise_err("ERR_INVALID_REQUEST", "expected_vote_total must be an integer >= 1")
    survey = data.get("survey_turnout_estimate")
    if survey is not None and not is_int(survey):
        raise_err("ERR_INVALID_REQUEST", "survey_turnout_estimate must be an integer or null")
    hist = data.get("historical_dem_share")
    if hist is not None and (not is_number(hist) or hist < 0 or hist > 1):
        raise_err("ERR_INVALID_REQUEST", "historical_dem_share must be a number in [0,1] or null")

    # Uniqueness: county_fips per event (priority 17).
    for c in db["counties"].values():
        if c["event_id"] == event["id"] and c["county_fips"] == data["county_fips"]:
            raise_err("ERR_DUPLICATE_COUNTY", "county_fips already registered in this event")

    rec = versioned_record()
    rec.update({
        "event_id": event["id"],
        "county_fips": data["county_fips"],
        "county_name": data["county_name"],
        "state_code": data["state_code"],
        "expected_precincts": data["expected_precincts"],
        "expected_vote_total": data["expected_vote_total"],
        "survey_turnout_estimate": survey,
        "historical_dem_share": (float(hist) if hist is not None else None),
    })
    db["counties"][rec["id"]] = rec
    return ok_object(county_json(rec), 201)


@bp.get("/election-events/<rid>/counties")
def list_counties(rid):
    require_roles(*READ_ROLES)
    event = get_event(rid)
    rows = [c for c in db["counties"].values() if c["event_id"] == event["id"]]
    return paginate(rows, county_json)


@bp.get("/counties/<rid>")
def read_county(rid):
    require_roles(*READ_ROLES)
    return ok_object(county_json(get_county(rid)))

"""Contests, county links, and candidates (PRD §3.1)."""
from flask import Blueprint

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_event, get_contest, get_county, require_posture,
    versioned_record, base_record, touch,
)
from serializers import contest_json, link_json, candidate_json
from store import db
from util import is_int, nonblank

bp = Blueprint("contests", __name__)

READ_ROLES = (
    "ElectionOpsAdmin", "CoveragePlanner", "StringerCoordinator",
    "TabulationClerk", "DecisionAnalyst", "DecisionDeskChief", "RecountOfficer",
)
CONTEST_TYPES = (
    "FEDERAL_EXEC", "FEDERAL_SENATE", "FEDERAL_HOUSE", "STATE", "BALLOT_MEASURE",
)
TABULATION_STATUSES = ("AWAITING", "REPORTING", "COMPLETE")
CALL_STATUSES = ("UNCALLED", "CALLED")
PARTIES = ("DEM", "REP", "IND", "LIB", "GRN", "OTHER")


@bp.post("/election-events/<rid>/contests")
def create_contest(rid):
    require_roles("ElectionOpsAdmin")
    event = get_event(rid)
    require_posture(event, "SETUP")
    data = body()
    for f in ("office_name", "state_code", "contest_type"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["office_name"]):
        raise_err("ERR_INVALID_REQUEST", "office_name must be a non-blank string")
    if not nonblank(data["state_code"]):
        raise_err("ERR_INVALID_REQUEST", "state_code must be a non-blank string")
    if data["contest_type"] not in CONTEST_TYPES:
        raise_err("ERR_INVALID_REQUEST", "contest_type out of range")
    seats = data.get("seats", 1)
    if seats is None:
        seats = 1
    if not is_int(seats) or seats < 1:
        raise_err("ERR_INVALID_REQUEST", "seats must be an integer >= 1")

    rec = versioned_record()
    rec.update({
        "event_id": event["id"],
        "office_name": data["office_name"],
        "state_code": data["state_code"],
        "contest_type": data["contest_type"],
        "seats": seats,
        "tabulation_status": "AWAITING",
        "call_status": "UNCALLED",
        "called_candidate_id": None,
        "reported_precincts": 0,
        "total_votes": 0,
        "margin_pct": 0.0,
        "outstanding_estimate": 0,
    })
    db["contests"][rec["id"]] = rec
    return ok_object(contest_json(rec), 201)


@bp.get("/election-events/<rid>/contests")
def list_contests(rid):
    require_roles(*READ_ROLES)
    event = get_event(rid)
    rows = [c for c in db["contests"].values() if c["event_id"] == event["id"]]
    from flask import request
    ts = request.args.get("tabulation_status")
    if ts is not None:
        if ts not in TABULATION_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "tabulation_status filter out of range")
        rows = [c for c in rows if c["tabulation_status"] == ts]
    cs = request.args.get("call_status")
    if cs is not None:
        if cs not in CALL_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "call_status filter out of range")
        rows = [c for c in rows if c["call_status"] == cs]
    return paginate(rows, contest_json)


@bp.get("/contests/<rid>")
def read_contest(rid):
    require_roles(*READ_ROLES)
    return ok_object(contest_json(get_contest(rid)))


@bp.patch("/contests/<rid>")
def patch_contest(rid):
    require_roles("ElectionOpsAdmin")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "SETUP")
    data = body()
    if "office_name" in data and data["office_name"] is not None:
        if not nonblank(data["office_name"]):
            raise_err("ERR_INVALID_REQUEST", "office_name must be a non-blank string")
        contest["office_name"] = data["office_name"]
    if "seats" in data and data["seats"] is not None:
        if not is_int(data["seats"]) or data["seats"] < 1:
            raise_err("ERR_INVALID_REQUEST", "seats must be an integer >= 1")
        contest["seats"] = data["seats"]
    touch(contest)
    return ok_object(contest_json(contest))


@bp.post("/contests/<rid>/county-links")
def create_county_link(rid):
    require_roles("ElectionOpsAdmin")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "SETUP")
    data = body()
    county_id = data.get("county_id")
    if county_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: county_id")
    county = db["counties"].get(county_id)
    if county is None:
        raise_err("ERR_COUNTY_NOT_FOUND", "County id does not resolve")
    if county["event_id"] != contest["event_id"]:
        raise_err("ERR_CROSS_EVENT_REFERENCE", "County belongs to another event")
    if county["state_code"] != contest["state_code"]:
        # PRD §3.1: every linked county shares the contest's state_code.
        raise_err(
            "ERR_INVALID_REQUEST",
            "Linked county must share the contest's state_code",
        )
    for l in db["links"].values():
        if l["contest_id"] == contest["id"] and l["county_id"] == county["id"]:
            raise_err("ERR_DUPLICATE_COUNTY_LINK", "County already linked to this contest")
    rec = base_record()
    rec.update({"contest_id": contest["id"], "county_id": county["id"]})
    db["links"][rec["id"]] = rec
    return ok_object(link_json(rec), 201)


@bp.get("/contests/<rid>/county-links")
def list_links_of_contest(rid):
    require_roles(*READ_ROLES)
    contest = get_contest(rid)
    rows = [l for l in db["links"].values() if l["contest_id"] == contest["id"]]
    return paginate(rows, link_json)


@bp.get("/counties/<rid>/county-links")
def list_links_of_county(rid):
    require_roles(*READ_ROLES)
    county = get_county(rid)
    rows = [l for l in db["links"].values() if l["county_id"] == county["id"]]
    return paginate(rows, link_json)


@bp.post("/contests/<rid>/candidates")
def create_candidate(rid):
    require_roles("ElectionOpsAdmin")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "SETUP")
    data = body()
    for f in ("candidate_name", "party"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["candidate_name"]):
        raise_err("ERR_INVALID_REQUEST", "candidate_name must be a non-blank string")
    if data["party"] not in PARTIES:
        raise_err("ERR_INVALID_REQUEST", "party out of range")
    is_incumbent = data.get("is_incumbent", False)
    if is_incumbent is None:
        is_incumbent = False
    if not isinstance(is_incumbent, bool):
        raise_err("ERR_INVALID_REQUEST", "is_incumbent must be a boolean")
    for c in db["candidates"].values():
        if c["contest_id"] == contest["id"] and c["candidate_name"] == data["candidate_name"]:
            raise_err("ERR_DUPLICATE_CANDIDATE", "candidate_name already on this contest")
    rec = base_record()
    rec.update({
        "contest_id": contest["id"],
        "candidate_name": data["candidate_name"],
        "party": data["party"],
        "is_incumbent": is_incumbent,
    })
    db["candidates"][rec["id"]] = rec
    return ok_object(candidate_json(rec), 201)


@bp.get("/contests/<rid>/candidates")
def list_candidates(rid):
    require_roles(*READ_ROLES)
    contest = get_contest(rid)
    rows = [c for c in db["candidates"].values() if c["contest_id"] == contest["id"]]
    return paginate(rows, candidate_json)

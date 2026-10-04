"""Members, employers, ombudsmen (registration/read), affiliation listing,
and the member/employer service-period listings."""
from flask import Blueprint

from auth import require_role, require_ownership
from helpers import (
    body_json, req_str, req_enum, opt_str,
    get_member, get_employer, get_ombudsman,
    ser_member, ser_employer, ser_ombudsman, ser_service_period,
    BRANCHES, COMPONENTS, SECTORS, SIZE_TIERS,
)
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("parties", __name__)


@bp.route("/reemployment/members", methods=["POST"])
def create_member():
    require_role("Anonymous")
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    branch = req_enum(body, "branch", BRANCHES)
    component = req_enum(body, "component", COMPONENTS)
    mid = new_id()
    t = now()
    m = {
        "id": mid, "full_name": full_name, "email": email,
        "branch": branch, "component": component,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.members[mid] = m
    return success(ser_member(m), "object", 201)


@bp.route("/reemployment/members/<mid>", methods=["GET"])
def read_member(mid):
    role, uid = require_role("ServiceMember", "ProgramCoordinator")
    m = get_member(mid)
    if role == "ServiceMember":
        require_ownership(mid == uid)
    return success(ser_member(m))


@bp.route("/reemployment/employers", methods=["POST"])
def create_employer():
    require_role("ProgramCoordinator")
    body = body_json()
    legal_name = req_str(body, "legal_name")
    sector = req_enum(body, "sector", SECTORS)
    size_tier = req_enum(body, "size_tier", SIZE_TIERS)
    eid = new_id()
    t = now()
    e = {
        "id": eid, "legal_name": legal_name, "sector": sector, "size_tier": size_tier,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.employers[eid] = e
    return success(ser_employer(e), "object", 201)


@bp.route("/reemployment/employers/<eid>", methods=["GET"])
def read_employer(eid):
    role, uid = require_role("Employer", "Ombudsman", "ProgramCoordinator")
    e = get_employer(eid)
    if role == "Employer":
        require_ownership(eid == uid)
    return success(ser_employer(e))


@bp.route("/reemployment/ombudsmen", methods=["POST"])
def create_ombudsman():
    require_role("Anonymous")
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    affiliation = opt_str(body, "employer_affiliation_id")
    if affiliation is not None:
        get_employer(affiliation)
    oid = new_id()
    t = now()
    o = {
        "id": oid, "full_name": full_name, "email": email,
        "employer_affiliation_id": affiliation, "status": "TRAINEE",
        "certified_on": None, "certification_expires_on": None,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.ombudsmen[oid] = o
    return success(ser_ombudsman(o), "object", 201)


@bp.route("/reemployment/ombudsmen/<oid>", methods=["GET"])
def read_ombudsman(oid):
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    o = get_ombudsman(oid)
    if role == "Ombudsman":
        require_ownership(oid == uid)
    return success(ser_ombudsman(o))


@bp.route("/reemployment/employers/<eid>/affiliated-ombudsmen", methods=["GET"])
def affiliated_ombudsmen(eid):
    role, uid = require_role("Employer", "Ombudsman", "ProgramCoordinator")
    get_employer(eid)
    if role == "Employer":
        require_ownership(eid == uid)
    items = [o for o in db.ombudsmen.values() if o["employer_affiliation_id"] == eid]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    page, meta = paginate(items)
    return success([ser_ombudsman(o) for o in page], "array", 200, meta)


@bp.route("/reemployment/members/<mid>/service-periods", methods=["GET"])
def member_service_periods(mid):
    role, uid = require_role("ServiceMember", "Ombudsman", "ProgramCoordinator")
    get_member(mid)
    if role == "ServiceMember":
        require_ownership(mid == uid)
    items = [p for p in db.service_periods.values() if p["member_id"] == mid]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return success([ser_service_period(p) for p in page], "array", 200, meta)


@bp.route("/reemployment/employers/<eid>/service-periods", methods=["GET"])
def employer_service_periods(eid):
    role, uid = require_role("Employer", "Ombudsman", "ProgramCoordinator")
    get_employer(eid)
    if role == "Employer":
        require_ownership(eid == uid)
    items = [p for p in db.service_periods.values() if p["employer_id"] == eid]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return success([ser_service_period(p) for p in page], "array", 200, meta)

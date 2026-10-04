from flask import Blueprint, request

import db
import services
from errors import fail
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_int,
    req_enum,
    req_list_str,
    opt_str,
)
from response import success, paginate
from util import serialize

bp = Blueprint("openings", __name__)


def _get_opening(oid):
    opening = db.store.openings.get(oid)
    if opening is None:
        fail("ERR_OPENING_NOT_FOUND", "EmployerOpening %s does not exist" % oid)
    return opening


@bp.route("/employer-openings", methods=["POST"])
@locked
def create_opening():
    uid, role = auth_context()
    data = body()
    employer_id = req_str(data, "employer_id")
    title = req_str(data, "title")
    required_skills = req_list_str(data, "required_skills")
    location_type = req_enum(data, "location_type", {"ON_SITE", "REMOTE"})
    capacity = req_int(data, "capacity", min_value=1)
    region_code = opt_str(data, "region_code")
    if location_type == "ON_SITE" and region_code is None:
        fail("ERR_VALIDATION", "region_code is required when location_type is ON_SITE")
    require_role(role, ["EmployerRep"])
    employer = db.store.employers.get(employer_id)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer %s does not exist" % employer_id)
    if uid != employer_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal employer_id")
    if employer["authorization_status"] != "AUTHORIZED":
        fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not AUTHORIZED")
    ent = db.base_entity()
    ent.update(
        {
            "employer_id": employer_id,
            "title": title,
            "required_skills": required_skills,
            "location_type": location_type,
            "region_code": region_code,
            "capacity": capacity,
            "filled_count": 0,
            "status": "OPEN",
        }
    )
    db.store.openings[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/employer-openings", methods=["GET"])
@locked
def list_openings():
    auth_context()
    items = sorted(db.store.openings.values(), key=lambda e: e["_seq"])
    f_employer = request.args.get("employer_id")
    f_status = request.args.get("status")
    if f_employer is not None:
        items = [o for o in items if o["employer_id"] == f_employer]
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    page, pagination = paginate(items)
    return success([serialize(o) for o in page], pagination=pagination)


@bp.route("/employer-openings/<oid>", methods=["GET"])
@locked
def get_opening(oid):
    auth_context()
    return success(serialize(_get_opening(oid)))


@bp.route("/employer-openings/<oid>/close", methods=["POST"])
@locked
def close_opening(oid):
    uid, role = auth_context()
    body()
    require_role(role, ["EmployerRep"])
    opening = _get_opening(oid)
    if uid != opening["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the opening's employer_id")
    if opening["status"] != "OPEN":
        fail("ERR_OPENING_NOT_OPEN", "Opening is not OPEN")
    opening["status"] = "CLOSED"
    services.cascade_opening_closed(opening)
    services.touch(opening)
    return success(serialize(opening))

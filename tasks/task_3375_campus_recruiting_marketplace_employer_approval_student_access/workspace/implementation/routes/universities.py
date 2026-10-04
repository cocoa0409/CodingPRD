"""University onboarding, lifecycle transitions, and the outcome report."""

from flask import Blueprint

import db
from db import wall_now
from errors import fail
from services import build_outcome_report, university_view
from util import Body, get_context, require_role, success_object

bp = Blueprint("universities", __name__)

UNIVERSITY_STATUSES = ("ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED")

# Legal (from -> to) pairs for the university lifecycle.
UNIVERSITY_TRANSITIONS = {
    ("ONBOARDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "OFFBOARDED"),
    ("SUSPENDED", "OFFBOARDED"),
}


@bp.route("/universities", methods=["POST"])
def create_university():
    _user_id, role = get_context()
    require_role(role, "PlatformAdmin")
    body = Body()
    name = body.str_f("name", required=True)
    primary_domain = body.str_f("primary_domain", required=True)
    cap = body.int_f("employer_daily_message_cap", minv=0)
    body.finalize()
    if cap is None:
        cap = 10
    record = {
        "id": db.new_id(),
        "name": name,
        "primary_domain": primary_domain,
        "status": "ONBOARDING",
        "employer_daily_message_cap": cap,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("universities", record)
    return success_object(university_view(record), 201)


@bp.route("/universities/<university_id>/transition", methods=["POST"])
def transition_university(university_id):
    _user_id, role = get_context()
    require_role(role, "PlatformAdmin")
    university = db.get("universities", university_id)
    if university is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    body = Body()
    to = body.str_f("to", required=True, enum=UNIVERSITY_STATUSES)
    if to is not None and (university["status"], to) not in UNIVERSITY_TRANSITIONS:
        fail("ERR_INVALID_UNIVERSITY_TRANSITION",
             "University transition %s -> %s is not allowed" % (university["status"], to))
    body.finalize()
    university["status"] = to
    db.touch(university)
    return success_object(university_view(university))


@bp.route("/universities/<university_id>/outcome-report", methods=["GET"])
def outcome_report(university_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "PlatformAdmin")
    university = db.get("universities", university_id)
    if university is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    if role == "CareerCenterAdmin" and user_id != university_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may report only on its own university")
    return success_object(build_outcome_report(university))

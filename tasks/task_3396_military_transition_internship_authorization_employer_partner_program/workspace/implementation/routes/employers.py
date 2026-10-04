from datetime import timedelta

from flask import Blueprint, request

import constants
import db
import services
from errors import fail
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_enum,
    opt_str,
)
from response import success, paginate
from util import serialize, parse_iso_date

bp = Blueprint("employers", __name__)


def _get_employer(eid):
    employer = db.store.employers.get(eid)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer %s does not exist" % eid)
    return employer


@bp.route("/employers", methods=["POST"])
@locked
def create_employer():
    uid, role = auth_context()
    data = body()
    legal_name = req_str(data, "legal_name")
    industry_code = req_str(data, "industry_code")
    require_role(role, ["ProgramOffice"])
    ent = db.base_entity()
    ent.update(
        {
            "legal_name": legal_name,
            "industry_code": industry_code,
            "authorization_status": "PENDING_AUTHORIZATION",
            "authorized_at": None,
            "next_review_due_date": None,
            "pending_violations": 0,
            "last_cleared_audit_at": None,
            "last_compliance_score": None,
        }
    )
    db.store.employers[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/employers/<eid>", methods=["GET"])
@locked
def get_employer(eid):
    auth_context()
    return success(serialize(_get_employer(eid)))


@bp.route("/employers/<eid>/authorize", methods=["POST"])
@locked
def authorize_employer(eid):
    uid, role = auth_context()
    body()
    require_role(role, ["ProgramOffice"])
    employer = _get_employer(eid)
    if employer["authorization_status"] != "PENDING_AUTHORIZATION":
        fail("ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION", "Employer is not PENDING_AUTHORIZATION")
    employer["authorization_status"] = "AUTHORIZED"
    employer["authorized_at"] = db.now()
    employer["next_review_due_date"] = db.now() + timedelta(days=constants.REVIEW_INTERVAL_DAYS)
    services.touch(employer)
    return success(serialize(employer))


@bp.route("/employers/<eid>/periodic-review", methods=["POST"])
@locked
def periodic_review(eid):
    uid, role = auth_context()
    data = body()
    outcome = req_enum(data, "outcome", {"PASS", "FAIL"})
    opt_str(data, "notes")  # optional; validated for type, not stored
    require_role(role, ["ProgramOffice"])
    employer = _get_employer(eid)
    status = employer["authorization_status"]
    if outcome == "PASS":
        if status not in ("AUTHORIZED", "SUSPENDED", "AUTHORIZATION_LAPSED"):
            fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not in a review-eligible state")
        employer["authorization_status"] = "AUTHORIZED"
        employer["authorized_at"] = db.now()
        employer["next_review_due_date"] = db.now() + timedelta(
            days=constants.REVIEW_INTERVAL_DAYS
        )
    else:  # FAIL
        if status not in ("AUTHORIZED", "AUTHORIZATION_LAPSED"):
            fail("ERR_EMPLOYER_NOT_AUTHORIZED", "Employer is not in a review-eligible state")
        employer["authorization_status"] = "SUSPENDED"
    services.touch(employer)
    return success(serialize(employer))


@bp.route("/employers/<eid>/compliance-audits", methods=["GET"])
@locked
def list_employer_audits(eid):
    auth_context()
    employer = _get_employer(eid)
    items = sorted(
        [a for a in db.store.audits.values() if a["employer_id"] == employer["id"]],
        key=lambda e: e["_seq"],
    )
    page, pagination = paginate(items)
    return success([serialize(a) for a in page], pagination=pagination)


@bp.route("/employers/<eid>/hiring-rate", methods=["GET"])
@locked
def get_hiring_rate(eid):
    uid, role = auth_context()
    require_role(role, ["ProgramOffice", "EmployerRep", "InstallationAuthority"])
    employer = _get_employer(eid)
    variant = request.args.get("variant", "ROLLING")
    if variant not in ("COHORT", "ROLLING"):
        fail("ERR_VALIDATION", "variant must be COHORT or ROLLING")
    cohort_start = None
    cohort_end = None
    if variant == "COHORT":
        raw_start = request.args.get("cohort_start_date")
        raw_end = request.args.get("cohort_end_date")
        if not raw_start or not raw_end:
            fail("ERR_VALIDATION", "variant=COHORT requires cohort_start_date and cohort_end_date")
        cohort_start = parse_iso_date(raw_start)
        cohort_end = parse_iso_date(raw_end)
        if cohort_start is None or cohort_end is None:
            fail("ERR_VALIDATION", "cohort dates must be ISO 8601 dates")
    return success(services.hiring_rate(employer, variant, cohort_start, cohort_end))

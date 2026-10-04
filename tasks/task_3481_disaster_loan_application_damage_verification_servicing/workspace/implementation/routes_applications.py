"""LoanApplication intake: create, list, read, submit, reconsideration (PRD 3.2)."""

from flask import Blueprint, g, request

import calc
import clock
from auth import check_owner, require_roles
from body import json_body, req_enum, req_int, req_str
from domain import bump, get_or_404, new_common
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows, get, put
from serializers import serialize, serialize_all

bp = Blueprint("applications", __name__)

PURPOSES = {"PHYSICAL_DAMAGE", "ECONOMIC_INJURY"}
READ_ROLES = ("Applicant", "LoanOfficer", "LoanApprover", "ServicingAgent",
              "LossVerifier", "GrantCoordinator")


@bp.post("/disaster-relief/loan-applications")
@require_roles("Applicant")
def create_application():
    data = json_body()
    declaration_id = req_str(data, "declaration_id")
    county_fips = req_str(data, "county_fips")
    loan_purpose = req_enum(data, "loan_purpose", PURPOSES)
    requested = req_int(data, "requested_amount_cents", min_value=1)
    row = new_common()
    row.update({
        "declaration_id": declaration_id,
        "applicant_id": g.user_id,  # always from the caller's identity, never the body
        "county_fips": county_fips,
        "loan_purpose": loan_purpose,
        "requested_amount_cents": requested,
        "status": "DRAFT",
        "reconsideration_count": 0,
        "submitted_at": None,
        "decline_reason": None,
        "loan_id": None,
    })
    put("applications", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loan-applications")
@require_roles(*READ_ROLES)
def list_applications():
    rows = all_rows("applications")
    if g.role == "Applicant":
        rows = [r for r in rows if r["applicant_id"] == g.user_id]
    for field in ("applicant_id", "declaration_id", "loan_id", "status"):
        val = request.args.get(field)
        if val is not None and g.role == "Applicant" and field == "applicant_id":
            continue  # ownership scope already applied above
        if val is not None:
            rows = [r for r in rows if str(r.get(field)) == val]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.get("/disaster-relief/loan-applications/<app_id>")
@require_roles(*READ_ROLES)
def get_application(app_id):
    app = get_or_404("applications", app_id)
    check_owner(app["applicant_id"])
    return success(serialize(app))


@bp.post("/disaster-relief/loan-applications/<app_id>/submit")
@require_roles("Applicant")
def submit_application(app_id):
    app = get_or_404("applications", app_id)
    check_owner(app["applicant_id"])
    declaration = get("declarations", app["declaration_id"])
    if declaration is None:
        raise_err("ERR_NOT_FOUND", "declaration not found")
    if app["status"] != "DRAFT":
        raise_err("ERR_APPLICATION_NOT_DRAFT")
    now = clock.get_current()
    # Deadline checks (inclusive) run before county eligibility.
    if app["loan_purpose"] == "PHYSICAL_DAMAGE":
        if now > declaration["physical_filing_deadline"]:
            raise_err("ERR_PHYSICAL_FILING_CLOSED")
    else:
        if now > declaration["economic_injury_filing_deadline"]:
            raise_err("ERR_EIDL_FILING_CLOSED")
    eligible = any(c["county_fips"] == app["county_fips"]
                   and app["loan_purpose"] in c["eligible_purposes"]
                   for c in declaration["counties"])
    if not eligible:
        raise_err("ERR_COUNTY_NOT_ELIGIBLE")
    app["submitted_at"] = now
    app["status"] = "SUBMITTED"
    bump(app)
    return success(serialize(app))


@bp.post("/disaster-relief/loan-applications/<app_id>/request-reconsideration")
@require_roles("Applicant")
def request_reconsideration(app_id):
    app = get_or_404("applications", app_id)
    check_owner(app["applicant_id"])
    if app["status"] != "DECLINED":
        raise_err("ERR_APPLICATION_NOT_DECLINED")
    if app["reconsideration_count"] >= calc.MAX_RECONSIDERATIONS:
        raise_err("ERR_RECONSIDERATION_LIMIT")
    app["reconsideration_count"] += 1
    app["decline_reason"] = None
    app["status"] = "DECISION_PENDING"
    bump(app)
    return success(serialize(app))

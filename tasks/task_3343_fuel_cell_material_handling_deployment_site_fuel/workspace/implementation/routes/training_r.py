"""Training record endpoints (PRD section 3.8)."""

from flask import Blueprint, request

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_DATE_RANGE

bp = Blueprint("training", __name__)

READ_ROLES = ("SiteManager", "SafetyOfficer")
COURSE_CODES = ("H2_BASIC", "H2_OPERATOR", "H2_EMERGENCY")


@bp.post("/api/sites/<site_id>/training-records")
@require_roles("SiteManager")
def create_record(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    trainee = v.str_value(v.req(data, "trainee_employee_id"),
                          "trainee_employee_id", 1, 60)
    course = v.enum_value(v.req(data, "course_code"), "course_code",
                          COURSE_CODES)
    completed = v.date_value(v.req(data, "completed_at"), "completed_at")
    expires = v.date_value(v.req(data, "expires_at"), "expires_at")
    if v.parse_date(expires) <= v.parse_date(completed):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "expires_at must be after completed_at")
    r = helpers.create_rec(db.training_records, {
        "site_id": site_id,
        "trainee_employee_id": trainee,
        "course_code": course,
        "completed_at": completed,
        "expires_at": expires,
        "status": "VALID",
    })
    return envelope.ok(r, 201)


@bp.get("/api/sites/<site_id>/training-records")
@require_roles(*READ_ROLES)
def list_records(site_id):
    helpers.get_site(site_id)
    items = [r for r in db.training_records.values()
             if r["site_id"] == site_id]
    trainee = request.args.get("trainee_employee_id")
    if trainee is not None:
        items = [r for r in items if r["trainee_employee_id"] == trainee]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/training-records/<rid>")
@require_roles(*READ_ROLES)
def get_record(rid):
    return envelope.ok(helpers.get_or_404(db.training_records, rid,
                                          "training record"), 200)

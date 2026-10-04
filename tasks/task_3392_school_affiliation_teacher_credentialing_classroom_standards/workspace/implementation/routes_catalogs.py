"""Standards catalog endpoints (PRD 2.6, 3.1)."""

from flask import Blueprint

from envelope import ok
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_CATALOG_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CATALOG_EFFECTIVE_ORDER,
)
from serializers import serialize_catalog
from store import db, new_id, stamp_new, touch, active_catalog, parse_date
from validation import (
    authenticate,
    require_role,
    payload,
    req_str,
    req_int,
    req_number,
    req_dict,
)

bp = Blueprint("catalogs", __name__)

READ_ROLES = {
    "SocietyAdmin",
    "AccreditationReviewer",
    "SchoolAdmin",
    "ProgramDirector",
    "Registrar",
    "Consultant",
}


def _get_catalog(catalog_id):
    cat = db.catalogs.get(catalog_id)
    if cat is None:
        raise ApiError(ERR_CATALOG_NOT_FOUND[0], ERR_CATALOG_NOT_FOUND[1],
                       "No standards catalog with id %r." % catalog_id)
    return cat


@bp.route("/standards-catalogs", methods=["POST"])
def create_catalog():
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    body = payload()
    version_label = req_str(body, "version_label")
    effective_from = req_str(body, "effective_from")
    if parse_date(effective_from) is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'effective_from' must be an ISO date (YYYY-MM-DD).")
    cat = {
        "id": new_id(),
        "version_label": version_label,
        "status": "DRAFT",
        "effective_from": effective_from,
        "min_uninterrupted_work_minutes_by_level": req_dict(body, "min_uninterrupted_work_minutes_by_level"),
        "max_students_per_adult_by_level": req_dict(body, "max_students_per_adult_by_level"),
        "materials_pass_threshold": req_number(body, "materials_pass_threshold"),
        "min_multi_age_span_years_by_level": req_dict(body, "min_multi_age_span_years_by_level"),
        "practicum_min_hours_by_level": req_dict(body, "practicum_min_hours_by_level"),
        "ce_hours_required": req_number(body, "ce_hours_required"),
        "credential_validity_months": req_int(body, "credential_validity_months"),
        "renewal_window_months": req_int(body, "renewal_window_months"),
        "renewal_grace_months": req_int(body, "renewal_grace_months"),
        "min_membership_months_before_accreditation": req_int(body, "min_membership_months_before_accreditation"),
        "consultant_travel_buffer_days": req_int(body, "consultant_travel_buffer_days"),
        "plan_response_days": req_int(body, "plan_response_days"),
    }
    stamp_new(cat)
    db.catalogs[cat["id"]] = cat
    return ok(serialize_catalog(cat), 201)


@bp.route("/standards-catalogs/<catalog_id>", methods=["GET"])
def get_catalog(catalog_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return ok(serialize_catalog(_get_catalog(catalog_id)), 200)


@bp.route("/standards-catalogs/<catalog_id>/activate", methods=["POST"])
def activate_catalog(catalog_id):
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    cat = _get_catalog(catalog_id)
    # Tier 6: activation is allowed only from DRAFT.
    if cat["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a DRAFT catalog can be activated.")
    # Tier 9: effective_from must be strictly later than the current ACTIVE's.
    current = active_catalog()
    if current is not None and current["id"] != cat["id"]:
        new_eff = parse_date(cat["effective_from"])
        cur_eff = parse_date(current["effective_from"])
        if new_eff is None or cur_eff is None or not new_eff > cur_eff:
            raise ApiError(ERR_CATALOG_EFFECTIVE_ORDER[0],
                           ERR_CATALOG_EFFECTIVE_ORDER[1],
                           "effective_from must be strictly later than the "
                           "currently ACTIVE catalog's.")
    if current is not None and current["id"] != cat["id"]:
        current["status"] = "RETIRED"
        touch(current)
    cat["status"] = "ACTIVE"
    touch(cat)
    return ok(serialize_catalog(cat), 200)

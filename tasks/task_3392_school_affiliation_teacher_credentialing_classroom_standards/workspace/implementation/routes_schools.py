"""School onboarding, brand, dues, standing, and the public directory
(PRD 3.2, 3.7, 3.8)."""

from flask import Blueprint

from cascade import apply_standing_transition, OPEN_PLAN_STATES
from derived import directory_visible, brand_compliant
from envelope import ok, pagination_params, paginate, list_response
from errors import (
    ApiError,
    ERR_SCHOOL_NOT_FOUND,
    ERR_DISPLAY_NAME_TAKEN,
    ERR_BRAND_DIFFERENTIATION_REQUIRED,
    ERR_INVALID_STATE,
    ERR_OPEN_IMPROVEMENT_PLAN,
    ERR_VALIDATION,
)
from serializers import serialize_school
from store import db, new_id, stamp_new, touch, parse_date
from validation import (
    authenticate,
    require_role,
    payload,
    req_str,
    opt_str,
    req_bool,
    req_int,
    req_enum,
)

bp = Blueprint("schools", __name__)

SCHOOL_READ_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin", "Registrar"}
SCHOOL_LIST_ROLES = {"SocietyAdmin", "AccreditationReviewer", "Registrar"}
STANDINGS = {"GOOD_STANDING", "PROBATION", "SUSPENDED", "REVOKED"}

# Reviewer-driven standing transitions (PRD 3.7 ladder).
_ALLOWED_STANDING_TRANSITIONS = {
    ("GOOD_STANDING", "PROBATION"),
    ("PROBATION", "SUSPENDED"),
    ("PROBATION", "GOOD_STANDING"),
    ("SUSPENDED", "GOOD_STANDING"),
    ("GOOD_STANDING", "REVOKED"),
    ("PROBATION", "REVOKED"),
    ("SUSPENDED", "REVOKED"),
}


def get_school_or_404(school_id):
    s = db.schools.get(school_id)
    if s is None:
        raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                       "No school with id %r." % school_id)
    return s


def _check_display_name_unique(display_name, exclude_id=None):
    for s in db.schools.values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["display_name"].lower() == display_name.lower():
            raise ApiError(ERR_DISPLAY_NAME_TAKEN[0], ERR_DISPLAY_NAME_TAKEN[1],
                           "display_name is already in use.")


def _check_brand(display_name, uses_method_name, descriptor, membership_level):
    """PRD 3.2: a non-ACCREDITED school using the method name must carry a
    descriptor that actually appears inside its display_name."""
    compliant = (
        (not uses_method_name)
        or membership_level == "ACCREDITED"
        or (bool(descriptor) and descriptor in display_name)
    )
    if not compliant:
        raise ApiError(ERR_BRAND_DIFFERENTIATION_REQUIRED[0],
                       ERR_BRAND_DIFFERENTIATION_REQUIRED[1],
                       "A non-ACCREDITED school using the method name must "
                       "include a differentiating descriptor in its display name.")


@bp.route("/schools", methods=["POST"])
def create_school():
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    body = payload()
    name = req_str(body, "name")
    display_name = req_str(body, "display_name")
    uses_method_name = req_bool(body, "uses_method_name")
    descriptor = opt_str(body, "descriptor")
    contact_email = req_str(body, "contact_email")
    # Tier 9: display-name uniqueness, then brand differentiation.
    _check_display_name_unique(display_name)
    _check_brand(display_name, uses_method_name, descriptor, "APPLICANT")
    school = {
        "id": new_id(),
        "name": name,
        "display_name": display_name,
        "uses_method_name": uses_method_name,
        "descriptor": descriptor,
        "contact_email": contact_email,
        "membership_level": "APPLICANT",
        "standing": "GOOD_STANDING",
        "affiliated_since": None,
        "member_since": None,
        "accredited_since": None,
        "dues_paid_through": None,
        "pinned_catalog_id": None,
    }
    stamp_new(school)
    db.schools[school["id"]] = school
    return ok(serialize_school(school), 201)


@bp.route("/schools/<school_id>", methods=["GET"])
def get_school(school_id):
    _, role = authenticate()
    require_role(role, SCHOOL_READ_ROLES)
    return ok(serialize_school(get_school_or_404(school_id)), 200)


@bp.route("/schools", methods=["GET"])
def list_schools():
    _, role = authenticate()
    require_role(role, SCHOOL_LIST_ROLES)
    from flask import request
    args = request.args
    items = list(db.schools.values())
    for f in ("membership_level", "standing", "pinned_catalog_id"):
        v = args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_school)


@bp.route("/schools/<school_id>/brand", methods=["POST"])
def update_brand(school_id):
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    school = get_school_or_404(school_id)
    body = payload()
    display_name = req_str(body, "display_name")
    uses_method_name = req_bool(body, "uses_method_name")
    descriptor = opt_str(body, "descriptor")
    # Tier 5: entity-backed ownership.
    if uid != school["id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "SchoolAdmin may only update their own school.")
    # Tier 9: uniqueness (excluding self), then brand differentiation.
    _check_display_name_unique(display_name, exclude_id=school["id"])
    _check_brand(display_name, uses_method_name, descriptor, school["membership_level"])
    school["display_name"] = display_name
    school["uses_method_name"] = uses_method_name
    school["descriptor"] = descriptor
    touch(school)
    return ok(serialize_school(school), 200)


@bp.route("/schools/<school_id>/dues-payments", methods=["POST"])
def record_dues_payment(school_id):
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    school = get_school_or_404(school_id)
    body = payload()
    period_start = req_str(body, "period_start")
    period_end = req_str(body, "period_end")
    req_int(body, "amount_cents")
    if parse_date(period_start) is None or parse_date(period_end) is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "period_start and period_end must be ISO dates (YYYY-MM-DD).")
    school["dues_paid_through"] = period_end
    touch(school)
    return ok(serialize_school(school), 201)


@bp.route("/schools/<school_id>/standing", methods=["POST"])
def change_standing(school_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    school = get_school_or_404(school_id)
    body = payload()
    to_standing = req_enum(body, "to_standing", STANDINGS)
    # Tier 6: the requested transition must exist on the standing ladder.
    if (school["standing"], to_standing) not in _ALLOWED_STANDING_TRANSITIONS:
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Standing transition %s -> %s is not permitted."
                       % (school["standing"], to_standing))
    # Tier 9: restoring GOOD_STANDING requires no open improvement plans.
    if to_standing == "GOOD_STANDING":
        open_plans = [
            p for p in db.plans.values()
            if p["school_id"] == school["id"] and p["status"] in OPEN_PLAN_STATES
        ]
        if open_plans:
            raise ApiError(ERR_OPEN_IMPROVEMENT_PLAN[0], ERR_OPEN_IMPROVEMENT_PLAN[1],
                           "The school still has open improvement plans.")
    apply_standing_transition(school, to_standing)
    return ok(serialize_school(school), 200)


# ---------------------------------------------------------------------------
# Public directory (PRD 3.8) — anonymous callers accepted, no auth tier.
# ---------------------------------------------------------------------------

def _public_payload(school, listed):
    if not listed:
        return {"display_name": school["display_name"], "listed": False}
    return {
        "school_id": school["id"],
        "display_name": school["display_name"],
        "listed": True,
        "membership_level": school["membership_level"],
        "standing": school["standing"],
        "accredited": school["membership_level"] == "ACCREDITED",
        "brand_compliant": brand_compliant(school),
    }


@bp.route("/directory", methods=["GET"])
def directory_list():
    items = [s for s in db.schools.values() if directory_visible(s)]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    limit, offset = pagination_params()
    page, meta = paginate(items, limit, offset)
    data = {
        "items": [_public_payload(s, True) for s in page],
        "total_count": meta["total_count"],
        "has_more": meta["has_more"],
    }
    return ok(data, 200, pagination=meta)


@bp.route("/directory/<school_id>", methods=["GET"])
def directory_verify(school_id):
    school = db.schools.get(school_id)
    if school is None:
        raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                       "No school with id %r." % school_id)
    return ok(_public_payload(school, directory_visible(school)), 200)

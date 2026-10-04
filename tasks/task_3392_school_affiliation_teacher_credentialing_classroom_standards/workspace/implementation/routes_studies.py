"""Self-studies (PRD 3.6): DRAFT -> SUBMITTED -> ACCEPTED /
RETURNED_FOR_REVISION, with catalog pinning and school-version OCC."""

from flask import Blueprint, request

from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_SCHOOL_NOT_FOUND,
    ERR_SELF_STUDY_NOT_FOUND,
    ERR_VALIDATION,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_IN_FLIGHT_SELF_STUDY_EXISTS,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_self_study
from store import db, new_id, stamp_new, touch, now_iso, active_catalog
from validation import authenticate, require_role, payload, req_enum

bp = Blueprint("self_studies", __name__)

STUDY_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin"}
STUDY_OUTCOMES = {"ACCEPTED", "RETURNED_FOR_REVISION"}
IN_FLIGHT_STUDY_STATES = ("DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION")


def get_study_or_404(study_id):
    s = db.self_studies.get(study_id)
    if s is None:
        raise ApiError(ERR_SELF_STUDY_NOT_FOUND[0], ERR_SELF_STUDY_NOT_FOUND[1],
                       "No self-study with id %r." % study_id)
    return s


@bp.route("/self-studies", methods=["POST"])
def create_self_study():
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    body = payload()
    # Tier 3: school_id body FK.
    school_id = body.get("school_id")
    school = None
    if isinstance(school_id, str):
        school = db.schools.get(school_id)
        if school is None:
            raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                           "No school with id %r." % school_id)
    # Tier 4: shape (narrative required but may be empty until submission).
    if not isinstance(school_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'school_id' is required and must be a string.")
    narrative = body.get("narrative")
    if not isinstance(narrative, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'narrative' is required and must be a string.")
    expected = body.get("expected_school_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'expected_school_version' is required and must be an integer.")
    # Tier 5: ownership.
    if uid != school["id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only open a self-study for their own school.")
    # Tier 6: OCC.
    if expected != school["version"]:
        raise ApiError(ERR_STALE_VERSION[0], ERR_STALE_VERSION[1],
                       "expected_school_version does not match the school's current version.")
    # Tier 9: one in-flight self-study per school; an ACTIVE catalog is pinned.
    for s in db.self_studies.values():
        if s["school_id"] == school["id"] and s["status"] in IN_FLIGHT_STUDY_STATES:
            raise ApiError(ERR_IN_FLIGHT_SELF_STUDY_EXISTS[0],
                           ERR_IN_FLIGHT_SELF_STUDY_EXISTS[1],
                           "The school already has an in-flight self-study.")
    cat = active_catalog()
    if cat is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    study = {
        "id": new_id(),
        "school_id": school["id"],
        "narrative": narrative,
        "status": "DRAFT",
        "pinned_catalog_id": cat["id"],
        "pinned_catalog_label": cat["version_label"],
        "submitted_at": None,
    }
    stamp_new(study)
    db.self_studies[study["id"]] = study
    touch(school)  # creating a self-study is a direct school mutation
    return ok(serialize_self_study(study), 201)


@bp.route("/self-studies/<study_id>", methods=["GET"])
def get_self_study(study_id):
    _, role = authenticate()
    require_role(role, STUDY_ROLES)
    return ok(serialize_self_study(get_study_or_404(study_id)), 200)


@bp.route("/self-studies", methods=["GET"])
def list_self_studies():
    _, role = authenticate()
    require_role(role, STUDY_ROLES)
    args = request.args
    items = list(db.self_studies.values())
    for f in ("school_id", "pinned_catalog_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_self_study)


@bp.route("/self-studies/<study_id>/submit", methods=["POST"])
def submit_self_study(study_id):
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    study = get_study_or_404(study_id)
    # Tier 5: ownership.
    if uid != study["school_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only submit their own school's self-study.")
    # Tier 6: submission only from DRAFT or RETURNED_FOR_REVISION.
    if study["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a DRAFT or RETURNED_FOR_REVISION self-study can be submitted.")
    # The narrative must be non-empty at submission (PRD 3.6).
    if not study["narrative"]:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "The self-study narrative must be non-empty.")
    study["status"] = "SUBMITTED"
    study["submitted_at"] = now_iso()
    touch(study)
    return ok(serialize_self_study(study), 200)


@bp.route("/self-studies/<study_id>/review", methods=["POST"])
def review_self_study(study_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    study = get_study_or_404(study_id)
    body = payload()
    outcome = req_enum(body, "outcome", STUDY_OUTCOMES)
    # Tier 6: only a SUBMITTED study is actionable.
    if study["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SUBMITTED self-study can be reviewed.")
    study["status"] = outcome
    touch(study)
    if outcome == "ACCEPTED":
        # The school adopts the study's pinned edition (PRD 2.6, 3.6).
        school = db.schools[study["school_id"]]
        school["pinned_catalog_id"] = study["pinned_catalog_id"]
        touch(school)  # self-study acceptance is a direct school mutation
    return ok(serialize_self_study(study), 200)

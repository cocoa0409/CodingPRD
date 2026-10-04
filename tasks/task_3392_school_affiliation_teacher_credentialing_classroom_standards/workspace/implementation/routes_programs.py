"""Teacher education programs and adult learners (PRD 3.4)."""

from flask import Blueprint, request

from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_FORBIDDEN,
    ERR_PROGRAM_NOT_FOUND,
    ERR_LEARNER_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_AGE_LEVEL_MISMATCH,
    ERR_PRACTICUM_STANDARD_UNMET,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_program, serialize_learner
from store import db, new_id, stamp_new, touch, active_catalog
from validation import (
    authenticate,
    require_role,
    payload,
    req_str,
    req_enum,
    req_list,
    req_dict,
    AGE_LEVELS,
)

bp = Blueprint("programs", __name__)

PROGRAM_READ_ROLES = {"SocietyAdmin", "AccreditationReviewer", "ProgramDirector", "Registrar"}
LEARNER_READ_ROLES = PROGRAM_READ_ROLES | {"AdultLearner"}
PROGRAM_STATUSES = {"PROVISIONAL", "ACCREDITED", "PROBATION", "SUSPENDED"}

# AccreditationReviewer decision transitions (PRD 3.4).
_ALLOWED_PROGRAM_TRANSITIONS = {
    ("PROVISIONAL", "ACCREDITED"),
    ("ACCREDITED", "PROBATION"),
    ("PROBATION", "ACCREDITED"),
    ("ACCREDITED", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
}


def get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if p is None:
        raise ApiError(ERR_PROGRAM_NOT_FOUND[0], ERR_PROGRAM_NOT_FOUND[1],
                       "No teacher education program with id %r." % program_id)
    return p


def _validate_hours_map(body, field):
    m = req_dict(body, field)
    for k, v in m.items():
        if k not in AGE_LEVELS:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "%s keys must be age levels." % field)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "%s values must be non-negative integers." % field)
    return m


@bp.route("/teacher-education-programs", methods=["POST"])
def create_program():
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    body = payload()
    name = req_str(body, "name")
    levels = req_list(body, "age_levels_offered", non_empty=True)
    for lv in levels:
        if lv not in AGE_LEVELS:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "age_levels_offered must be a non-empty subset of the age-level enum.")
    program = {
        "id": new_id(),
        "name": name,
        "age_levels_offered": list(levels),
        "course_contact_hours_by_level": _validate_hours_map(body, "course_contact_hours_by_level"),
        "practicum_hours_by_level": _validate_hours_map(body, "practicum_hours_by_level"),
        "status": "PROVISIONAL",
    }
    stamp_new(program)
    db.programs[program["id"]] = program
    return ok(serialize_program(program), 201)


@bp.route("/teacher-education-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _, role = authenticate()
    require_role(role, PROGRAM_READ_ROLES)
    return ok(serialize_program(get_program_or_404(program_id)), 200)


@bp.route("/teacher-education-programs/<program_id>/status", methods=["POST"])
def change_program_status(program_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    program = get_program_or_404(program_id)
    body = payload()
    to_status = req_enum(body, "to_status", PROGRAM_STATUSES)
    # Tier 6: only the five declared transitions exist.
    if (program["status"], to_status) not in _ALLOWED_PROGRAM_TRANSITIONS:
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Program transition %s -> %s is not permitted."
                       % (program["status"], to_status))
    # Tier 9: PROVISIONAL -> ACCREDITED requires the practicum standard for
    # every offered level against the ACTIVE catalog.
    if program["status"] == "PROVISIONAL" and to_status == "ACCREDITED":
        cat = active_catalog()
        if cat is None:
            raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                           "No ACTIVE standards catalog exists.")
        mins = cat["practicum_min_hours_by_level"]
        for lv in program["age_levels_offered"]:
            offered = program["practicum_hours_by_level"].get(lv, 0)
            if offered < mins.get(lv, 0):
                raise ApiError(ERR_PRACTICUM_STANDARD_UNMET[0],
                               ERR_PRACTICUM_STANDARD_UNMET[1],
                               "Practicum hours for %s are below the ACTIVE "
                               "catalog's minimum." % lv)
    program["status"] = to_status
    touch(program)
    return ok(serialize_program(program), 200)


# ---------------------------------------------------------------------------
# Adult learners
# ---------------------------------------------------------------------------

@bp.route("/adult-learners", methods=["POST"])
def create_learner():
    uid, role = authenticate()
    require_role(role, {"ProgramDirector"})
    body = payload()
    # Tier 3: program_id body FK.
    program_id = body.get("program_id")
    program = None
    if isinstance(program_id, str):
        program = db.programs.get(program_id)
        if program is None:
            raise ApiError(ERR_PROGRAM_NOT_FOUND[0], ERR_PROGRAM_NOT_FOUND[1],
                           "No teacher education program with id %r." % program_id)
    # Tier 4: shape.
    if not isinstance(program_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'program_id' is required and must be a string.")
    full_name = req_str(body, "full_name")
    age_level = req_enum(body, "age_level", AGE_LEVELS)
    # Tier 5: the director's X-User-ID must equal the payload's program_id.
    if uid != program["id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "ProgramDirector may only enroll learners into their own program.")
    # Tier 6: enrollment is open only while PROVISIONAL or ACCREDITED.
    if program["status"] not in ("PROVISIONAL", "ACCREDITED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Enrollment is closed for a %s program." % program["status"])
    # Tier 8: the learner's age level must be offered by the program.
    if age_level not in program["age_levels_offered"]:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "The program does not offer age level %s." % age_level)
    learner = {
        "id": new_id(),
        "program_id": program["id"],
        "full_name": full_name,
        "age_level": age_level,
        "status": "ENROLLED",
    }
    stamp_new(learner)
    db.learners[learner["id"]] = learner
    return ok(serialize_learner(learner), 201)


@bp.route("/adult-learners/<learner_id>", methods=["GET"])
def get_learner(learner_id):
    _, role = authenticate()
    require_role(role, LEARNER_READ_ROLES)
    learner = db.learners.get(learner_id)
    if learner is None:
        raise ApiError(ERR_LEARNER_NOT_FOUND[0], ERR_LEARNER_NOT_FOUND[1],
                       "No adult learner with id %r." % learner_id)
    return ok(serialize_learner(learner), 200)


@bp.route("/adult-learners", methods=["GET"])
def list_learners():
    _, role = authenticate()
    require_role(role, PROGRAM_READ_ROLES)
    args = request.args
    items = list(db.learners.values())
    for f in ("program_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_learner)

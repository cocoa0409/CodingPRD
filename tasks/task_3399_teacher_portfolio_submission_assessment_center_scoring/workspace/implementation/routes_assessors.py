"""Assessor pipeline endpoints (PRD 3.5) and calibration benchmarks (PRD 3.6):
POST /assessors, GET /assessors/{id}, POST /assessors/{id}/transition,
POST /benchmarks."""
from flask import Blueprint

import constants as C
import domain
import errors as E
import serializers as ser
from response import ok
from store import DB, new_id, stamp_new, touch
from validation import (auth_headers, require_role, body, req_field,
                        as_number, validate_score_value)

bp = Blueprint("assessors", __name__)


@bp.post("/assessors")
def create_assessor():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN])
    data = body()
    full_name = req_field(data, "full_name")
    email = req_field(data, "email")
    home_district_code = req_field(data, "home_district_code")
    assessor = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "home_district_code": home_district_code,
        "status": "RECRUITED",
        "calibration_passes": 0,
        "calibration_failures": 0,
        "calibrated_at": None,
    }
    stamp_new(assessor)
    DB.assessors[assessor["id"]] = assessor
    return ok(ser.assessor(assessor), 201)


@bp.get("/assessors/<assessor_id>")
def get_assessor(assessor_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_ASSESSOR, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    if role == C.ROLE_ASSESSOR and uid != assessor_id:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Assessors may read only their own record")
    assessor = DB.assessors.get(assessor_id)
    if assessor is None:
        E.fail(E.ERR_ASSESSOR_NOT_FOUND, 404,
               "Assessor not found: %s" % assessor_id)
    return ok(ser.assessor(assessor))


_ADMIN_TRANSITIONS = {
    ("RECRUITED", "IN_TRAINING"),
    ("SUSPENDED", "IN_TRAINING"),
    ("IN_TRAINING", "CALIBRATING"),
    ("CALIBRATED", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
}


@bp.post("/assessors/<assessor_id>/transition")
def transition_assessor(assessor_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN])
    assessor = DB.assessors.get(assessor_id)
    if assessor is None:
        E.fail(E.ERR_ASSESSOR_NOT_FOUND, 404,
               "Assessor not found: %s" % assessor_id)
    data = body()
    target = req_field(data, "to")
    if (assessor["status"], target) not in _ADMIN_TRANSITIONS:
        E.fail(E.ERR_INVALID_ASSESSOR_TRANSITION, 409,
               "Assessor in %s cannot be transitioned to %s"
               % (assessor["status"], target))
    if target == "IN_TRAINING" and assessor["status"] == "SUSPENDED":
        # Retraining loop resets the calibration counters.
        assessor["calibration_passes"] = 0
        assessor["calibration_failures"] = 0
        assessor["status"] = "IN_TRAINING"
        touch(assessor)
    elif target == "SUSPENDED":
        domain.suspend_assessor(assessor)
    else:
        assessor["status"] = target
        touch(assessor)
    return ok(ser.assessor(assessor))


@bp.post("/benchmarks")
def create_benchmark():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN])
    data = body()
    component_code = req_field(data, "component_code")
    content_domain = req_field(data, "content_domain")
    known_score = validate_score_value(req_field(data, "known_score"),
                                       "known_score")
    tolerance = as_number(data.get("tolerance", C.DEFAULT_TOLERANCE), "tolerance")
    benchmark = {
        "id": new_id(),
        "component_code": component_code,
        "content_domain": content_domain,
        "known_score": known_score,
        "tolerance": tolerance,
    }
    stamp_new(benchmark)
    DB.benchmarks[benchmark["id"]] = benchmark
    return ok(ser.benchmark(benchmark), 201)

"""Grade routes."""
import uuid
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_num, req_bool)
from services import get_mill, get_grade

bp = Blueprint("grades", __name__)


@bp.route("/mills/<millId>/grades", methods=["POST"])
def create_grade(millId):
    require_role("Metallurgist", "PlantManager")
    get_mill(millId)
    body = get_body()
    code = req_str(body, "grade_code")
    form = req_enum(body, "product_form", {"BILLET", "BLOOM", "SLAB"})
    group = req_enum(body, "grade_group", {"GROUP_A", "GROUP_B"})
    cert = req_enum(body, "certification_class", {"STANDARD", "CERTIFIED"})
    cu_max = req_num(body, "cu_max_pct", gt=0)
    mn_min = req_num(body, "mn_min_pct", ge=0)
    mn_max = req_num(body, "mn_max_pct")
    if mn_max < mn_min:
        raise err("ERR_INVALID_REQUEST", "mn_max_pct must be >= mn_min_pct")
    rec = req_bool(body, "requires_energy_certified")
    for g in db.grades.values():
        if g["mill_id"] == millId and g["grade_code"] == code:
            raise err("ERR_INVALID_REQUEST", "grade_code must be unique per mill")
    grade = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "grade_code": code,
        "product_form": form,
        "grade_group": group,
        "certification_class": cert,
        "cu_max_pct": cu_max,
        "mn_min_pct": mn_min,
        "mn_max_pct": mn_max,
        "requires_energy_certified": rec,
        "created_at": db.ts_now(),
    }
    db.grades[grade["id"]] = grade
    return ok(grade, 201)


@bp.route("/mills/<millId>/grades", methods=["GET"])
def list_grades(millId):
    require_auth()
    get_mill(millId)
    rows = [g for g in db.grades.values() if g["mill_id"] == millId]
    return list_response(rows, {"product_form": "product_form",
                                "certification_class": "certification_class"})


@bp.route("/mills/<millId>/grades/by-id/<gradeId>", methods=["GET"])
def get_grade_route(millId, gradeId):
    require_auth()
    get_mill(millId)
    return ok(get_grade(gradeId, millId))


@bp.route("/mills/grades", methods=["GET"])
def flat_list_grades():
    require_auth()
    return list_response(list(db.grades.values()),
                         {"mill_id": "mill_id", "product_form": "product_form",
                          "certification_class": "certification_class"})


@bp.route("/mills/grades/<gradeId>", methods=["GET"])
def flat_get_grade(gradeId):
    require_auth()
    return ok(get_grade(gradeId))

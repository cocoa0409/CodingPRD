"""CareProgram endpoints + program clock advance."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_input, ERR_PROGRAM_NOT_FOUND,
                    ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.clock import sweep_episode_lapses
from services.resources import base_fields, touch
from services.validation import (get_json_body, require_field, require_int,
                                 require_list, optional_int, require_string)

bp = Blueprint("programs", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "EngagementSpecialist", "Clinician", "PerformanceAnalyst"]


@bp.route("/care-programs", methods=["POST"])
def create_program():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    program_code = require_string(body, "program_code")
    display_name = require_string(body, "display_name")
    zips = require_list(body, "service_geography_zips")
    sla_hours = optional_int(body, "urgent_response_sla_hours", 24)

    p = base_fields()
    p.update({
        "program_code": program_code,
        "display_name": display_name,
        "service_geography_zips": list(zips),
        "urgent_response_sla_hours": sla_hours,
        "current_period_index": 0,
    })
    db.care_programs[p["id"]] = p
    return success_object(serializers.care_program(p), status=201)


@bp.route("/care-programs", methods=["GET"])
def list_programs():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.care_programs.values(),
                   key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.care_program(p) for p in page],
                        limit, offset, total)


@bp.route("/care-programs/<programId>", methods=["GET"])
def get_program(programId):
    require_roles(READ_ROLES)
    p = db.care_programs.get(programId)
    if p is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")
    return success_object(serializers.care_program(p))


@bp.route("/care-programs/<programId>/clock/advance", methods=["POST"])
def advance_program_clock(programId):
    require_roles(["PlatformAdmin"])
    p = db.care_programs.get(programId)
    if p is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")
    body = get_json_body()
    by_days = require_int(body, "by_days")
    p["current_period_index"] = int(p.get("current_period_index") or 0) + by_days
    touch(p)
    # Period advance also triggers the LAPSED sweep (SCAFFOLD §1.5).
    sweep_episode_lapses()
    return success_object(serializers.care_program(p))

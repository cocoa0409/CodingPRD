"""Clinician endpoints."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_input, ERR_CLINICIAN_NOT_FOUND,
                    ERR_PROGRAM_NOT_FOUND, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.resources import base_fields
from services.validation import (get_json_body, require_string, require_enum,
                                 require_int, optional_bool)

bp = Blueprint("clinicians", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "Clinician"]
DISCIPLINES = {"NP", "SW", "BH"}


@bp.route("/clinicians", methods=["POST"])
def create_clinician():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    care_program_id = require_string(body, "care_program_id")
    full_name = require_string(body, "full_name")
    discipline = require_enum(body, "discipline", DISCIPLINES)
    home_zip = require_string(body, "home_zip")
    max_daily_visits = require_int(body, "max_daily_visits")
    urgent_qualified = optional_bool(body, "urgent_response_qualified", False)

    if db.care_programs.get(care_program_id) is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")

    c = base_fields()
    c.update({
        "care_program_id": care_program_id,
        "full_name": full_name,
        "discipline": discipline,
        "home_zip": home_zip,
        "max_daily_visits": max_daily_visits,
        "active_daily_visit_count": 0,
        "urgent_response_qualified": urgent_qualified,
        "status": "ACTIVE",
    })
    db.clinicians[c["id"]] = c
    return success_object(serializers.clinician(c), status=201)


@bp.route("/clinicians", methods=["GET"])
def list_clinicians():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.clinicians.values())
    cp = request.args.get("care_program_id")
    if cp:
        items = [c for c in items if c.get("care_program_id") == cp]
    d = request.args.get("discipline")
    if d:
        items = [c for c in items if c.get("discipline") == d]
    s = request.args.get("status")
    if s:
        items = [c for c in items if c.get("status") == s]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.clinician(c) for c in page],
                        limit, offset, total)


@bp.route("/clinicians/<clinicianId>", methods=["GET"])
def get_clinician(clinicianId):
    require_roles(READ_ROLES)
    c = db.clinicians.get(clinicianId)
    if c is None:
        raise err_not_found(ERR_CLINICIAN_NOT_FOUND, "Clinician")
    return success_object(serializers.clinician(c))

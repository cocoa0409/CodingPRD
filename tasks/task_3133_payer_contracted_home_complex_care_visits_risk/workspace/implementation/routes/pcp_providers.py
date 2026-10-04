"""PCPProvider endpoints."""
from flask import Blueprint, request

from db import db
from errors import err_not_found, ERR_PCP_NOT_FOUND, ERR_PROGRAM_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.resources import base_fields
from services.validation import (get_json_body, require_string, optional_bool)

bp = Blueprint("pcp_providers", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "EngagementSpecialist"]


@bp.route("/pcp-providers", methods=["POST"])
def create_pcp():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    care_program_id = require_string(body, "care_program_id")
    npi = require_string(body, "npi")
    full_name = require_string(body, "full_name")
    practice_name = require_string(body, "practice_name")
    opt_in = optional_bool(body, "notification_opt_in", True)

    if db.care_programs.get(care_program_id) is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")

    p = base_fields()
    p.update({
        "care_program_id": care_program_id,
        "npi": npi,
        "full_name": full_name,
        "practice_name": practice_name,
        "notification_opt_in": opt_in,
    })
    db.pcp_providers[p["id"]] = p
    return success_object(serializers.pcp_provider(p), status=201)


@bp.route("/pcp-providers", methods=["GET"])
def list_pcps():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.pcp_providers.values())
    cp = request.args.get("care_program_id")
    if cp:
        items = [p for p in items if p.get("care_program_id") == cp]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.pcp_provider(p) for p in page],
                        limit, offset, total)


@bp.route("/pcp-providers/<pcpId>", methods=["GET"])
def get_pcp(pcpId):
    require_roles(READ_ROLES)
    p = db.pcp_providers.get(pcpId)
    if p is None:
        raise err_not_found(ERR_PCP_NOT_FOUND, "PCPProvider")
    return success_object(serializers.pcp_provider(p))

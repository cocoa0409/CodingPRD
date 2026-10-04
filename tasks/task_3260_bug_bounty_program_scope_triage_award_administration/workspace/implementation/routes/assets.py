"""Scope asset endpoints."""
from flask import Blueprint, request

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import asset_out

bp = Blueprint("assets", __name__)

CRITICALITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
CREATE_FIELDS = {"program_id", "name", "asset_identifier", "criticality"}


def _get_asset(aid):
    a = db.assets.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Asset {aid} not found")
    return a


@bp.route("/api/assets", methods=["POST"])
def create_asset():
    require_roles({"ProgramAdmin"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["program_id", "name", "asset_identifier", "criticality"])
    if body["program_id"] not in db.programs:
        raise_err(ERR_NOT_FOUND, f"Program {body['program_id']} not found")
    if body["criticality"] not in CRITICALITIES:
        raise_err(ERR_INVALID_REQUEST, "Invalid criticality")
    a = base_entity()
    a.update(
        {
            "program_id": body["program_id"],
            "name": body["name"],
            "asset_identifier": body["asset_identifier"],
            "criticality": body["criticality"],
            "status": "ACTIVE",
        }
    )
    db.assets[a["id"]] = a
    return success_object(asset_out(a), 201)


@bp.route("/api/assets", methods=["GET"])
def list_assets():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.assets.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [a for a in items if a["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([asset_out(a) for a in page], limit, offset, total)


@bp.route("/api/assets/<asset_id>", methods=["GET"])
def read_asset(asset_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(asset_out(_get_asset(asset_id)))


@bp.route("/api/assets/<asset_id>/retire", methods=["POST"])
def retire_asset(asset_id):
    require_roles({"ProgramAdmin"})
    a = _get_asset(asset_id)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Asset is not ACTIVE")
    a["status"] = "RETIRED"
    touch(a)
    return success_object(asset_out(a))

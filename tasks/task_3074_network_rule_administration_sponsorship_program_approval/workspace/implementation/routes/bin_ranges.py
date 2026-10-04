"""BIN ranges: request, list, get, approve, deactivate."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, is_digits, paginate,
    req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import ok

bp = Blueprint("bin_ranges", __name__)

READ_ROLES = {"NetworkOperator", "CertificationEngineer"}


@bp.post("/network/bin-ranges")
def create_bin_range():
    require_roles({"NetworkOperator"})
    body = get_json()
    bin_prefix = req_str(body, "bin_prefix")
    issuer_member_id = req_str(body, "issuer_member_id")
    issuer = exists_or_404(db.members, issuer_member_id, "issuer member")
    if not is_digits(bin_prefix, 6):
        raise_err("ERR_VALIDATION", "bin_prefix must be exactly 6 digits")
    if issuer["status"] != "ACTIVE" or issuer["member_kind"] not in ("ISSUER", "BOTH"):
        raise_err("ERR_VALIDATION", "Issuer must be an ACTIVE member of kind ISSUER or BOTH")
    rec = base_record()
    rec.update({
        "bin_prefix": bin_prefix,
        "issuer_member_id": issuer_member_id,
        "status": "REQUESTED",
        "assigned_program_id": None,
    })
    db.bin_ranges[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/bin-ranges")
def list_bin_ranges():
    require_roles(READ_ROLES)
    items = list(db.bin_ranges.values())
    issuer = request.args.get("issuer_member_id")
    assigned = request.args.get("assigned_program_id")
    status = request.args.get("status")
    if issuer is not None:
        items = [b for b in items if b["issuer_member_id"] == issuer]
    if assigned is not None:
        items = [b for b in items if b.get("assigned_program_id") == assigned]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/bin-ranges/<bid>")
def get_bin_range(bid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.bin_ranges, bid)
    return ok(rec, 200)


@bp.post("/network/bin-ranges/<bid>/approve")
def approve_bin_range(bid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.bin_ranges, bid)
    body = get_json()
    program_id = req_str(body, "program_id")
    program = exists_or_404(db.programs, program_id, "program")
    if rec["status"] != "REQUESTED":
        raise_err("ERR_INVALID_STATE", "BinRange is not REQUESTED")
    issuer = db.members.get(rec["issuer_member_id"])
    if issuer is None or issuer["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Issuer member is not ACTIVE")
    if program["status"] != "PRODUCTION_ENABLED":
        raise_err("ERR_PROGRAM_NOT_ENABLED", "Referenced program is not PRODUCTION_ENABLED")
    rec["status"] = "ACTIVE"
    rec["assigned_program_id"] = program_id
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/bin-ranges/<bid>/deactivate")
def deactivate_bin_range(bid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.bin_ranges, bid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "BinRange is not ACTIVE")
    rec["status"] = "DEACTIVATED"
    touch(rec)
    return ok(rec, 200)

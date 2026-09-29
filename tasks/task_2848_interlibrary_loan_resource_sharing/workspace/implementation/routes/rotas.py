"""Rota and rota-entry endpoints (PRD 3.2)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (ADMIN, ILL_STAFF, auth, get_rota,
                        get_rota_entry)
from response import ok_row
from routes.common import filter_eq, list_response
from validate import (body, opt_bool, opt_int, q_enum, raw_id, req_enum,
                      req_int, req_str)

bp = Blueprint("rotas", __name__)

MATERIAL_TYPES = ("LOAN", "COPY")
SELECTION_POLICIES = ("LANDED_COST", "MANUAL_RANK")
ENTRY_STATUSES = ("ACTIVE", "SUPERSEDED")


@bp.route("/ill/rotas", methods=["POST"])
def create_rota():
    auth(ADMIN, ILL_STAFF)
    data = body()
    name = req_str(data, "name")
    material_type = req_enum(data, "material_type", MATERIAL_TYPES)
    selection_policy = req_enum(data, "selection_policy", SELECTION_POLICIES)
    max_attempts = opt_int(data, "max_attempts", 3, 1, 10)
    auto_escalate = opt_bool(data, "auto_escalate_pod", False)
    response_hours = opt_int(data, "offer_response_hours", 48, 1, 720)
    row = base_row()
    row.update({
        "name": name,
        "material_type": material_type,
        "selection_policy": selection_policy,
        "max_attempts": max_attempts,
        "auto_escalate_pod": auto_escalate,
        "offer_response_hours": response_hours,
    })
    db.rotas[row["id"]] = row
    return ok_row(row, 201)


@bp.route("/ill/rotas/<rota_id>", methods=["GET"])
def get_one_rota(rota_id):
    auth(ILL_STAFF, ADMIN)
    return ok_row(get_rota(rota_id))


@bp.route("/ill/rota-entries", methods=["POST"])
def create_rota_entry():
    auth(ADMIN, ILL_STAFF)
    data = body()
    # rung 32: body foreign keys in declared field order
    rota_ref = raw_id(data, "rota_id")
    if rota_ref is not None and rota_ref not in db.rotas:
        raise ApiError("ERR_ROTA_NOT_FOUND")
    partner_ref = raw_id(data, "partner_id")
    if partner_ref is not None and partner_ref not in db.partners:
        raise ApiError("ERR_PARTNER_NOT_FOUND")
    # rung 35: shape
    rota_id = req_str(data, "rota_id")
    expected_version = req_int(data, "expected_rota_version", 0)
    partner_id = req_str(data, "partner_id")
    manual_rank = req_int(data, "manual_rank", 1)
    partner = db.partners[partner_id]
    quoted_fee = opt_int(data, "quoted_fee_cents", None, 0)
    quoted_turnaround = opt_int(data, "quoted_turnaround_days", None, 0)
    if quoted_fee is None:
        quoted_fee = partner["base_lending_fee_cents"]
    if quoted_turnaround is None:
        quoted_turnaround = partner["avg_turnaround_days"]
    is_enabled = opt_bool(data, "is_enabled", True)
    rota = db.rotas[rota_id]
    # rung 49: optimistic concurrency on the parent rota
    if expected_version != rota["version"]:
        raise ApiError("ERR_STALE_ROTA_VERSION")
    for existing in db.rota_entries.values():
        if existing["rota_id"] == rota_id and existing["partner_id"] == partner_id \
                and existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    row = base_row()
    row.update({
        "rota_id": rota_id,
        "partner_id": partner_id,
        "manual_rank": manual_rank,
        "quoted_fee_cents": quoted_fee,
        "quoted_turnaround_days": quoted_turnaround,
        "is_enabled": is_enabled,
        "status": "ACTIVE",
    })
    db.rota_entries[row["id"]] = row
    touch(rota)
    return ok_row(row, 201)


@bp.route("/ill/rota-entries/<entry_id>", methods=["PATCH"])
def patch_rota_entry(entry_id):
    auth(ADMIN, ILL_STAFF)
    entry = get_rota_entry(entry_id)
    data = body()
    is_enabled = opt_bool(data, "is_enabled")
    manual_rank = opt_int(data, "manual_rank", None, 1)
    if is_enabled is not None:
        entry["is_enabled"] = is_enabled
    if manual_rank is not None:
        entry["manual_rank"] = manual_rank
    touch(entry)
    return ok_row(entry)


@bp.route("/ill/rota-entries/<entry_id>", methods=["GET"])
def get_one_rota_entry(entry_id):
    auth(ILL_STAFF, ADMIN)
    return ok_row(get_rota_entry(entry_id))


@bp.route("/ill/rotas/<rota_id>/entries", methods=["GET"])
def list_rota_entries(rota_id):
    auth(ILL_STAFF, ADMIN)
    get_rota(rota_id)
    rows = [r for r in db.rota_entries.values() if r["rota_id"] == rota_id]
    rows = filter_eq(rows, "status", q_enum("status", ENTRY_STATUSES))
    return list_response(rows, sort_key=lambda r: (r["manual_rank"], r["created_at"],
                                                  r["_seq"]))

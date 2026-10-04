"""Members: apply, list, get, approve, suspend, reinstate, terminate,
plus member-scoped list endpoints (participants, bin-ranges, programs)."""

from flask import Blueprint

import db
from errors import raise_err
from helpers import (
    REGIONS, base_record, get_json, get_or_404, paginate, req_enum, req_str,
    sort_by_created, touch,
)
from middleware import require_roles
from response import ok
from services.cascade import (
    reinstate_member_cascade, suspend_member_cascade, terminate_member_cascade,
)

bp = Blueprint("members", __name__)

MEMBER_KINDS = {"ISSUER", "ACQUIRER", "BOTH"}
READ_ALL_ROLES = {
    "NetworkOperator", "RulesAdministrator", "FraudAnalyst", "SettlementOperator",
    "DisputeAnalyst", "PricingAnalyst", "SponsorshipManager", "CertificationEngineer",
}


@bp.post("/network/members")
def create_member():
    require_roles({"NetworkOperator"})
    body = get_json()
    legal_name = req_str(body, "legal_name")
    member_kind = req_enum(body, "member_kind", MEMBER_KINDS)
    region = req_enum(body, "region", REGIONS)
    rec = base_record()
    rec.update({
        "legal_name": legal_name,
        "member_kind": member_kind,
        "region": region,
        "status": "APPLICATION",
        "suspension_reason": None,
        "settled_balance_cents": 0,
    })
    db.members[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/members")
def list_members():
    require_roles(READ_ALL_ROLES)
    items = list(db.members.values())
    status = _q("status")
    kind = _q("member_kind")
    region = _q("region")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if kind is not None:
        items = [m for m in items if m["member_kind"] == kind]
    if region is not None:
        items = [m for m in items if m["region"] == region]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


def _q(name):
    from flask import request
    return request.args.get(name)


@bp.get("/network/members/<mid>")
def get_member(mid):
    require_roles(READ_ALL_ROLES | {"Member"})
    rec = get_or_404(db.members, mid)
    return ok(rec, 200)


@bp.post("/network/members/<mid>/approve")
def approve_member(mid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.members, mid)
    if rec["status"] != "APPLICATION":
        raise_err("ERR_INVALID_STATE", "Member is not in APPLICATION status")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/members/<mid>/suspend")
def suspend_member(mid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.members, mid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Member is not ACTIVE")
    body = get_json()
    reason = req_str(body, "reason")
    rec["status"] = "SUSPENDED"
    rec["suspension_reason"] = reason
    touch(rec)
    suspend_member_cascade(mid)
    return ok(rec, 200)


@bp.post("/network/members/<mid>/reinstate")
def reinstate_member(mid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.members, mid)
    if rec["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Member is not SUSPENDED")
    rec["status"] = "ACTIVE"
    rec["suspension_reason"] = None
    touch(rec)
    reinstate_member_cascade(mid)
    return ok(rec, 200)


@bp.post("/network/members/<mid>/terminate")
def terminate_member(mid):
    require_roles({"NetworkOperator"})
    rec = get_or_404(db.members, mid)
    if rec["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Member is not SUSPENDED")
    rec["status"] = "TERMINATED"
    touch(rec)
    terminate_member_cascade(mid)
    return ok(rec, 200)


@bp.get("/network/members/<mid>/participants")
def list_member_participants(mid):
    require_roles({"NetworkOperator", "SponsorshipManager", "FraudAnalyst"})
    get_or_404(db.members, mid)
    items = [p for p in db.participants.values() if p["sponsor_member_id"] == mid]
    status = _q("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/members/<mid>/bin-ranges")
def list_member_bin_ranges(mid):
    require_roles({"NetworkOperator", "CertificationEngineer"})
    get_or_404(db.members, mid)
    items = [b for b in db.bin_ranges.values() if b["issuer_member_id"] == mid]
    status = _q("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/members/<mid>/programs")
def list_member_programs(mid):
    require_roles({"NetworkOperator", "CertificationEngineer"})
    get_or_404(db.members, mid)
    items = [p for p in db.programs.values() if p["owner_member_id"] == mid]
    status = _q("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)

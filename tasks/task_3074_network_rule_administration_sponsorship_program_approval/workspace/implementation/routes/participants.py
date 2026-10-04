"""Participants: register, list, get, approve, suspend, reinstate, terminate, merchants list."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, paginate, req_str,
    sort_by_created, touch,
)
from middleware import require_roles
from response import ok
from services.cascade import terminate_participant_cascade

bp = Blueprint("participants", __name__)

READ_ROLES = {"NetworkOperator", "SponsorshipManager", "FraudAnalyst"}


@bp.post("/network/participants")
def create_participant():
    require_roles({"SponsorshipManager"})
    body = get_json()
    name = req_str(body, "name")
    sponsor_member_id = req_str(body, "sponsor_member_id")
    program_name = req_str(body, "program_name")
    sponsor = exists_or_404(db.members, sponsor_member_id, "sponsor member")
    if sponsor["status"] != "ACTIVE" or sponsor["member_kind"] not in ("ACQUIRER", "BOTH"):
        raise_err("ERR_VALIDATION", "Sponsor must be an ACTIVE member of kind ACQUIRER or BOTH")
    rec = base_record()
    rec.update({
        "name": name,
        "sponsor_member_id": sponsor_member_id,
        "program_name": program_name,
        "status": "PENDING_REVIEW",
        "fraud_attributed_count": 0,
    })
    db.participants[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/participants")
def list_participants():
    require_roles(READ_ROLES)
    items = list(db.participants.values())
    sponsor = request.args.get("sponsor_member_id")
    status = request.args.get("status")
    if sponsor is not None:
        items = [p for p in items if p["sponsor_member_id"] == sponsor]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/participants/<pid>")
def get_participant(pid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.participants, pid)
    return ok(rec, 200)


@bp.post("/network/participants/<pid>/approve")
def approve_participant(pid):
    require_roles({"SponsorshipManager"})
    rec = get_or_404(db.participants, pid)
    if rec["status"] != "PENDING_REVIEW":
        raise_err("ERR_INVALID_STATE", "Participant is not PENDING_REVIEW")
    sponsor = db.members.get(rec["sponsor_member_id"])
    if sponsor is None or sponsor["status"] != "ACTIVE":
        raise_err("ERR_SPONSOR_INACTIVE", "Sponsoring member is not ACTIVE")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/participants/<pid>/suspend")
def suspend_participant(pid):
    require_roles({"SponsorshipManager"})
    rec = get_or_404(db.participants, pid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Participant is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/participants/<pid>/reinstate")
def reinstate_participant(pid):
    require_roles({"SponsorshipManager"})
    rec = get_or_404(db.participants, pid)
    if rec["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Participant is not SUSPENDED")
    sponsor = db.members.get(rec["sponsor_member_id"])
    if sponsor is None or sponsor["status"] != "ACTIVE":
        raise_err("ERR_SPONSOR_INACTIVE", "Sponsoring member is not ACTIVE")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/participants/<pid>/terminate")
def terminate_participant(pid):
    require_roles({"SponsorshipManager"})
    rec = get_or_404(db.participants, pid)
    if rec["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Participant is not SUSPENDED")
    rec["status"] = "TERMINATED"
    touch(rec)
    terminate_participant_cascade(pid)
    return ok(rec, 200)


@bp.get("/network/participants/<pid>/merchants")
def list_participant_merchants(pid):
    require_roles(READ_ROLES)
    get_or_404(db.participants, pid)
    items = [m for m in db.merchants.values() if m.get("participant_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)

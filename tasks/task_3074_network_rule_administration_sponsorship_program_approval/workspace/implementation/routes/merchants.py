"""Merchants: board, list, get."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    REGIONS, base_record, get_json, get_or_404, is_digits, paginate, req_enum,
    req_int, sort_by_created,
)
from middleware import require_roles
from response import ok

bp = Blueprint("merchants", __name__)

READ_ROLES = {"NetworkOperator", "SponsorshipManager", "FraudAnalyst", "DisputeAnalyst"}


@bp.post("/network/merchants")
def create_merchant():
    require_roles({"SponsorshipManager"})
    body = get_json()
    participant_id = body.get("participant_id")
    acquirer_member_id = body.get("acquirer_member_id")
    mcc = body.get("mcc")
    region = req_enum(body, "region", REGIONS)
    declared = req_int(body, "declared_monthly_volume_cents")

    # Existence of referenced resources (left-to-right) before structural checks
    if participant_id is not None:
        get_or_404(db.participants, participant_id)
    if acquirer_member_id is not None:
        get_or_404(db.members, acquirer_member_id)

    # Structural: exactly one linkage set
    if (participant_id is None) == (acquirer_member_id is None):
        raise_err("ERR_VALIDATION", "Exactly one of participant_id and acquirer_member_id must be set")
    if not is_digits(mcc, 4):
        raise_err("ERR_VALIDATION", "mcc must be exactly 4 digits")
    if declared <= 0:
        raise_err("ERR_VALIDATION", "declared_monthly_volume_cents must be strictly positive")

    rec = base_record()
    rec.update({
        "participant_id": participant_id,
        "acquirer_member_id": acquirer_member_id,
        "mcc": mcc,
        "region": region,
        "declared_monthly_volume_cents": declared,
        "status": "ACTIVE",
        "fraud_monitoring_status": "NOT_MONITORED",
    })
    db.merchants[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/merchants")
def list_merchants():
    require_roles(READ_ROLES)
    items = list(db.merchants.values())
    participant_id = request.args.get("participant_id")
    acquirer_member_id = request.args.get("acquirer_member_id")
    status = request.args.get("status")
    mcc = request.args.get("mcc")
    if participant_id is not None:
        items = [m for m in items if m.get("participant_id") == participant_id]
    if acquirer_member_id is not None:
        items = [m for m in items if m.get("acquirer_member_id") == acquirer_member_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if mcc is not None:
        items = [m for m in items if m["mcc"] == mcc]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/merchants/<mid>")
def get_merchant(mid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.merchants, mid)
    return ok(rec, 200)

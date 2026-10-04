"""LicenseAgreement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, invalid_state, stale_version,
)
from middleware import require_roles
from response import success
from services.entity import stamp_new, stamp_new_log, touch


bp = Blueprint("license_agreements", __name__)

PERMITTED_USES = ("UNDERWRITING", "SETTLEMENT", "DISPLAY")


def _agreement_view(a):
    return {
        "id": a["id"],
        "licensee_ref": a["licensee_ref"],
        "permitted_uses": a["permitted_uses"],
        "monthly_event_quota": a["monthly_event_quota"],
        "fee_per_event_cents": a["fee_per_event_cents"],
        "status": a["status"],
        "activation_version": a["activation_version"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _event_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "agreement_id": e["agreement_id"],
        "event_type": e["event_type"],
        "occurred_at": e["occurred_at"],
    }


def _snapshot_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "agreement_id": s["agreement_id"],
        "methodology_version_label": s["methodology_version_label"],
        "snapshot_version": s["snapshot_version"],
    }


def _capture_snapshot(agreement):
    """Pin the latest PUBLISHED methodology. Caller is responsible for
    validating that one exists."""
    published = [m for m in DB.methodologies.values() if m["status"] == "PUBLISHED"]
    if not published:
        return None
    published.sort(key=lambda m: m["created_at"])
    latest = published[-1]
    snap = stamp_new_log({
        "agreement_id": agreement["id"],
        "methodology_version_label": latest["version_label"],
        "snapshot_version": agreement["activation_version"],
    })
    DB.snapshots[snap["id"]] = snap
    return snap


@bp.route("/license-agreements", methods=["POST"])
def create_license_agreement():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    licensee_ref = body.get("licensee_ref")
    permitted_uses = body.get("permitted_uses")
    quota = body.get("monthly_event_quota")

    if not isinstance(licensee_ref, str) or not licensee_ref:
        raise invalid_input("licensee_ref is required")
    if not isinstance(permitted_uses, list) or not permitted_uses:
        raise invalid_input("permitted_uses must be a non-empty list")
    for u in permitted_uses:
        if u not in PERMITTED_USES:
            raise invalid_input(f"permitted_uses entry {u} invalid")
    if not isinstance(quota, int) or isinstance(quota, bool):
        raise invalid_input("monthly_event_quota must be integer")
    if quota < 1 or quota > 100000:
        raise invalid_input("monthly_event_quota out of range [1, 100000]")

    a = stamp_new({
        "licensee_ref": licensee_ref,
        "permitted_uses": list(permitted_uses),
        "monthly_event_quota": quota,
        "fee_per_event_cents": 4,
        "status": "DRAFT",
        "activation_version": 0,
    })
    DB.license_agreements[a["id"]] = a
    return success(_agreement_view(a), 201)


@bp.route("/license-agreements", methods=["GET"])
def list_license_agreements():
    require_roles("ValuationAdmin")
    items = list(DB.license_agreements.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_agreement_view(a) for a in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/license-agreements/<agreement_id>", methods=["GET"])
def get_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    return success(_agreement_view(a), 200)


@bp.route("/license-agreements/<agreement_id>", methods=["PATCH"])
def patch_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    body = request.get_json(silent=True) or {}
    expected_version = body.get("expected_version")
    if expected_version is None:
        raise invalid_input("expected_version is required")
    try:
        ev = int(expected_version)
    except (TypeError, ValueError):
        raise invalid_input("expected_version must be integer")
    if ev != a["version"]:
        raise stale_version("expected_version does not match")

    if "permitted_uses" in body:
        uses = body["permitted_uses"]
        if not isinstance(uses, list) or not uses:
            raise invalid_input("permitted_uses must be non-empty list")
        for u in uses:
            if u not in PERMITTED_USES:
                raise invalid_input("permitted_uses entry invalid")
        a["permitted_uses"] = list(uses)
    if "monthly_event_quota" in body:
        q = body["monthly_event_quota"]
        if not isinstance(q, int) or isinstance(q, bool) or q < 1 or q > 100000:
            raise invalid_input("monthly_event_quota out of range")
        a["monthly_event_quota"] = q
    touch(a)
    return success(_agreement_view(a), 200)


def _require_published_methodology():
    published = [m for m in DB.methodologies.values() if m["status"] == "PUBLISHED"]
    if not published:
        raise invalid_state("no PUBLISHED methodology exists")
    return published


@bp.route("/license-agreements/<agreement_id>/activate", methods=["POST"])
def activate_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    if a["status"] != "DRAFT":
        raise invalid_state("agreement not in DRAFT")
    _require_published_methodology()
    a["activation_version"] = a.get("activation_version", 0) + 1
    a["status"] = "ACTIVE"
    touch(a)
    _capture_snapshot(a)
    return success(_agreement_view(a), 200)


@bp.route("/license-agreements/<agreement_id>/suspend", methods=["POST"])
def suspend_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    if a["status"] != "ACTIVE":
        raise invalid_state("agreement not in ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    return success(_agreement_view(a), 200)


@bp.route("/license-agreements/<agreement_id>/reactivate", methods=["POST"])
def reactivate_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    if a["status"] != "SUSPENDED":
        raise invalid_state("agreement not in SUSPENDED")
    _require_published_methodology()
    a["activation_version"] = a.get("activation_version", 0) + 1
    a["status"] = "ACTIVE"
    touch(a)
    _capture_snapshot(a)
    return success(_agreement_view(a), 200)


@bp.route("/license-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_license_agreement(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("agreement must be ACTIVE or SUSPENDED")
    a["status"] = "TERMINATED"
    touch(a)
    return success(_agreement_view(a), 200)


@bp.route("/license-agreements/<agreement_id>/events", methods=["GET"])
def list_agreement_events(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    items = [e for e in DB.license_events.values() if e["agreement_id"] == agreement_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_event_view(e) for e in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/license-agreements/<agreement_id>/snapshots", methods=["GET"])
def list_agreement_snapshots(agreement_id):
    require_roles("ValuationAdmin")
    a = DB.license_agreements.get(agreement_id)
    if a is None:
        raise not_found("agreement not found")
    items = [s for s in DB.snapshots.values() if s["agreement_id"] == agreement_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_snapshot_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)

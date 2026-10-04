"""Rating snapshots and the dispute / appeal process (PRD 3.6, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import web
from constants import (
    DISPUTE_DECISIONS,
    DISPUTE_WINDOW_DAYS,
    ROLE_BUSINESS_REP,
    ROLE_BUREAU_ADMIN,
    ROLE_STANDARDS_REVIEWER,
    SNAPSHOT_VARIANTS,
)
from errors import ApiError
from routes_core import get_business_or_404
from routes_complaints import get_complaint_or_404  # noqa: F401

bp = Blueprint("rating", __name__)

SNAPSHOT_LIST_ROLES = {ROLE_BUREAU_ADMIN, ROLE_STANDARDS_REVIEWER, ROLE_BUSINESS_REP}


def get_snapshot_or_404(snapshot_id):
    snapshot = db.STORE.rating_snapshots.get(snapshot_id)
    if snapshot is None:
        raise ApiError("ERR_SNAPSHOT_NOT_FOUND")
    return snapshot


def get_dispute_or_404(dispute_id):
    dispute = db.STORE.rating_disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")
    return dispute


def serialize_snapshot(snapshot):
    return db.serialize(snapshot)


def serialize_dispute(dispute):
    return db.serialize(dispute)


# ---------------------------------------------------------------------------
# POST /businesses/{id}/rating-snapshots
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/rating-snapshots", methods=["POST"])
def compute_snapshot(business_id):
    web.authz({ROLE_BUREAU_ADMIN})
    business = get_business_or_404(business_id)
    data = web.body()
    variant = web.require_enum(data, "variant", SNAPSHOT_VARIANTS)
    snapshot = domain.create_snapshot(business, variant)
    # publication (or provisional refresh) mutates the business's mirrored
    # current_* fields and bumps its version (PRD 3.7)
    db.touch(business)
    return web.success_object(serialize_snapshot(snapshot), status=201)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/rating-snapshots
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/rating-snapshots", methods=["GET"])
def list_snapshots(business_id):
    web.authz(SNAPSHOT_LIST_ROLES)
    get_business_or_404(business_id)
    variant = request.args.get("variant")
    items = [
        s for s in db.STORE.rating_snapshots.values()
        if s["business_id"] == business_id
    ]
    if variant is not None:
        items = [s for s in items if s["variant"] == variant]
    return web.paginated_entities(items, serialize_snapshot)


# ---------------------------------------------------------------------------
# POST /businesses/{id}/rating-disputes
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/rating-disputes", methods=["POST"])
def file_dispute(business_id):
    user_id, role = web.authz({ROLE_BUSINESS_REP})
    # priority 3: ownership on the path business id
    if user_id != business_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 4: path existence, then body-id existence
    business = get_business_or_404(business_id)
    data = web.body()
    snapshot_id = data.get("snapshot_id")
    snapshot = None
    if snapshot_id is not None:
        snapshot = db.STORE.rating_snapshots.get(snapshot_id)
        if snapshot is None:
            raise ApiError("ERR_SNAPSHOT_NOT_FOUND")
    disputed_complaint_id = data.get("disputed_complaint_id")
    complaint = None
    if disputed_complaint_id is not None:
        complaint = db.STORE.complaints.get(disputed_complaint_id)
        if complaint is None:
            raise ApiError("ERR_COMPLAINT_NOT_FOUND")
    # priority 5: schema — expected_business_version is non-optional (PRD 2.8)
    web.require_fields(data, "snapshot_id", "reason", "expected_business_version")
    if not isinstance(data.get("reason"), str) or data["reason"] == "":
        raise ApiError("ERR_INVALID_REQUEST", "reason must be a non-empty string")
    expected_version = data["expected_business_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(
            "ERR_INVALID_REQUEST", "expected_business_version must be an integer"
        )
    # priority 6: optimistic concurrency on the parent Business version
    if expected_version != business["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # priority 9: the snapshot must be one of this business's own PUBLISHED
    # snapshots; the disputed complaint must belong to this business
    if snapshot["business_id"] != business_id or snapshot["variant"] != "PUBLISHED":
        raise ApiError("ERR_SNAPSHOT_BUSINESS_MISMATCH")
    if complaint is not None and complaint["business_id"] != business_id:
        raise ApiError("ERR_SNAPSHOT_BUSINESS_MISMATCH")
    # priority 10: filing window — no later than 10 days after published_at
    now = db.now()
    if now > snapshot["published_at"] + timedelta(days=DISPUTE_WINDOW_DAYS):
        raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED")
    # FILED is zero-duration: creation commits directly to UNDER_APPEAL_REVIEW
    dispute = db.new_entity(
        "rating_disputes",
        {
            "business_id": business_id,
            "snapshot_id": snapshot_id,
            "reason": data["reason"],
            "disputed_complaint_id": disputed_complaint_id,
            "status": "UNDER_APPEAL_REVIEW",
            "filed_at": now,
        },
    )
    # side effect: filing increments the business version by 1
    db.touch(business)
    return web.success_object(serialize_dispute(dispute), status=201)


# ---------------------------------------------------------------------------
# POST /rating-disputes/{id}/appeal-decision
# ---------------------------------------------------------------------------
@bp.route("/rating-disputes/<dispute_id>/appeal-decision", methods=["POST"])
def appeal_decision(dispute_id):
    web.authz({ROLE_BUREAU_ADMIN})
    dispute = get_dispute_or_404(dispute_id)
    data = web.body()
    decision = web.require_enum(data, "decision", DISPUTE_DECISIONS)
    if dispute["status"] != "UNDER_APPEAL_REVIEW":
        raise ApiError("ERR_DISPUTE_INVALID_STATE")
    business = get_business_or_404(dispute["business_id"])
    if decision == "UPHELD":
        dispute["status"] = "UPHELD"
        db.touch(dispute)
        return web.success_object(serialize_dispute(dispute), status=200)

    # OVERRULED: the disputed complaint must name a complaint of this business
    complaint_id = dispute["disputed_complaint_id"]
    complaint = db.STORE.complaints.get(complaint_id) if complaint_id else None
    if complaint is None or complaint["business_id"] != business["id"]:
        raise ApiError("ERR_SNAPSHOT_BUSINESS_MISMATCH")
    # recompute with the disputed complaint excluded from every input set,
    # publish the superseding snapshot, and mark the old one superseded
    new_snapshot = domain.create_snapshot(
        business, "PUBLISHED", excluded_complaint_id=complaint_id
    )
    db.touch(business)
    old_snapshot = db.STORE.rating_snapshots.get(dispute["snapshot_id"])
    if old_snapshot is not None:
        old_snapshot["superseded_by_id"] = new_snapshot["id"]
        db.touch(old_snapshot)
    dispute["status"] = "OVERRULED"
    db.touch(dispute)
    return web.success_object(serialize_dispute(dispute), status=200)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/rating-disputes
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/rating-disputes", methods=["GET"])
def list_disputes(business_id):
    web.authz(SNAPSHOT_LIST_ROLES)
    get_business_or_404(business_id)
    status = request.args.get("status")
    items = [
        d for d in db.STORE.rating_disputes.values()
        if d["business_id"] == business_id
    ]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return web.paginated_entities(items, serialize_dispute)

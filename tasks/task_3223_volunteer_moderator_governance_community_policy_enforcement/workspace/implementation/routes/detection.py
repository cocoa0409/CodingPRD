"""Automated detection backlog and content-decision routes (§3.3, §3.4)."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member, current
from services import community as community_svc
from services import content

bp = Blueprint("detection", __name__)

BACKLOG_STATUSES = ("OPEN", "CONSUMED", "DISMISSED")
DECISION_STATUSES = ("RECORDED", "AUDITED", "REVISED", "SETTLED")


@bp.post("/api/communities/<community_id>/automated-detection-backlog-items")
def create_item(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    community_svc.guard_mutable(community)

    R.as_enum(data, "source_type", content.SOURCE_TYPES)
    R.as_str(data, "source_id")
    R.as_str(data, "subject_account_id")
    R.as_int(data, "signal_severity_band", low=1, high=5)
    R.as_num(data, "detection_confidence", low=0.0, high=1.0)
    R.as_num(data, "overlap_ratio", low=0.0, high=1.0)
    R.required(data, "published_at_utc")

    item = content.create_backlog_item(community, data)
    return R.ok(content.backlog_response(item), status=201)


@bp.get("/api/communities/<community_id>/automated-detection-backlog-items")
def list_items(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("AutoDetectionBacklogItem", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, BACKLOG_STATUSES)
    subject = R.query_str(request.args, "subject_account_id")
    if subject is not None:
        records = [r for r in records if r["subject_account_id"] == subject]
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/automated-detection-backlog-items/<item_id>")
def get_item(community_id, item_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    item = db.find("AutoDetectionBacklogItem", item_id)
    if item is None or item["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(content.db_to_json(item))


@bp.get("/api/accounts/<account_id>/detection-backlog")
def account_backlog(account_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    content.load_account(account_id)
    records = [r for r in db.all_of("AutoDetectionBacklogItem")
               if r["subject_account_id"] == account_id]
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, BACKLOG_STATUSES)
    return R.ok_list(records, request.args)


@bp.post("/api/communities/<community_id>/content-decisions")
def create_decision(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    community_svc.guard_mutable(community)

    R.as_str(data, "auto_detection_backlog_item_id")
    R.as_enum(data, "decision_outcome", content.DECISION_OUTCOMES)
    R.as_num(data, "decision_confidence", low=0.0, high=1.0)
    R.as_int(data, "dissection_band", low=0, high=5)
    R.as_int(data, "precedent_approval_count", low=0)
    R.as_bool(data, "community_health_index_override_present", default=False)

    decision = content.create_decision(community, data, current())
    return R.ok(R.to_json(decision), status=201)


@bp.get("/api/communities/<community_id>/content-decisions")
def list_decisions(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("ContentDecision", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, DECISION_STATUSES)
    tier = R.query_int_filter(request.args, "effective_enforcement_tier")
    records = R.filter_int(records, "effective_enforcement_tier", tier, 1, 5)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/content-decisions/<decision_id>")
def get_decision(community_id, decision_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    decision = db.find("ContentDecision", decision_id)
    if decision is None or decision["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(decision))
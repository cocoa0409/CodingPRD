"""Post and content-report routes (§3.3)."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member
from services import community as community_svc
from services import content

bp = Blueprint("posts", __name__)

POST_STATUSES = ("PUBLISHED", "REMOVED", "LOCKED")
REPORT_STATUSES = ("OPEN", "RESOLVED", "RESOLVED_LOCKED", "DISMISSED")


@bp.post("/api/communities/<community_id>/posts")
def create_post(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin")
    data = R.body(request)
    community = community_svc.fetch_or_404(community_id)
    R.as_str(data, "author_account_id")
    R.as_str(data, "title", required_=False)
    R.as_str(data, "body", required_=False)
    R.as_enum(data, "post_type", content.POST_TYPES)
    R.as_bool(data, "is_over_18", default=False)
    if community["state"] == "ARCHIVED":
        fail("ERR_ARCHIVED_COMMUNITY")
    post = content.create_post(community, data)
    return R.ok(R.to_json(post), status=201)


@bp.get("/api/communities/<community_id>/posts")
def list_posts(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("Post", "community_id", community_id)
    author = R.query_str(request.args, "author_account_id")
    if author is not None:
        records = [p for p in records if p["author_account_id"] == author]
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, POST_STATUSES)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/posts/<post_id>")
def get_post(community_id, post_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    post = db.find("Post", post_id)
    if post is None or post["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(post))


@bp.post("/api/communities/<community_id>/content-reports")
def create_report(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin")
    data = R.body(request)
    community = community_svc.fetch_or_404(community_id)
    R.as_enum(data, "content_source_type", content.SOURCE_TYPES)
    R.as_str(data, "content_source_id")
    R.as_str(data, "reporter_account_id", required_=False)
    R.as_enum(data, "report_reason_code", content.REPORT_REASONS)
    R.as_int(data, "resolution_tier", low=1, high=3)
    report = content.create_report(community, data)
    return R.ok(R.to_json(report), status=201)


@bp.get("/api/communities/<community_id>/content-reports")
def list_reports(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("ContentReport", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, REPORT_STATUSES)
    reason = R.query_str(request.args, "report_reason_code")
    records = R.filter_enum(records, "report_reason_code", reason, content.REPORT_REASONS)
    tier = R.query_int_filter(request.args, "resolution_tier")
    records = R.filter_int(records, "resolution_tier", tier, 1, 3)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/content-reports/<report_id>")
def get_report(community_id, report_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    report = db.find("ContentReport", report_id)
    if report is None or report["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(report))
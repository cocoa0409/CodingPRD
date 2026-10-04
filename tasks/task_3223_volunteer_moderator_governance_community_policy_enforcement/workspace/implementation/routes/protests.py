"""Protest routes: request, approvals, coordination and ending (§3.7)."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member, current
from services import community as community_svc
from services import protests as protest_svc

bp = Blueprint("protests", __name__)

PROTEST_STATUSES = ("REQUESTED", "COORDINATED", "ENDED")


def _load(community_id, protest_id):
    community = community_svc.fetch_or_404(community_id)
    protest = db.find("ProtestEvent", protest_id)
    if protest is None or protest["community_id"] != community_id:
        fail("ERR_PROTEST_NOT_FOUND")
    protest_svc.refresh_protest(protest)
    return community, protest


@bp.post("/api/communities/<community_id>/protests")
def request_protest(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    expected = data.get("expected_community_version")
    if expected is not None and expected != community["version"]:
        fail("ERR_STALE_VERSION")
    R.as_enum(data, "requested_access_mode", protest_svc.ACCESS_MODES)
    R.as_list(data, "conflicting_cross_power_account_ids", required_=False, default=[])
    protest = protest_svc.request_protest(community, data)
    return R.ok(R.to_json(protest), status=201)


@bp.get("/api/communities/<community_id>/protests")
def list_protests(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    protest_svc.refresh_community_protests(community_id)
    records = db.children("ProtestEvent", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, PROTEST_STATUSES)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/protests/<protest_id>")
def get_protest(community_id, protest_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    _community, protest = _load(community_id, protest_id)
    return R.ok(R.to_json(protest))


@bp.get("/api/protests/<protest_id>")
def get_protest_global(protest_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    protest = db.find("ProtestEvent", protest_id)
    if protest is None:
        fail("ERR_PROTEST_NOT_FOUND")
    protest_svc.refresh_protest(protest)
    return R.ok(R.to_json(protest))


@bp.get("/api/protests/<protest_id>/approvals")
def list_approvals_global(protest_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    if db.find("ProtestEvent", protest_id) is None:
        fail("ERR_PROTEST_NOT_FOUND")
    records = [a for a in db.all_of("ProtestApproval") if a["protest_id"] == protest_id]
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/protests/<protest_id>/approvals")
def list_approvals_scoped(community_id, protest_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    _community, protest = _load(community_id, protest_id)
    records = [a for a in db.all_of("ProtestApproval") if a["protest_id"] == protest["id"]]
    return R.ok_list(records, request.args)


@bp.post("/api/communities/<community_id>/protests/<protest_id>/approvals")
def record_approval(community_id, protest_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community, protest = _load(community_id, protest_id)
    moderator_id = R.as_str(data, "moderator_id")
    approving = R.as_str(data, "approving_account_id")
    moderator = db.find("Moderator", moderator_id)
    if moderator is None or moderator["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    protest_svc.record_approval(community, protest, moderator, approving)
    protest_svc.refresh_protest(protest)
    return R.ok(R.to_json(protest), status=201)


@bp.post("/api/communities/<community_id>/protests/<protest_id>/coordinate")
def coordinate(community_id, protest_id):
    require_roles("Moderator", "PlatformAdmin")
    require_community_member(community_id)
    community, protest = _load(community_id, protest_id)
    protest = protest_svc.coordinate(community, protest)
    return R.ok(R.to_json(protest))


@bp.post("/api/communities/<community_id>/protests/<protest_id>/end")
def end_protest(community_id, protest_id):
    require_roles("Moderator", "PlatformAdmin")
    require_community_member(community_id)
    community, protest = _load(community_id, protest_id)
    protest = protest_svc.end_protest(community, protest)
    return R.ok(R.to_json(protest))
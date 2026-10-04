"""Moderator team routes: appointment, reads and the four team mutations."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member, current
from services import community as community_svc
from services import teams

bp = Blueprint("moderators", __name__)

MODERATOR_STATUSES = ("ACTIVE", "REMOVED_FOR_INACTIVITY", "RESIGNED", "DEMOTED")
MODERATOR_ROLES = ("TOP_MODERATOR", "REGULAR_MODERATOR")


def _occ_moderator(moderator, data):
    """Priority 5 — expected_moderator_version, checked ahead of any state rule."""
    expected = data.get("expected_moderator_version")
    if expected is None:
        return
    if expected != moderator["moderator_version"]:
        fail("ERR_STALE_VERSION")


def _load_moderator(community_id, moderator_id):
    community = community_svc.fetch_or_404(community_id)
    moderator = db.find("Moderator", moderator_id)
    if moderator is None or moderator["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return community, moderator


@bp.post("/api/communities/<community_id>/moderators")
def appoint(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    expected = data.get("expected_community_version")
    if expected is not None and expected != community["version"]:
        fail("ERR_STALE_VERSION")

    R.as_str(data, "moderator_account_id")
    R.as_str(data, "display_name", required_=False)
    R.as_enum(data, "moderator_role", MODERATOR_ROLES)
    moderator = teams.appoint_moderator(community, data)
    return R.ok(R.to_json(moderator), status=201)


@bp.get("/api/communities/<community_id>/moderators")
def list_moderators(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer",
                  "SuccessionAuditor")
    community_svc.fetch_or_404(community_id)
    records = db.children("Moderator", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, MODERATOR_STATUSES)
    role = R.query_str(request.args, "moderator_role")
    records = R.filter_enum(records, "moderator_role", role, MODERATOR_ROLES)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/moderators/<moderator_id>")
def get_moderator(community_id, moderator_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer",
                  "SuccessionAuditor")
    _community, moderator = _load_moderator(community_id, moderator_id)
    return R.ok(R.to_json(moderator))


@bp.get("/api/moderators/<moderator_id>")
def get_moderator_global(moderator_id):
    require_roles("Moderator", "PlatformAdmin", "SuccessionAuditor")
    moderator = db.find("Moderator", moderator_id)
    if moderator is None:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(moderator))


@bp.get("/api/moderators/<moderator_id>/approvals")
def list_moderator_approvals(moderator_id):
    require_roles("Moderator", "PlatformAdmin", "SuccessionAuditor")
    if db.find("Moderator", moderator_id) is None:
        fail("ERR_NOT_FOUND")
    records = [a for a in db.all_of("ProtestApproval") if a["moderator_id"] == moderator_id]
    return R.ok_list(records, request.args)


@bp.get("/api/moderators/<moderator_id>/actions")
def list_moderator_actions(moderator_id):
    require_roles("Moderator", "PlatformAdmin", "SuccessionAuditor")
    if db.find("Moderator", moderator_id) is None:
        fail("ERR_NOT_FOUND")
    records = [a for a in db.all_of("ModerationAction") if a["moderator_id"] == moderator_id]
    window, meta_extra = R.paginate(records, request.args)
    payload = [{"moderator_id": r["moderator_id"], "action_kind": r["action_kind"],
                "action_at_utc": r["action_at_utc"]} for r in window]
    return {"meta": R._meta(meta_extra), "response_type": "array", "data": payload}, 200


@bp.post("/api/communities/<community_id>/moderators/<moderator_id>/remove")
def remove(community_id, moderator_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community, moderator = _load_moderator(community_id, moderator_id)
    _occ_moderator(moderator, data)
    moderator = teams.remove_moderator(community, moderator)
    return R.ok(R.to_json(moderator))


@bp.post("/api/communities/<community_id>/moderators/<moderator_id>/resign")
def resign(community_id, moderator_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community, moderator = _load_moderator(community_id, moderator_id)
    _occ_moderator(moderator, data)
    moderator = teams.resign_moderator(community, moderator)
    return R.ok(R.to_json(moderator))


@bp.post("/api/communities/<community_id>/moderators/<moderator_id>/demote")
def demote(community_id, moderator_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    community, moderator = _load_moderator(community_id, moderator_id)
    _occ_moderator(moderator, data)
    moderator = teams.demote_moderator(community, moderator, current())
    return R.ok(R.to_json(moderator))


@bp.post("/api/communities/<community_id>/moderators/<moderator_id>/reinstate")
def reinstate(community_id, moderator_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community, moderator = _load_moderator(community_id, moderator_id)
    _occ_moderator(moderator, data)
    community_svc.refresh_derived(community)
    moderator = teams.reinstate_moderator(community, moderator)
    return R.ok(R.to_json(moderator))
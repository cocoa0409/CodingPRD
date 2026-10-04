"""Local rule routes (§3.1) and the rule-escalation channel."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member
from services import community as community_svc
from services import teams

bp = Blueprint("rules", __name__)

RULE_STATUSES = ("ACTIVE", "RETIRED")


@bp.post("/api/communities/<community_id>/rules")
def create_rule(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    _occ_community(community, data)
    community_svc.guard_mutable(community)

    R.as_str(data, "rule_code")
    R.as_str(data, "rule_text", required_=False)
    band = R.as_int(data, "rule_band")
    R.as_bool(data, "is_sitewide_floor", default=False)
    if band < 1 or band > 3:
        fail("ERR_INVALID_REQUEST", "rule_band must be 1, 2 or 3")

    rule = teams.create_rule(community, data, None)
    return R.ok(R.to_json(rule), status=201)


@bp.put("/api/communities/<community_id>/rules/<rule_id>")
def update_rule(community_id, rule_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    _occ_community(community, data)
    rule = db.find("CommunityRule", rule_id)
    if rule is None or rule["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    rule = teams.update_rule(community, rule, data)
    return R.ok(R.to_json(rule))


@bp.get("/api/communities/<community_id>/rules")
def list_rules(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("CommunityRule", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, RULE_STATUSES)
    band = R.query_int_filter(request.args, "rule_band")
    records = R.filter_int(records, "rule_band", band, 1, 3)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/rules/<rule_id>")
def get_rule(community_id, rule_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    rule = db.find("CommunityRule", rule_id)
    if rule is None or rule["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return R.ok(R.to_json(rule))


@bp.post("/api/communities/<community_id>/escalations")
def escalate(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    community_svc.guard_mutable(community)

    rule_id = R.as_str(data, "rule_id")
    note = R.as_str(data, "escalation_note", required_=False, default=None)
    rule = db.find("CommunityRule", rule_id)
    if rule is None or rule["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    rule, _record = teams.escalate_rule(community, rule, note)
    return R.ok(R.to_json(rule))


def _occ_community(community, data):
    """Priority 5 — expected_community_version, checked before any state rule."""
    expected = data.get("expected_community_version")
    if expected is None:
        return
    if expected != community["version"]:
        fail("ERR_STALE_VERSION")
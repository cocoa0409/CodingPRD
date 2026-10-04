"""Team succession routes (§3.2), including the segregation-of-duties dispute."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member, current
from services import community as community_svc
from services import teams

bp = Blueprint("successions", __name__)

SUCCESSION_STATES = ("PENDING_HANDOVER", "DISCUSSION", "HANDOVER_BLOCKED", "COMPLETED")


@bp.post("/api/communities/<community_id>/successions")
def open_succession(community_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community = community_svc.fetch_or_404(community_id)
    expected = data.get("expected_community_version")
    if expected is not None and expected != community["version"]:
        fail("ERR_STALE_VERSION")
    succession = teams.open_succession(community)
    return R.ok(R.to_json(succession), status=201)


@bp.get("/api/communities/<community_id>/successions")
def list_successions(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "SuccessionAuditor")
    community_svc.fetch_or_404(community_id)
    records = db.children("TeamSuccession", "community_id", community_id)
    state = R.query_str(request.args, "state")
    records = R.filter_enum(records, "state", state, SUCCESSION_STATES)
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/successions/<succession_id>")
def get_succession(community_id, succession_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "SuccessionAuditor")
    _community, succession = _load(community_id, succession_id)
    return R.ok(R.to_json(succession))


@bp.post("/api/communities/<community_id>/successions/<succession_id>/discussions")
def discussion(community_id, succession_id):
    require_roles("Moderator", "PlatformAdmin")
    data = R.body(request)
    require_community_member(community_id)
    community, succession = _load(community_id, succession_id)
    note = data.get("round_note")
    succession = teams.record_discussion(community, succession, current(), note)
    return R.ok(R.to_json(succession))


@bp.post("/api/communities/<community_id>/successions/<succession_id>/disputes")
def dispute(community_id, succession_id):
    require_roles("Moderator", "PlatformAdmin", "SuccessionAuditor")
    data = R.body(request)
    actor = current()
    require_community_member(community_id)

    # Priority 3: segregation of duties is evaluated BEFORE the existence check
    # for the succession identifier, and before the community lookup.
    community = db.find("Community", community_id)
    if community is not None and teams.succession_sod_violation(
            community, succession_id, actor):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the author of the most recent discussion round may not open the next dispute")

    community = community_svc.fetch_or_404(community_id)
    succession = db.find("TeamSuccession", succession_id)
    if succession is None or succession["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    succession = teams.dispute_succession(community, succession, actor,
                                          data.get("dispute_note"))
    return R.ok(R.to_json(succession))


@bp.post("/api/communities/<community_id>/successions/<succession_id>/prevent")
def prevent(community_id, succession_id):
    require_roles("PlatformAdmin")
    community, succession = _load(community_id, succession_id)
    succession = teams.prevent_succession(community, succession)
    return R.ok(R.to_json(succession))


def _load(community_id, succession_id):
    community = community_svc.fetch_or_404(community_id)
    succession = db.find("TeamSuccession", succession_id)
    if succession is None or succession["community_id"] != community_id:
        fail("ERR_NOT_FOUND")
    return community, succession
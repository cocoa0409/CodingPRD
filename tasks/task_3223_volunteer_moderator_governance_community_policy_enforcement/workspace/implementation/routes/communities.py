"""Community routes: creation, reads, the logical clock and posture listings."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_community_member
from db import parse_dt, iso
from services import community as community_svc

bp = Blueprint("communities", __name__)

STATE_FILTERS = ("ACTIVE", "PROTEST_RESTRICTED", "RESTRICTED", "INSTITUTION_NEGOTIATION",
                 "QUARANTINED", "ARCHIVED")


def _serialize(community):
    return R.to_json(community)


@bp.post("/api/communities")
def create_community():
    actor = require_roles("Account", "Moderator", "PlatformAdmin")
    data = R.body(request)
    R.as_str(data, "name")
    # §3.1 lists `name` and `description` as the unconditional create inputs and
    # marks only `is_over_18` and `founding_moderator_account_id` optional.
    R.as_str(data, "description")
    R.as_bool(data, "is_over_18", default=False)
    community = community_svc.create_community(data, actor)
    return R.ok(_serialize(community), status=201)


@bp.get("/api/communities")
def list_communities():
    require_roles("Account", "Moderator", "PlatformAdmin", "Anonymous",
                  "ContentReviewer", "SuccessionAuditor")
    state = R.query_str(request.args, "state")
    records = community_svc.all_fetched()
    records = R.filter_enum(records, "state", state, STATE_FILTERS)
    tier = R.query_int_filter(request.args, "enforcement_tier")
    records = R.filter_int(records, "enforcement_tier", tier, 1, 3)
    window, meta_extra = R.paginate(records, request.args)
    payload = [_serialize(c) for c in window]
    return {"meta": R._meta(meta_extra), "response_type": "array", "data": payload}, 200


@bp.get("/api/communities/<community_id>")
def get_community(community_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "Anonymous",
                  "ContentReviewer", "SuccessionAuditor")
    community = community_svc.fetch_or_404(community_id)
    return R.ok(_serialize(community))


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    data = R.body(request)
    raw = R.required(data, "current_utc")
    moment = parse_dt(raw)
    if moment is None:
        fail("ERR_INVALID_REQUEST", "current_utc is required")
    current = db.set_clock(moment)
    return R.ok({"current_utc": iso(current)})


@bp.get("/api/communities/<community_id>/escalations")
def list_escalations(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = [r for r in db.all_of("EscalationRecord") if r["community_id"] == community_id]
    window, meta_extra = R.paginate(records, request.args)
    payload = [{"rule_id": r["rule_id"], "escalation_note": r["escalation_note"],
                "escalated_at_utc": r["escalated_at_utc"]} for r in window]
    return {"meta": R._meta(meta_extra), "response_type": "array", "data": payload}, 200


@bp.get("/api/communities/<community_id>/account-sanctions")
def list_community_sanctions(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("AccountSanction", "community_id", community_id)
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, ("ACTIVE", "LIFTED"))
    return R.ok_list(records, request.args)


@bp.get("/api/communities/<community_id>/appeals")
def list_community_appeals(community_id):
    require_roles("Moderator", "PlatformAdmin", "ContentReviewer")
    community_svc.fetch_or_404(community_id)
    records = db.children("Appeal", "community_id", community_id)
    state = R.query_str(request.args, "state")
    records = R.filter_enum(records, "state", state,
                            ("FILED", "SUBMITTED", "UNDER_WATCH", "GRANTED", "DENIED"))
    return R.ok_list(records, request.args)


@bp.post("/api/communities/<community_id>/reinstatement-requests")
def reinstatement(community_id):
    actor = require_roles("Moderator", "PlatformAdmin")
    _guard_moderator_scope(community_id)
    community = community_svc.reinstatement_request(community_id, actor)
    return R.ok(_serialize(community))


def _guard_moderator_scope(community_id):
    require_community_member(community_id)
"""Claim lifecycle: manual filing, disputes, the appeal ladder and takedown."""

from flask import Blueprint, request

import db
from errors import raise_error
from middleware import current_principal, require_creator_owns, require_role, require_rights_holder_owns
from response import ok
from routes.common import body, get_appeal, get_claim, get_content_item, get_reference_file, paginated, sort_by_created_at
from routes.serializers import claim_view
from services import claims as claim_svc

bp = Blueprint("claims", __name__, url_prefix="/api")

MIN_MATCH_CONFIDENCE = 0.500
MAX_MATCH_CONFIDENCE = 1.000
CLAIM_LEVELS = ("STANDARD", "HIGH")


def _owning_channel_of_claim(claim):
    item = db.get("content_items", claim["content_item_id"])
    return item["channel_id"] if item else None


@bp.post("/claims")
def create_manual_claim():
    role, user_id = require_role("RightsHolder", "PlatformAdmin")
    payload = body()

    reference_file_id = payload.get("reference_file_id")

    # An entity-backed rights holder may only invoke its own reference file.
    if role == "RightsHolder" and user_id != reference_file_id:
        from middleware import forbidden

        forbidden("A rights holder may act only on claims from its own reference file.")

    item = get_content_item(payload.get("content_item_id"))
    reference = get_reference_file(reference_file_id)

    confidence = payload.get("match_confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise_error("ERR_INVALID_MATCH_CONFIDENCE")
    if confidence < MIN_MATCH_CONFIDENCE or confidence > MAX_MATCH_CONFIDENCE:
        raise_error("ERR_INVALID_MATCH_CONFIDENCE")

    claim_level = payload.get("claim_level") or "STANDARD"
    if claim_level not in CLAIM_LEVELS:
        raise_error("ERR_INVALID_STATE", "claim_level must be STANDARD or HIGH.")

    claim = claim_svc.create_claim(
        content_item=item,
        reference_file=reference,
        match_confidence=confidence,
        source="MANUAL",
        claim_level=claim_level,
    )
    return ok(claim_view(claim), 201)


@bp.get("/claims")
def list_claims():
    require_role("Any")
    rows = db.all_of("claims")

    item_filter = request.args.get("content_item_id")
    reference_filter = request.args.get("reference_file_id")
    status_filter = request.args.get("status")

    if item_filter:
        rows = [c for c in rows if c["content_item_id"] == item_filter]
    if reference_filter:
        rows = [c for c in rows if c["reference_file_id"] == reference_filter]
    if status_filter:
        rows = [c for c in rows if c["status"] == status_filter]

    return paginated([claim_view(c) for c in sort_by_created_at(rows)])


@bp.get("/claims/<claim_id>")
def get_one_claim(claim_id):
    require_role("Any")
    return ok(claim_view(get_claim(claim_id)))


@bp.post("/claims/<claim_id>/dispute")
def dispute_claim(claim_id):
    require_role("Creator")
    claim = get_claim(claim_id)
    channel_id = _owning_channel_of_claim(claim)
    require_creator_owns(channel_id)

    payload = body()
    claim_svc.file_dispute(
        claim,
        payload.get("expected_claim_version"),
        payload.get("reason_code"),
        payload.get("narrative"),
    )
    return ok(claim_view(claim))


@bp.get("/claims/<claim_id>/disputes")
def list_disputes(claim_id):
    require_role("Any")
    claim = get_claim(claim_id)
    rows = claim_svc.disputes_of(claim["id"])
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.post("/claims/<claim_id>/dispute/resolve")
def resolve_dispute(claim_id):
    require_role("RightsHolder")
    claim = get_claim(claim_id)
    require_rights_holder_owns(claim)
    claim_svc.resolve_dispute(claim, body().get("resolution"))
    return ok(claim_view(claim))


@bp.post("/claims/<claim_id>/appeals")
def file_appeal(claim_id):
    require_role("RightsHolder")
    claim = get_claim(claim_id)
    require_rights_holder_owns(claim)
    appeal = claim_svc.file_appeal(claim, body().get("grounds_code"))
    return ok(dict(appeal))


@bp.get("/claims/<claim_id>/appeals")
def list_appeals(claim_id):
    require_role("Any")
    claim = get_claim(claim_id)
    rows = claim_svc.appeals_of(claim["id"])
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.post("/claims/<claim_id>/appeals/<appeal_id>/decide")
def decide_appeal(claim_id, appeal_id):
    require_role("RightsHolder")
    claim = get_claim(claim_id)
    appeal = get_appeal(claim, appeal_id)
    require_rights_holder_owns(claim)
    claim_svc.decide_appeal(claim, appeal, body().get("decision"))
    return ok(dict(appeal))


@bp.post("/claims/<claim_id>/counter-notifications")
def counter_notification(claim_id):
    require_role("Creator")
    claim = get_claim(claim_id)
    channel_id = _owning_channel_of_claim(claim)
    require_creator_owns(channel_id)
    claim_svc.file_counter_notification(claim, body().get("statement"))
    return ok(claim_view(claim))


@bp.post("/claims/<claim_id>/takedown")
def takedown(claim_id):
    require_role("RightsHolder")
    claim = get_claim(claim_id)
    require_rights_holder_owns(claim)
    claim_svc.take_down(claim)
    return ok(claim_view(claim))


@bp.get("/claims/<claim_id>/copyright-strikes")
def list_claim_copyright_strikes(claim_id):
    require_role("Any")
    claim = get_claim(claim_id)
    rows = [s for s in db.all_of("copyright_strikes") if s["claim_id"] == claim["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.get("/claims/<claim_id>/revenue-routings")
def list_claim_routings(claim_id):
    require_role("Any")
    claim = get_claim(claim_id)
    rows = [r for r in db.all_of("revenue_routings") if r["claim_id"] == claim["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])
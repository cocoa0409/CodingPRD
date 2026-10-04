"""Methodologies, rated entities, engagement letters and the logical clock."""

from flask import Blueprint, request

from auth import authed
from db import base_row, db, now, parse_ts
import domain as dom
from errors import fail
from query import apply_filters, body, paginate, to_int
from response import created, listing, ok
from services import engagement as engagement_service
from services import methodology as methodology_service

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@authed("PlatformAdmin")
def set_current_utc(actor):
    payload = body()
    instant = parse_ts(payload.get("current_utc"))
    if instant is None:
        fail("ERR_INVALID_STATE", "current_utc must be an ISO 8601 instant.")
    db.clock = instant
    return ok({})


# ---------------------------------------------------------------------------
# Methodologies
# ---------------------------------------------------------------------------
@bp.route("/methodologies", methods=["POST"])
@authed("ComplianceOfficer")
def create_methodology(actor):
    payload = body()
    row = methodology_service.create(
        payload.get("name"),
        payload.get("version_code"),
        payload.get("methodology_code"),
        payload.get("sector"),
    )
    return created(dom.methodology(row))


@bp.route("/methodologies", methods=["GET"])
@authed("Any")
def list_methodologies(actor):
    rows = apply_filters(
        list(db.methodologies.values()),
        ("methodology_code", "sector", "status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.methodology(r) for r in window], limit, offset, total)


@bp.route("/methodologies/<methodology_id>", methods=["GET"])
@authed("Any")
def get_methodology(actor, methodology_id):
    row = db.methodologies.get(methodology_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.methodology(row))


@bp.route("/methodologies/<methodology_id>/publish", methods=["POST"])
@authed("ComplianceOfficer")
def publish_methodology(actor, methodology_id):
    row = db.methodologies.get(methodology_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.methodology(methodology_service.publish(row)))


@bp.route("/methodologies/<methodology_id>/publish-disclosure", methods=["POST"])
@authed("ComplianceOfficer")
def publish_methodology_disclosure(actor, methodology_id):
    row = db.methodologies.get(methodology_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.methodology(methodology_service.publish_disclosure(row)))


@bp.route("/methodologies/<methodology_id>/supersede", methods=["POST"])
@authed("ComplianceOfficer")
def supersede_methodology(actor, methodology_id):
    row = db.methodologies.get(methodology_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.methodology(methodology_service.supersede(row)))


# ---------------------------------------------------------------------------
# Rated entities
# ---------------------------------------------------------------------------
@bp.route("/rated-entities", methods=["POST"])
@authed("EngagementManager")
def create_rated_entity(actor):
    payload = body()
    methodology_id = payload.get("methodology_id")
    if methodology_id is None or methodology_id not in db.methodologies:
        fail("ERR_METHODOLOGY_NOT_FOUND")

    row = base_row()
    row.update(
        {
            "legal_name": payload.get("legal_name"),
            "sector": payload.get("sector"),
            "domicile_country": payload.get("domicile_country"),
            "revenue_band": payload.get("revenue_band"),
            "methodology_id": methodology_id,
            "solicitation_status": payload.get("solicitation_status") or "SOLICITED",
            "surveillance_posture": "NORMAL",
            "first_rated_at": None,
            "current_grade": None,
        }
    )
    db.rated_entities[row["id"]] = row
    return created(dom.rated_entity(row))


@bp.route("/rated-entities", methods=["GET"])
@authed("Any")
def list_rated_entities(actor):
    rows = apply_filters(
        list(db.rated_entities.values()),
        ("methodology_id", "sector", "solicitation_status", "surveillance_posture"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.rated_entity(r) for r in window], limit, offset, total)


@bp.route("/rated-entities/<rated_entity_id>", methods=["GET"])
@authed("Any")
def get_rated_entity(actor, rated_entity_id):
    row = db.rated_entities.get(rated_entity_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rated_entity(row))


# ---------------------------------------------------------------------------
# Engagement letters
# ---------------------------------------------------------------------------
@bp.route("/engagement-letters", methods=["POST"])
@authed("EngagementManager")
def create_engagement_letter(actor):
    payload = body()
    entity_id = payload.get("rated_entity_id")
    if entity_id is None or entity_id not in db.rated_entities:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = engagement_service.create(
        entity_id,
        payload.get("fee_amount_cents"),
        payload.get("fee_structure"),
        payload.get("fee_payer_is_issuer"),
        payload.get("signed_at"),
    )
    return created(dom.engagement_letter(row))


@bp.route("/engagement-letters", methods=["GET"])
@authed("Any")
def list_engagement_letters(actor):
    rows = apply_filters(
        list(db.engagement_letters.values()), ("rated_entity_id", "status")
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.engagement_letter(r) for r in window], limit, offset, total)


@bp.route("/engagement-letters/<engagement_letter_id>", methods=["GET"])
@authed("Any")
def get_engagement_letter(actor, engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.engagement_letter(row))


@bp.route("/engagement-letters/<engagement_letter_id>/submit", methods=["POST"])
@authed("EngagementManager")
def submit_engagement_letter(actor, engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.engagement_letter(engagement_service.submit(row)))


@bp.route("/engagement-letters/<engagement_letter_id>/activate", methods=["POST"])
@authed("EngagementManager")
def activate_engagement_letter(actor, engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.engagement_letter(engagement_service.activate(row)))


@bp.route("/engagement-letters/<engagement_letter_id>/revert-to-draft", methods=["POST"])
@authed("EngagementManager")
def revert_engagement_letter(actor, engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.engagement_letter(engagement_service.revert_to_draft(row)))


@bp.route("/engagement-letters/<engagement_letter_id>/terminate", methods=["POST"])
@authed("EngagementManager")
def terminate_engagement_letter(actor, engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.engagement_letter(engagement_service.terminate(row)))
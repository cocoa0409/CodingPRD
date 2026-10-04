"""Rating requests and analysts."""

from flask import Blueprint

from auth import authed, require_own_analyst
from db import db
import domain as dom
from errors import fail
from query import apply_filters, body, paginate, bool_param
from response import created, listing, ok
from services import analysts as analyst_service
from services import requests as request_service

bp = Blueprint("requests", __name__)


# ---------------------------------------------------------------------------
# Rating requests
# ---------------------------------------------------------------------------
@bp.route("/rating-requests", methods=["POST"])
@authed("EngagementManager")
def create_rating_request(actor):
    payload = body()
    # PRD §3.2 pins the intake payload; an intake missing a declared field is a
    # malformed request, rejected with the malformed-request error.
    required = (
        "engagement_letter_id",
        "rated_entity_id",
        "instrument_type",
        "instrument_notional_cents",
        "requested_rating_scale",
    )
    if any(field not in payload for field in required):
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    engagement_letter_id = payload.get("engagement_letter_id")
    if engagement_letter_id is None or engagement_letter_id not in db.engagement_letters:
        fail("ERR_ENGAGEMENT_NOT_FOUND")
    rated_entity_id = payload.get("rated_entity_id")
    if rated_entity_id is None or rated_entity_id not in db.rated_entities:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = request_service.create(
        engagement_letter_id,
        rated_entity_id,
        payload.get("instrument_type"),
        payload.get("instrument_notional_cents"),
        payload.get("requested_rating_scale"),
    )
    return created(dom.rating_request(row))


@bp.route("/rating-requests", methods=["GET"])
@authed("Any")
def list_rating_requests(actor):
    rows = apply_filters(
        list(db.rating_requests.values()),
        ("engagement_letter_id", "rated_entity_id", "request_status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.rating_request(r) for r in window], limit, offset, total)


@bp.route("/rating-requests/<rating_request_id>", methods=["GET"])
@authed("Any")
def get_rating_request(actor, rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_request(row))


@bp.route("/rating-requests/<rating_request_id>/open-screening", methods=["POST"])
@authed("ComplianceOfficer")
def open_screening(actor, rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_request(request_service.open_screening(row)))


@bp.route("/rating-requests/<rating_request_id>/return-to-submitted", methods=["POST"])
@authed("ComplianceOfficer")
def return_to_submitted(actor, rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_request(request_service.return_to_submitted(row)))


@bp.route("/rating-requests/<rating_request_id>/confirm-team", methods=["POST"])
@authed("ComplianceOfficer")
def confirm_team(actor, rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_request(request_service.confirm_team(row)))


@bp.route("/rating-requests/<rating_request_id>/withdraw", methods=["POST"])
@authed("EngagementManager")
def withdraw_request(actor, rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_request(request_service.withdraw(row)))


# ---------------------------------------------------------------------------
# Analysts
# ---------------------------------------------------------------------------
@bp.route("/analysts", methods=["POST"])
@authed("ComplianceOfficer")
def create_analyst(actor):
    payload = body()
    row = analyst_service.create(
        payload.get("full_name"),
        payload.get("primary_sector"),
        payload.get("analyst_tier"),
        payload.get("independence_declared_at"),
    )
    return created(dom.analyst(row))


@bp.route("/analysts", methods=["GET"])
@authed("Any")
def list_analysts(actor):
    rows = list(db.analysts.values())
    for field in ("primary_sector", "departed_to_entity_id"):
        value = _arg(field)
        if value is not None:
            rows = [r for r in rows if str(r.get(field)) == value]
    for field in ("is_departed", "rotation_eligible"):
        value = bool_param(field)
        if value is not None:
            rows = [r for r in rows if bool(r.get(field)) is value]
    window, limit, offset, total = paginate(rows)
    return listing([dom.analyst(r) for r in window], limit, offset, total)


def _arg(name):
    from flask import request

    return request.args.get(name)


@bp.route("/analysts/<analyst_id>", methods=["GET"])
@authed("Any")
def get_analyst(actor, analyst_id):
    row = db.analysts.get(analyst_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.analyst(row))


@bp.route("/analysts/<analyst_id>/team-assignments", methods=["GET"])
@authed("Any")
def analyst_team_assignments(actor, analyst_id):
    require_own_analyst(actor, analyst_id)
    rows = [
        r
        for r in db.team_assignments.values()
        if analyst_id in (r["lead_analyst_id"], r["support_analyst_id"])
    ]
    window, limit, offset, total = paginate(rows)
    return listing([dom.team_assignment(r) for r in window], limit, offset, total)


@bp.route("/analysts/<analyst_id>/votes", methods=["GET"])
@authed("Any")
def analyst_votes(actor, analyst_id):
    require_own_analyst(actor, analyst_id)
    rows = [r for r in db.committee_votes.values() if r["analyst_id"] == analyst_id]
    window, limit, offset, total = paginate(rows)
    return listing([dom.committee_vote(r) for r in window], limit, offset, total)


@bp.route("/analysts/<analyst_id>/conflict-screenings", methods=["GET"])
@authed("Any")
def analyst_conflict_screenings(actor, analyst_id):
    require_own_analyst(actor, analyst_id)
    rows = [r for r in db.conflict_screenings.values() if r["analyst_id"] == analyst_id]
    window, limit, offset, total = paginate(rows)
    return listing([dom.conflict_screening(r) for r in window], limit, offset, total)


@bp.route("/analysts/<analyst_id>/depart", methods=["POST"])
@authed("ComplianceOfficer")
def depart_analyst(actor, analyst_id):
    row = db.analysts.get(analyst_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    return ok(
        dom.analyst(
            analyst_service.depart(
                row, payload.get("departed_to_entity_id"), payload.get("departure_date")
            )
        )
    )